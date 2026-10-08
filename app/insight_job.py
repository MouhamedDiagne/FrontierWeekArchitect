"""Run one persisted historical-feedback analysis from the local command line.

This module intentionally does not create a Foundry routine, Azure Function, or
Power Automate flow.  It is a small POC command that an operating-system task
scheduler can invoke after the required Dataverse snapshot table has been
configured.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol, TextIO, cast

from pydantic import ValidationError

from .agents import FeedbackAnalyzerAgent
from .dataverse import (
    DataverseFeedbackRepository,
    DataverseInsightAnalysisRepository,
    FeedbackReader,
    FeedbackRepository,
    InsightsSnapshotRepository,
)
from .errors import _error_was_logged, _log_error
from .models import (
    FeedbackInsightsRequest,
    InsightRunSource,
    InsightsAnalysisRunResult,
    UserProfile,
)


EXIT_SUCCESS = 0
EXIT_INVALID_ARGUMENTS = 2
EXIT_SETUP_FAILED = 3
EXIT_ANALYSIS_FAILED = 4
EXIT_CLEANUP_FAILED = 5
EXIT_INTERRUPTED = 130


class InsightJobSetupError(RuntimeError):
    """Raised when local dependencies cannot be created for this job."""


class InsightJobExecutionError(RuntimeError):
    """Raised when the historical analysis or its snapshot cannot complete."""


class InsightJobCleanupError(RuntimeError):
    """Raised only when cleanup is the sole failure of an otherwise valid run."""


class HistoricalInsightsAgent(Protocol):
    """Small execution boundary that keeps the local command unit-testable."""

    def prepare_historical_analysis(self) -> Any:
        ...

    def run_historical_analysis(
        self,
        request: FeedbackInsightsRequest,
        *,
        source: InsightRunSource,
    ) -> InsightsAnalysisRunResult:
        ...

    def cleanup(self) -> None:
        ...


FeedbackRepositoryFactory = Callable[..., FeedbackRepository]
SnapshotRepositoryFactory = Callable[..., InsightsSnapshotRepository]
AgentFactory = Callable[..., HistoricalInsightsAgent]


@dataclass(frozen=True)
class InsightJobSummary:
    """Scheduler-safe result containing scope and aggregate counts only."""

    snapshot_id: str
    source: InsightRunSource
    audience_profile: UserProfile
    start_date: datetime
    end_date: datetime
    comparison_start_date: datetime | None
    comparison_end_date: datetime | None
    software_id: str | None
    functionality_id: str | None
    total_feedbacks: int
    clustered_feedbacks: int
    cluster_count: int

    @staticmethod
    def _utc_iso8601(value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    def model_dump(self) -> dict[str, object]:
        """Return intentionally non-sensitive JSON-ready scheduler output."""

        return {
            "status": "completed",
            "snapshot_id": self.snapshot_id,
            "source": self.source.value,
            "audience_profile": self.audience_profile.value,
            "scope": {
                "start_date": self._utc_iso8601(self.start_date),
                "end_date": self._utc_iso8601(self.end_date),
                "comparison_start_date": self._utc_iso8601(
                    self.comparison_start_date
                ),
                "comparison_end_date": self._utc_iso8601(self.comparison_end_date),
                "software_id": self.software_id,
                "functionality_id": self.functionality_id,
            },
            "metrics": {
                "total_feedbacks": self.total_feedbacks,
                "clustered_feedbacks": self.clustered_feedbacks,
                "cluster_count": self.cluster_count,
            },
        }


def _create_feedback_repository(*, verbose: bool) -> DataverseFeedbackRepository:
    return DataverseFeedbackRepository.from_environment(verbose=verbose)


def _create_snapshot_repository(
    *,
    verbose: bool,
) -> DataverseInsightAnalysisRepository:
    return DataverseInsightAnalysisRepository.from_environment(verbose=verbose)


def _create_agent(
    *,
    feedback_repository: FeedbackRepository,
    feedback_reader: FeedbackReader,
    insights_snapshot_repository: InsightsSnapshotRepository,
    verbose: bool,
) -> FeedbackAnalyzerAgent:
    return FeedbackAnalyzerAgent(
        feedback_repository=feedback_repository,
        feedback_reader=feedback_reader,
        insights_snapshot_repository=insights_snapshot_repository,
        verbose=verbose,
    )


def parse_iso8601_timestamp(value: str) -> datetime:
    """Parse an ISO 8601 timestamp and reject ambiguous, timezone-free input."""

    normalized = value.strip()
    if normalized.endswith(("Z", "z")):
        normalized = f"{normalized[:-1]}+00:00"

    try:
        timestamp = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "must be an ISO 8601 timestamp with a timezone, for example "
            "2026-10-01T00:00:00Z"
        ) from error

    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise argparse.ArgumentTypeError(
            "must include an explicit timezone, for example Z or +00:00"
        )
    return timestamp.astimezone(timezone.utc)


def build_parser() -> argparse.ArgumentParser:
    """Build the strict CLI contract used by local scheduled tasks."""

    parser = argparse.ArgumentParser(
        description=(
            "Run one direct, persisted historical-feedback analysis for the POC."
        )
    )
    parser.add_argument(
        "--start-date",
        required=True,
        type=parse_iso8601_timestamp,
        help="Current-period start, ISO 8601 with timezone (inclusive).",
    )
    parser.add_argument(
        "--end-date",
        required=True,
        type=parse_iso8601_timestamp,
        help="Current-period end, ISO 8601 with timezone (exclusive).",
    )
    parser.add_argument(
        "--audience-profile",
        required=True,
        choices=[profile.value for profile in UserProfile],
        help="Audience used to select and present the report evidence.",
    )
    parser.add_argument(
        "--software-id",
        help="Optional canonical software identifier to narrow the analysis.",
    )
    parser.add_argument(
        "--functionality-id",
        help="Optional canonical functionality identifier to narrow the analysis.",
    )
    parser.add_argument(
        "--comparison-start-date",
        type=parse_iso8601_timestamp,
        help="Optional comparison-period start; must be paired with its end.",
    )
    parser.add_argument(
        "--comparison-end-date",
        type=parse_iso8601_timestamp,
        help="Optional comparison-period end; must be paired with its start.",
    )
    parser.add_argument(
        "--source",
        default=InsightRunSource.MANUAL.value,
        choices=[InsightRunSource.MANUAL.value, InsightRunSource.SCHEDULED.value],
        help="Origin recorded with the snapshot (default: manual).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print non-sensitive execution progress in addition to the summary.",
    )
    return parser


def request_from_args(
    args: argparse.Namespace,
) -> FeedbackInsightsRequest:
    """Convert parsed CLI input into the existing validated request model."""

    has_comparison_start = args.comparison_start_date is not None
    has_comparison_end = args.comparison_end_date is not None
    if has_comparison_start != has_comparison_end:
        raise ValueError(
            "--comparison-start-date and --comparison-end-date must be provided together."
        )

    try:
        return FeedbackInsightsRequest(
            start_date=args.start_date,
            end_date=args.end_date,
            software_id=args.software_id,
            functionality_id=args.functionality_id,
            audience_profile=args.audience_profile,
            comparison_start_date=args.comparison_start_date,
            comparison_end_date=args.comparison_end_date,
        )
    except ValidationError as error:
        # Dates and filter values are user-provided.  Do not echo them in an
        # automated job's logs; the parser already identifies the bad option.
        raise ValueError(
            "The requested reporting periods are invalid, overlapping, or out of order."
        ) from error


def _summary_from_result(
    *,
    request: FeedbackInsightsRequest,
    source: InsightRunSource,
    result: InsightsAnalysisRunResult,
) -> InsightJobSummary:
    snapshot_id = result.insight_snapshot_id
    if not snapshot_id:
        raise InsightJobExecutionError(
            "The historical analysis did not return a persisted snapshot identifier."
        )

    return InsightJobSummary(
        snapshot_id=snapshot_id,
        source=source,
        audience_profile=request.audience_profile,
        start_date=request.start_date,
        end_date=request.end_date,
        comparison_start_date=request.comparison_start_date,
        comparison_end_date=request.comparison_end_date,
        software_id=request.software_id,
        functionality_id=request.functionality_id,
        total_feedbacks=result.insights.total_feedbacks,
        clustered_feedbacks=result.insights.clustered_feedbacks,
        cluster_count=len(result.insights.clusters),
    )


def run_historical_insight_job(
    request: FeedbackInsightsRequest,
    *,
    source: InsightRunSource,
    verbose: bool = False,
    feedback_repository_factory: FeedbackRepositoryFactory = _create_feedback_repository,
    snapshot_repository_factory: SnapshotRepositoryFactory = _create_snapshot_repository,
    agent_factory: AgentFactory = _create_agent,
) -> InsightJobSummary:
    """Create dependencies, run direct analysis once, and always clean up.

    The factories make this orchestration independently testable: unit tests
    never need Azure credentials, Dataverse, or a Foundry model deployment.
    """

    if source not in {InsightRunSource.MANUAL, InsightRunSource.SCHEDULED}:
        raise ValueError("The local insight job only supports manual or scheduled runs.")

    agent: HistoricalInsightsAgent | None = None
    result: InsightsAnalysisRunResult | None = None
    failure: Exception | None = None

    try:
        try:
            feedback_repository = feedback_repository_factory(verbose=verbose)
            snapshot_repository = snapshot_repository_factory(verbose=verbose)
            # DataverseFeedbackRepository implements both persistence and the
            # read-only FeedbackReader boundary required by the insights service.
            feedback_reader = cast(FeedbackReader, feedback_repository)
            agent = agent_factory(
                feedback_repository=feedback_repository,
                feedback_reader=feedback_reader,
                insights_snapshot_repository=snapshot_repository,
                verbose=verbose,
            )
            agent.prepare_historical_analysis()
        except Exception as error:
            failure = InsightJobSetupError(
                "The local historical-analysis dependencies could not be initialized."
            )
            failure.__cause__ = error

        if failure is None:
            try:
                result = agent.run_historical_analysis(request, source=source)  # type: ignore[union-attr]
            except Exception as error:
                failure = InsightJobExecutionError(
                    "The historical analysis or snapshot persistence did not complete."
                )
                failure.__cause__ = error
    finally:
        if agent is not None:
            try:
                agent.cleanup()
            except Exception as cleanup_error:
                if failure is None:
                    failure = InsightJobCleanupError(
                        "The historical analysis completed but local agent cleanup failed."
                    )
                    failure.__cause__ = cleanup_error
                else:
                    try:
                        failure.add_note(
                            "Agent cleanup also failed after the primary error."
                        )
                    except AttributeError:
                        pass

    if failure is not None:
        raise failure
    if result is None:
        raise InsightJobExecutionError("The historical analysis returned no result.")
    return _summary_from_result(request=request, source=source, result=result)


def _write_failure(
    *,
    error: Exception,
    event: str,
    stderr: TextIO,
) -> None:
    diagnostic_error = (
        error.__cause__ if isinstance(error.__cause__, Exception) else error
    )
    if not _error_was_logged(diagnostic_error):
        _log_error("insight_job", event, diagnostic_error)
    print(
        "Historical insights job did not complete. Review the [ERROR] diagnostic above.",
        file=stderr,
        flush=True,
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    feedback_repository_factory: FeedbackRepositoryFactory = _create_feedback_repository,
    snapshot_repository_factory: SnapshotRepositoryFactory = _create_snapshot_repository,
    agent_factory: AgentFactory = _create_agent,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Execute the POC command and return a scheduler-friendly exit code."""

    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        request = request_from_args(args)
    except ValueError as error:
        print(f"Invalid job request: {error}", file=stderr, flush=True)
        return EXIT_INVALID_ARGUMENTS

    try:
        summary = run_historical_insight_job(
            request,
            source=InsightRunSource(args.source),
            verbose=args.verbose,
            feedback_repository_factory=feedback_repository_factory,
            snapshot_repository_factory=snapshot_repository_factory,
            agent_factory=agent_factory,
        )
    except KeyboardInterrupt:
        print("Historical insights job interrupted.", file=stderr, flush=True)
        return EXIT_INTERRUPTED
    except InsightJobSetupError as error:
        _write_failure(error=error, event="historical_analysis_setup_failed", stderr=stderr)
        return EXIT_SETUP_FAILED
    except InsightJobCleanupError as error:
        _write_failure(error=error, event="historical_analysis_cleanup_failed", stderr=stderr)
        return EXIT_CLEANUP_FAILED
    except Exception as error:
        _write_failure(error=error, event="historical_analysis_failed", stderr=stderr)
        return EXIT_ANALYSIS_FAILED

    print(
        json.dumps(summary.model_dump(), ensure_ascii=False, sort_keys=True),
        file=stdout,
        flush=True,
    )
    return EXIT_SUCCESS


if __name__ == "__main__":
    raise SystemExit(main())
