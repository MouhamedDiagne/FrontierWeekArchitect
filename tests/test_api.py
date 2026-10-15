import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import (
    ConversationNotFoundError,
    DashboardUnavailableError,
    create_app,
)
from app.models import (
    AudienceReport,
    AudienceReportScope,
    ConversationTurnResult,
    FeedbackAnalysisResult,
    FeedbackInsightsDataQuality,
    FeedbackInsightsRequest,
    FeedbackInsightsResult,
    FeedbackInsightsSnapshot,
    FeedbackSubmissionResult,
    FeedbackType,
    InsightRunSource,
    SentimentLabel,
    SoftwareReference,
    UserProfile,
)


class FakeRuntime:
    def __init__(self) -> None:
        self.started = False
        self.shutdown_called = False
        self.sessions: set[str] = set()
        self.messages: list[tuple[str, str]] = []
        self.submissions: list[dict[str, object]] = []
        request = FeedbackInsightsRequest(
            start_date=datetime(2026, 10, 1, tzinfo=timezone.utc),
            end_date=datetime(2026, 11, 1, tzinfo=timezone.utc),
            software_id="targetym_ai",
            audience_profile=UserProfile.MANAGEMENT,
        )
        insights = FeedbackInsightsResult(
            request=request,
            total_feedbacks=4,
            clustered_feedbacks=3,
            clusters=[],
            data_quality=FeedbackInsightsDataQuality(
                records_with_summary=4,
                records_using_raw_fallback=0,
                records_without_usable_representation=0,
            ),
            limitations=[],
        )
        self.snapshot: FeedbackInsightsSnapshot | None = FeedbackInsightsSnapshot(
            generated_at=datetime(2026, 10, 7, 10, tzinfo=timezone.utc),
            source=InsightRunSource.MANUAL,
            insights=insights,
            audience_report=AudienceReport(
                profile=UserProfile.MANAGEMENT,
                scope=AudienceReportScope(
                    period="October 2026",
                    software_id="targetym_ai",
                    functionality_id=None,
                ),
                executive_focus="Priorities",
                priority_signal_ids=[],
                positive_signal_ids=[],
                watch_list_ids=[],
                suggested_follow_up_types=[],
                limitations=[],
            ),
        )

    @property
    def ready(self) -> bool:
        return self.started and not self.shutdown_called

    def start(self) -> None:
        self.started = True

    def create_conversation(self) -> str:
        session_id = f"session-{len(self.sessions) + 1}"
        self.sessions.add(session_id)
        return session_id

    def send_message(self, session_id: str, message: str) -> ConversationTurnResult:
        if session_id not in self.sessions:
            raise ConversationNotFoundError(session_id)
        if message == "raise-service-error":
            raise RuntimeError("provider details must not reach the caller")
        self.messages.append((session_id, message))
        return ConversationTurnResult(
            reply="The feedback was analysed.",
            analysis=FeedbackAnalysisResult(
                software=SoftwareReference(id="targetym_ai", name="Targetym AI"),
                sentiment=SentimentLabel.NEGATIVE,
                percentage=0.9,
                language="en",
                feedback_type=FeedbackType.ISSUE_REPORT,
                problem_category="bug_error",
                feedback_summary="The report export fails.",
            ),
            feedback_record_id="feedback-1",
        )

    def close_conversation(self, session_id: str) -> None:
        if session_id not in self.sessions:
            raise ConversationNotFoundError(session_id)
        self.sessions.remove(session_id)

    def submit_feedback(
        self,
        *,
        feedback: str,
        software_id: str,
        received_at,
        analyzed_at,
    ) -> FeedbackSubmissionResult:
        if feedback == "raise-service-error":
            raise RuntimeError("provider details must not reach the caller")
        self.submissions.append(
            {
                "feedback": feedback,
                "software_id": software_id,
                "received_at": received_at,
                "analyzed_at": analyzed_at,
            }
        )
        return FeedbackSubmissionResult(
            analysis=FeedbackAnalysisResult(
                software=SoftwareReference(id=software_id, name="Targetym AI"),
                sentiment=SentimentLabel.NEGATIVE,
                percentage=0.9,
                language="en",
                feedback_type=FeedbackType.ISSUE_REPORT,
                problem_category="bug_error",
                feedback_summary="The report export fails.",
            ),
            feedback_record_id="feedback-submission-1",
        )

    def latest_insights_snapshot(self) -> FeedbackInsightsSnapshot | None:
        return self.snapshot

    def shutdown(self) -> None:
        self.shutdown_called = True
        self.sessions.clear()


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = FakeRuntime()
        self.client = TestClient(create_app(runtime_factory=lambda: self.runtime))
        self.client.__enter__()

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)

    def test_creates_conversation_and_returns_structured_turn(self):
        health = self.client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json(), {"status": "ready"})

        created = self.client.post("/api/conversations")
        self.assertEqual(created.status_code, 201)
        session_id = created.json()["session_id"]

        response = self.client.post(
            f"/api/conversations/{session_id}/messages",
            json={"message": "Please analyse the report export failure."},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["reply"], "The feedback was analysed.")
        self.assertEqual(payload["feedback_record_id"], "feedback-1")
        self.assertEqual(payload["analysis"]["sentiment"], "negative")
        self.assertEqual(self.runtime.messages[0][0], session_id)

    def test_protects_api_routes_when_an_access_token_is_configured(self):
        runtime = FakeRuntime()
        app = create_app(
            runtime_factory=lambda: runtime,
            api_access_token="test-token",
            environment="production",
        )
        with TestClient(app) as protected_client:
            self.assertEqual(protected_client.get("/health").status_code, 200)
            self.assertEqual(
                protected_client.post("/api/conversations").status_code,
                401,
            )
            self.assertEqual(
                protected_client.post(
                    "/api/conversations",
                    headers={"X-Feedback-API-Key": "wrong-token"},
                ).status_code,
                401,
            )
            self.assertEqual(
                protected_client.post(
                    "/api/conversations",
                    headers={"X-Feedback-API-Key": "test-token"},
                ).status_code,
                201,
            )

    def test_production_api_requires_an_access_token_during_startup(self):
        app = create_app(
            runtime_factory=FakeRuntime,
            api_access_token="",
            environment="production",
        )
        with self.assertRaises(RuntimeError):
            with TestClient(app):
                pass

    def test_rejects_unknown_or_closed_conversation(self):
        unknown = self.client.post(
            "/api/conversations/unknown/messages",
            json={"message": "Hello"},
        )
        self.assertEqual(unknown.status_code, 404)

        session_id = self.client.post("/api/conversations").json()["session_id"]
        closed = self.client.delete(f"/api/conversations/{session_id}")
        self.assertEqual(closed.status_code, 204)

        repeated_close = self.client.delete(f"/api/conversations/{session_id}")
        self.assertEqual(repeated_close.status_code, 404)

    def test_validates_message_before_runtime_call(self):
        session_id = self.client.post("/api/conversations").json()["session_id"]

        response = self.client.post(
            f"/api/conversations/{session_id}/messages",
            json={"message": "   "},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.runtime.messages, [])

    def test_hides_runtime_error_details(self):
        session_id = self.client.post("/api/conversations").json()["session_id"]

        response = self.client.post(
            f"/api/conversations/{session_id}/messages",
            json={"message": "raise-service-error"},
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["detail"],
            "The feedback service is temporarily unavailable. Please try again.",
        )

    def test_submits_feedback_without_creating_a_conversation(self):
        response = self.client.post(
            "/api/feedbacks",
            json={
                "software_id": "targetym_ai",
                "feedback": "The report export fails.",
                "received_at": "2026-10-07T09:30:00Z",
                "analyzed_at": "2026-10-07T11:35:00+02:00",
            },
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["feedback_record_id"], "feedback-submission-1")
        self.assertEqual(response.json()["analysis"]["software"]["id"], "targetym_ai")
        self.assertEqual(self.runtime.sessions, set())
        self.assertEqual(
            self.runtime.submissions,
            [
                {
                    "feedback": "The report export fails.",
                    "software_id": "targetym_ai",
                    "received_at": datetime(2026, 10, 7, 9, 30, tzinfo=timezone.utc),
                    "analyzed_at": datetime(2026, 10, 7, 9, 35, tzinfo=timezone.utc),
                }
            ],
        )

    def test_accepts_received_at_without_analyzed_at(self):
        response = self.client.post(
            "/api/feedbacks",
            json={
                "software_id": "targetym_ai",
                "feedback": "The report export fails.",
                "received_at": "2026-10-07T09:30:00Z",
            },
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            self.runtime.submissions,
            [
                {
                    "feedback": "The report export fails.",
                    "software_id": "targetym_ai",
                    "received_at": datetime(2026, 10, 7, 9, 30, tzinfo=timezone.utc),
                    "analyzed_at": None,
                }
            ],
        )

    def test_validates_a_feedback_submission_before_runtime_call(self):
        no_timezone = self.client.post(
            "/api/feedbacks",
            json={
                "software_id": "targetym_ai",
                "feedback": "The report export fails.",
                "received_at": "2026-10-07T09:30:00",
            },
        )
        self.assertEqual(no_timezone.status_code, 422)

        analyzed_at_without_timezone = self.client.post(
            "/api/feedbacks",
            json={
                "software_id": "targetym_ai",
                "feedback": "The report export fails.",
                "analyzed_at": "2026-10-07T09:30:00",
            },
        )
        self.assertEqual(analyzed_at_without_timezone.status_code, 422)

        analyzed_at_without_received_at = self.client.post(
            "/api/feedbacks",
            json={
                "software_id": "targetym_ai",
                "feedback": "The report export fails.",
                "analyzed_at": "2026-10-07T09:30:00Z",
            },
        )
        self.assertEqual(analyzed_at_without_received_at.status_code, 422)

        analyzed_before_received = self.client.post(
            "/api/feedbacks",
            json={
                "software_id": "targetym_ai",
                "feedback": "The report export fails.",
                "received_at": "2026-10-07T09:30:00Z",
                "analyzed_at": "2026-10-07T09:29:59Z",
            },
        )
        self.assertEqual(analyzed_before_received.status_code, 422)

        blank = self.client.post(
            "/api/feedbacks",
            json={
                "software_id": "targetym_ai",
                "feedback": "   ",
            },
        )
        self.assertEqual(blank.status_code, 422)

    def test_hides_feedback_submission_error_details(self):
        response = self.client.post(
            "/api/feedbacks",
            json={
                "software_id": "targetym_ai",
                "feedback": "raise-service-error",
            },
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["detail"],
            "The feedback service is temporarily unavailable. Please try again.",
        )

    def test_returns_the_latest_saved_dashboard_snapshot(self):
        response = self.client.get("/api/dashboard/latest")

        self.assertEqual(response.status_code, 200)
        snapshot = response.json()["snapshot"]
        self.assertEqual(snapshot["source"], "manual")
        self.assertEqual(snapshot["insights"]["total_feedbacks"], 4)
        self.assertEqual(snapshot["audience_report"]["profile"], "management")

    def test_dashboard_returns_not_found_when_no_snapshot_exists(self):
        self.runtime.snapshot = None

        response = self.client.get("/api/dashboard/latest")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json()["detail"],
            "No saved insight analysis is available yet.",
        )

    def test_dashboard_hides_invalid_snapshot_visualization_details(self):
        with patch(
            "app.api.FeedbackVisualizationBuilder.build",
            side_effect=ValueError("invalid snapshot payload"),
        ):
            response = self.client.get("/api/dashboard/latest")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["detail"],
            "The feedback service is temporarily unavailable. Please try again.",
        )

    def test_shutdown_is_called_by_lifespan(self):
        self.assertTrue(self.runtime.started)
        self.assertFalse(self.runtime.shutdown_called)


if __name__ == "__main__":
    unittest.main()
