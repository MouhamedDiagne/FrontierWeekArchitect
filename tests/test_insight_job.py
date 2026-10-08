import io
import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from app.insight_job import (
    EXIT_ANALYSIS_FAILED,
    EXIT_INVALID_ARGUMENTS,
    EXIT_SETUP_FAILED,
    EXIT_SUCCESS,
    build_parser,
    main,
)
from app.models import FeedbackInsightsRequest, InsightRunSource


class FakeHistoricalInsightsAgent:
    def __init__(self, *, result=None, run_error=None, cleanup_error=None):
        self.result = result
        self.run_error = run_error
        self.cleanup_error = cleanup_error
        self.prepared = False
        self.cleaned_up = False
        self.requests = []

    def prepare_historical_analysis(self):
        self.prepared = True

    def run_historical_analysis(self, request, *, source):
        self.requests.append((request, source))
        if self.run_error is not None:
            raise self.run_error
        return self.result

    def cleanup(self):
        self.cleaned_up = True
        if self.cleanup_error is not None:
            raise self.cleanup_error


def result_with_counts(*, snapshot_id="snapshot-42"):
    return SimpleNamespace(
        insight_snapshot_id=snapshot_id,
        insights=SimpleNamespace(
            total_feedbacks=12,
            clustered_feedbacks=9,
            clusters=[SimpleNamespace(), SimpleNamespace()],
        ),
    )


def command_args(*extra):
    return [
        "--start-date",
        "2026-10-01T00:00:00Z",
        "--end-date",
        "2026-11-01T00:00:00Z",
        "--audience-profile",
        "management",
        *extra,
    ]


class InsightJobTests(unittest.TestCase):
    def test_direct_job_persists_a_snapshot_and_prints_only_aggregate_summary(self):
        agent = FakeHistoricalInsightsAgent(result=result_with_counts())
        supplied = {}
        stdout = io.StringIO()
        stderr = io.StringIO()

        def agent_factory(**kwargs):
            supplied.update(kwargs)
            return agent

        exit_code = main(
            command_args(
                "--software-id",
                "targetym_ai",
                "--functionality-id",
                "hr_reporting",
                "--source",
                "scheduled",
            ),
            feedback_repository_factory=lambda **kwargs: object(),
            snapshot_repository_factory=lambda **kwargs: object(),
            agent_factory=agent_factory,
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(exit_code, EXIT_SUCCESS)
        self.assertTrue(agent.prepared)
        self.assertTrue(agent.cleaned_up)
        self.assertIs(supplied["feedback_reader"], supplied["feedback_repository"])
        request, source = agent.requests[0]
        self.assertEqual(source, InsightRunSource.SCHEDULED)
        self.assertEqual(request.software_id, "targetym_ai")
        self.assertEqual(request.functionality_id, "hr_reporting")

        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["snapshot_id"], "snapshot-42")
        self.assertEqual(payload["source"], "scheduled")
        self.assertEqual(payload["metrics"], {
            "total_feedbacks": 12,
            "clustered_feedbacks": 9,
            "cluster_count": 2,
        })
        self.assertNotIn("raw_comment", stdout.getvalue())
        self.assertNotIn("feedback_summary", stdout.getvalue())
        self.assertEqual(stderr.getvalue(), "")

    def test_analysis_failure_returns_non_zero_and_still_cleans_up(self):
        agent = FakeHistoricalInsightsAgent(run_error=RuntimeError("provider unavailable"))
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = main(
            command_args(),
            feedback_repository_factory=lambda **kwargs: object(),
            snapshot_repository_factory=lambda **kwargs: object(),
            agent_factory=lambda **kwargs: agent,
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(exit_code, EXIT_ANALYSIS_FAILED)
        self.assertTrue(agent.prepared)
        self.assertTrue(agent.cleaned_up)
        self.assertEqual(agent.requests[0][1], InsightRunSource.MANUAL)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Historical insights job did not complete.", stderr.getvalue())
        self.assertNotIn("provider unavailable", stderr.getvalue())

    def test_repository_setup_failure_returns_setup_exit_code(self):
        stderr = io.StringIO()

        exit_code = main(
            command_args(),
            feedback_repository_factory=lambda **kwargs: (_ for _ in ()).throw(
                RuntimeError("Dataverse is not configured")
            ),
            snapshot_repository_factory=lambda **kwargs: object(),
            agent_factory=lambda **kwargs: self.fail("agent must not be created"),
            stdout=io.StringIO(),
            stderr=stderr,
        )

        self.assertEqual(exit_code, EXIT_SETUP_FAILED)
        self.assertIn("Historical insights job did not complete.", stderr.getvalue())
        self.assertNotIn("Dataverse is not configured", stderr.getvalue())

    def test_parser_rejects_naive_timestamps(self):
        parser = build_parser()

        with self.assertRaises(SystemExit) as raised:
            parser.parse_args(
                [
                    "--start-date",
                    "2026-10-01T00:00:00",
                    "--end-date",
                    "2026-11-01T00:00:00Z",
                    "--audience-profile",
                    "management",
                ]
            )

        self.assertEqual(raised.exception.code, EXIT_INVALID_ARGUMENTS)

    def test_comparison_dates_must_be_provided_as_a_pair(self):
        stderr = io.StringIO()

        exit_code = main(
            command_args(
                "--comparison-start-date",
                "2026-09-01T00:00:00Z",
            ),
            feedback_repository_factory=lambda **kwargs: self.fail("not used"),
            snapshot_repository_factory=lambda **kwargs: self.fail("not used"),
            agent_factory=lambda **kwargs: self.fail("not used"),
            stdout=io.StringIO(),
            stderr=stderr,
        )

        self.assertEqual(exit_code, EXIT_INVALID_ARGUMENTS)
        self.assertIn("must be provided together", stderr.getvalue())

    def test_request_model_keeps_utc_scope(self):
        request = FeedbackInsightsRequest(
            start_date=datetime(2026, 10, 1, tzinfo=timezone.utc),
            end_date=datetime(2026, 11, 1, tzinfo=timezone.utc),
            audience_profile="it",
        )

        self.assertEqual(request.audience_profile.value, "it")


if __name__ == "__main__":
    unittest.main()
