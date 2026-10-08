import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app import dataverse as dataverse_module
from app.models import (
    FeedbackInsightsDataQuality,
    FeedbackInsightsRequest,
    FeedbackInsightsResult,
    FeedbackInsightsSnapshot,
    InsightRunSource,
    UserProfile,
)
from app.reporting import ProfiledInsightsReportBuilder


class FakeDataverseClient:
    def __init__(self, *, record_id="snapshot-record-1", rows=None):
        self.records = SimpleNamespace(
            create=Mock(return_value=record_id),
            list=Mock(return_value=rows or []),
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None


def make_snapshot() -> FeedbackInsightsSnapshot:
    insights = FeedbackInsightsResult(
        request=FeedbackInsightsRequest(
            start_date=datetime(2026, 10, 1, tzinfo=timezone.utc),
            end_date=datetime(2026, 11, 1, tzinfo=timezone.utc),
            software_id="targetym_ai",
            audience_profile=UserProfile.MANAGEMENT,
        ),
        total_feedbacks=2,
        clustered_feedbacks=0,
        clusters=[],
        data_quality=FeedbackInsightsDataQuality(
            records_with_summary=2,
            records_using_raw_fallback=0,
            records_without_usable_representation=0,
        ),
        limitations=["No confirmed cluster is available."],
    )
    return FeedbackInsightsSnapshot(
        generated_at=datetime(2026, 10, 7, 9, 30, tzinfo=timezone.utc),
        source=InsightRunSource.MANUAL,
        insights=insights,
        audience_report=ProfiledInsightsReportBuilder.build(
            insights,
            UserProfile.MANAGEMENT,
        ),
    )


class DataverseInsightSnapshotTests(unittest.TestCase):
    def _repository(self):
        return dataverse_module.DataverseInsightAnalysisRepository(
            base_url="https://example.crm.dynamics.com",
            tenant_id="tenant-id",
            client_id="client-id",
            client_secret="client-secret",
            table_logical_name="agil_insightanalysis",
            verbose=False,
        )

    def test_save_writes_scope_metrics_and_json_without_raw_comments(self):
        client = FakeDataverseClient()
        snapshot = make_snapshot()

        with (
            patch.object(dataverse_module, "ClientSecretCredential", return_value=object()),
            patch.object(dataverse_module, "DataverseClient", return_value=client),
        ):
            record_id = self._repository().save_snapshot(snapshot=snapshot)

        self.assertEqual(record_id, "snapshot-record-1")
        table_name, payload = client.records.create.call_args.args
        self.assertEqual(table_name, "agil_insightanalysis")
        self.assertIn("agil_agilname", payload)
        self.assertEqual(payload["agil_source"], "manual")
        self.assertEqual(payload["agil_totalfeedbacks"], 2)
        self.assertEqual(payload["agil_clusteredfeedbacks"], 0)
        self.assertEqual(payload["agil_clustercount"], 0)
        self.assertEqual(payload["agil_audienceprofile"], "management")
        self.assertEqual(payload["agil_periodstart"], "2026-10-01T00:00:00Z")
        self.assertNotIn("raw_comment", payload["agil_insightsjson"])
        self.assertEqual(
            json.loads(payload["agil_audiencereportsjson"])["profile"],
            "management",
        )

    def test_latest_snapshot_round_trips_the_stored_json(self):
        snapshot = make_snapshot()
        row = {
            "agil_generatedat": "2026-10-07T09:30:00Z",
            "agil_source": "manual",
            "agil_insightsjson": snapshot.insights.model_dump_json(),
            "agil_audiencereportsjson": snapshot.audience_report.model_dump_json(),
        }
        client = FakeDataverseClient(rows=[row])

        with (
            patch.object(dataverse_module, "ClientSecretCredential", return_value=object()),
            patch.object(dataverse_module, "DataverseClient", return_value=client),
        ):
            stored = self._repository().latest_snapshot()

        self.assertEqual(stored, snapshot)
        kwargs = client.records.list.call_args.kwargs
        self.assertEqual(kwargs["top"], 1)
        self.assertEqual(kwargs["orderby"], ["agil_generatedat desc"])


if __name__ == "__main__":
    unittest.main()
