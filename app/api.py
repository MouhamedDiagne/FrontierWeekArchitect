"""Local HTTP boundary for the Streamlit feedback-assistant prototype.

The API deliberately owns no business rules.  It keeps the existing Foundry
agent and Dataverse repository on the server side, while browser-facing clients
receive only validated domain results.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import RLock
from typing import Protocol, cast
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .agents import FeedbackAnalyzerAgent
from .config import DATAVERSE_INSIGHT_ANALYSIS_TABLE
from .conversation import ConversationSession
from .dataverse import (
    DataverseFeedbackRepository,
    DataverseInsightAnalysisRepository,
    InsightsSnapshotRepository,
)
from .errors import _error_was_logged, _log_error
from .models import (
    ConversationMessage,
    ConversationTurnResult,
    FeedbackInput,
    FeedbackInsightsSnapshot,
    FeedbackSubmissionResult,
)
from .utils import _log
from .visualizations import FeedbackVisualizationBuilder, FeedbackVisualizations


class ConversationNotFoundError(KeyError):
    """Raised when an API caller refers to a closed or unknown session."""


class DashboardUnavailableError(RuntimeError):
    """Raised when snapshot persistence is not configured for this POC API."""


class ConversationRuntime(Protocol):
    """Small runtime contract that lets API tests avoid Azure dependencies."""

    @property
    def ready(self) -> bool:
        ...

    def start(self) -> None:
        ...

    def create_conversation(self) -> str:
        ...

    def send_message(
        self,
        session_id: str,
        message: str,
    ) -> ConversationTurnResult:
        ...

    def close_conversation(self, session_id: str) -> None:
        ...

    def submit_feedback(
        self,
        *,
        feedback: str,
        software_id: str,
        received_at: datetime | None,
    ) -> FeedbackSubmissionResult:
        ...

    def latest_insights_snapshot(self) -> FeedbackInsightsSnapshot | None:
        ...

    def shutdown(self) -> None:
        ...


@dataclass
class FeedbackAgentRuntime:
    """One process-local Foundry agent and its short-lived conversations.

    Session state is intentionally kept in memory for the POC.  It therefore
    disappears when the API process restarts; neither the browser nor Streamlit
    receives an Azure, Foundry, or Dataverse credential.
    """

    verbose: bool = True
    _agent: FeedbackAnalyzerAgent | None = field(default=None, init=False)
    _snapshot_repository: InsightsSnapshotRepository | None = field(
        default=None,
        init=False,
    )
    _sessions: dict[str, ConversationSession] = field(default_factory=dict, init=False)
    _lock: RLock = field(default_factory=RLock, init=False)

    @property
    def ready(self) -> bool:
        return self._agent is not None

    def start(self) -> None:
        with self._lock:
            if self._agent is not None:
                return

            _log("api", "Creating the Dataverse repository for the HTTP API.", verbose=self.verbose)
            repository = DataverseFeedbackRepository.from_environment(verbose=self.verbose)
            snapshot_repository = None
            if DATAVERSE_INSIGHT_ANALYSIS_TABLE:
                snapshot_repository = DataverseInsightAnalysisRepository.from_environment(
                    verbose=self.verbose
                )
            else:
                _log(
                    "api",
                    "Insight snapshot persistence is disabled until DATAVERSE_INSIGHT_ANALYSIS_TABLE is configured.",
                    verbose=self.verbose,
                )
            agent = FeedbackAnalyzerAgent(
                feedback_repository=repository,
                feedback_reader=repository,
                insights_snapshot_repository=snapshot_repository,
                verbose=self.verbose,
            )
            _log("api", "Creating the shared Foundry agent for the HTTP API.", verbose=self.verbose)
            agent.create()
            self._agent = agent
            self._snapshot_repository = snapshot_repository

    def _require_agent(self) -> FeedbackAnalyzerAgent:
        if self._agent is None:
            raise RuntimeError("The feedback API has not completed startup.")
        return self._agent

    def create_conversation(self) -> str:
        with self._lock:
            session = self._require_agent().start_conversation()
            public_session_id = str(uuid4())
            self._sessions[public_session_id] = session
            _log("api", f"Created API conversation {public_session_id}.", verbose=self.verbose)
            return public_session_id

    def _get_session(self, session_id: str) -> ConversationSession:
        try:
            return self._sessions[session_id]
        except KeyError as error:
            raise ConversationNotFoundError(session_id) from error

    def send_message(
        self,
        session_id: str,
        message: str,
    ) -> ConversationTurnResult:
        # Serializing turns is intentional: Foundry conversation ordering and
        # user-message grounding must not be raced by two browser requests.
        with self._lock:
            session = self._get_session(session_id)
            return self._require_agent().send_message(session, message)

    def close_conversation(self, session_id: str) -> None:
        with self._lock:
            session = self._get_session(session_id)
            agent = self._require_agent()
            try:
                agent.close_conversation(session)
            finally:
                self._sessions.pop(session_id, None)
            _log("api", f"Closed API conversation {session_id}.", verbose=self.verbose)

    def submit_feedback(
        self,
        *,
        feedback: str,
        software_id: str,
        received_at: datetime | None,
    ) -> FeedbackSubmissionResult:
        """Analyse one explicit submission without creating a chat session."""

        # The analysis uses the same shared OpenAI client as conversations.
        # Serializing it keeps the POC deterministic and avoids concurrent use
        # of one temporary Foundry agent/runtime while a conversational turn is
        # processing tool results.
        with self._lock:
            return self._require_agent().analyze_and_save_feedback(
                feedback=feedback,
                software_id=software_id,
                received_at=received_at,
            )

    def latest_insights_snapshot(self) -> FeedbackInsightsSnapshot | None:
        """Read the last persisted analysis for the local read-only dashboard."""

        with self._lock:
            if self._snapshot_repository is None:
                raise DashboardUnavailableError(
                    "Insight snapshot persistence is not configured."
                )
            return self._snapshot_repository.latest_snapshot()

    def shutdown(self) -> None:
        with self._lock:
            agent = self._agent
            if agent is None:
                return

            for session_id in tuple(self._sessions):
                try:
                    self.close_conversation(session_id)
                except Exception as error:
                    _log_error("api", "conversation_cleanup_failed", error)

            try:
                agent.cleanup()
            finally:
                self._agent = None
                self._snapshot_repository = None
                self._sessions.clear()


class ConversationCreated(BaseModel):
    """Public session identifier returned to the Streamlit server."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)


class ApiHealth(BaseModel):
    """Process health only; it deliberately does not probe remote services."""

    model_config = ConfigDict(extra="forbid")

    status: str


class FeedbackSubmission(FeedbackInput):
    """Validated POC payload accepted from a future form or integration."""

    received_at: datetime | None = None

    @field_validator("received_at")
    @classmethod
    def normalize_received_at(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("received_at must include a timezone")
        return value.astimezone(timezone.utc)


class LatestInsightsDashboard(BaseModel):
    """One immutable Dataverse snapshot rendered by the POC dashboard."""

    model_config = ConfigDict(extra="forbid")

    snapshot: FeedbackInsightsSnapshot
    visualizations: FeedbackVisualizations


def _get_runtime(request: Request) -> ConversationRuntime:
    return cast(ConversationRuntime, request.app.state.feedback_runtime)


def _raise_service_unavailable(error: Exception, *, operation: str) -> None:
    if not _error_was_logged(error):
        _log_error("api", f"{operation}_failed", error)
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="The feedback service is temporarily unavailable. Please try again.",
    ) from error


def create_app(
    *,
    runtime_factory: Callable[[], ConversationRuntime] | None = None,
) -> FastAPI:
    """Build the API application, with an injectable runtime for local tests."""

    selected_runtime_factory = runtime_factory or (lambda: FeedbackAgentRuntime())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime = selected_runtime_factory()
        try:
            runtime.start()
        except Exception as error:
            _raise_service_unavailable(error, operation="startup")
        app.state.feedback_runtime = runtime
        try:
            yield
        finally:
            try:
                runtime.shutdown()
            except Exception as error:
                if not _error_was_logged(error):
                    _log_error("api", "shutdown_failed", error)

    app = FastAPI(
        title="Agiltym Feedback API",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.get("/health", response_model=ApiHealth)
    def health(request: Request) -> ApiHealth:
        runtime = _get_runtime(request)
        return ApiHealth(status="ready" if runtime.ready else "starting")

    @app.post(
        "/api/conversations",
        response_model=ConversationCreated,
        status_code=status.HTTP_201_CREATED,
    )
    def create_conversation(request: Request) -> ConversationCreated:
        try:
            return ConversationCreated(session_id=_get_runtime(request).create_conversation())
        except Exception as error:
            _raise_service_unavailable(error, operation="conversation_creation")

    @app.post(
        "/api/conversations/{session_id}/messages",
        response_model=ConversationTurnResult,
    )
    def send_message(
        session_id: str,
        payload: ConversationMessage,
        request: Request,
    ) -> ConversationTurnResult:
        try:
            return _get_runtime(request).send_message(session_id, payload.message)
        except ConversationNotFoundError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found. Start a new conversation.",
            ) from error
        except Exception as error:
            _raise_service_unavailable(error, operation="conversation_turn")

    @app.delete(
        "/api/conversations/{session_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def close_conversation(session_id: str, request: Request) -> Response:
        try:
            _get_runtime(request).close_conversation(session_id)
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        except ConversationNotFoundError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found or already closed.",
            ) from error
        except Exception as error:
            _raise_service_unavailable(error, operation="conversation_close")

    @app.post(
        "/api/feedbacks",
        response_model=FeedbackSubmissionResult,
        status_code=status.HTTP_201_CREATED,
    )
    def submit_feedback(
        payload: FeedbackSubmission,
        request: Request,
    ) -> FeedbackSubmissionResult:
        """Receive one explicit feedback submission from a local POC source.

        This endpoint is deliberately localhost-only with the API server.  It
        is not an Internet-facing form endpoint until authentication,
        idempotency, and source traceability are separately implemented.
        """

        try:
            return _get_runtime(request).submit_feedback(
                feedback=payload.feedback,
                software_id=payload.software_id,
                received_at=payload.received_at,
            )
        except Exception as error:
            _raise_service_unavailable(error, operation="feedback_submission")

    @app.get(
        "/api/dashboard/latest",
        response_model=LatestInsightsDashboard,
    )
    def latest_insights_dashboard(request: Request) -> LatestInsightsDashboard:
        """Return the latest saved snapshot without re-running clustering."""

        try:
            snapshot = _get_runtime(request).latest_insights_snapshot()
        except DashboardUnavailableError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Insight snapshot persistence is not configured for this service."
                ),
            ) from error
        except Exception as error:
            _raise_service_unavailable(error, operation="dashboard_snapshot_read")

        if snapshot is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No saved insight analysis is available yet.",
            )
        try:
            visualizations = FeedbackVisualizationBuilder.build(
                snapshot.insights,
                snapshot.audience_report,
            )
        except Exception as error:
            _raise_service_unavailable(error, operation="dashboard_visualization")
        return LatestInsightsDashboard(
            snapshot=snapshot,
            visualizations=visualizations,
        )

    return app


app = create_app()
