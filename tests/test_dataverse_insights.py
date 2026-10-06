import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app import dataverse as dataverse_module
from app.models import (
    FeedbackInsightsFilters,
    FeedbackType,
    ProblemCategory,
    SentimentLabel,
)


ANNOTATION = "@OData.Community.Display.V1.FormattedValue"


class FakeDataverseClient:
    def __init__(self, rows):
        self.records = SimpleNamespace(list=Mock(return_value=rows))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None


def filters(**overrides):
    values = {
        "start_date": datetime(2026, 10, 1, tzinfo=timezone.utc),
        "end_date": datetime(2026, 11, 1, tzinfo=timezone.utc),
        "software_id": "dealym_crm",
        "functionality_id": "payments",
    }
    values.update(overrides)
    return FeedbackInsightsFilters(**values)


class DataverseInsightsReaderTests(unittest.TestCase):
    def _repository(self):
        return dataverse_module.DataverseFeedbackRepository(
            base_url="https://example.crm.dynamics.com",
            tenant_id="tenant-id",
            client_id="client-id",
            client_secret="client-secret",
            table_logical_name="agil_feedback",
            verbose=False,
        )

    def test_list_for_insights_builds_a_narrow_server_query_and_normalizes_choices(self):
        rows = [
            {
                "agil_feedbackreference": "feedback-1",
                "agil_rawcomment": "Raw text stays inside the reader.",
                "agil_receivedat": "2026-10-03T09:15:00Z",
                "agil_softwareid": "dealym_crm",
                "agil_feedbacksummary": "Le paiement est refusé après 3D Secure.",
                "agil_sentiment": "negative",
                "agil_feedbacktype": 100000000,
                f"agil_feedbacktype{ANNOTATION}": "Signalement de problème",
                "agil_problemcategory": 100000006,
                f"agil_problemcategory{ANNOTATION}": "Paiement / facturation",
                "agil_primaryfunctionality": "payments",
                "agil_primaryfunctionalityname": "Paiement",
            }
        ]
        client = FakeDataverseClient(rows)

        with (
            patch.object(dataverse_module, "ClientSecretCredential", return_value=object()),
            patch.object(dataverse_module, "DataverseClient", return_value=client),
        ):
            records = self._repository().list_for_insights(filters())

        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record.feedback_id, "feedback-1")
        self.assertEqual(record.sentiment, SentimentLabel.NEGATIVE)
        self.assertEqual(record.feedback_type, FeedbackType.ISSUE_REPORT)
        self.assertEqual(record.problem_category, ProblemCategory.BILLING_PAYMENT)
        self.assertEqual(record.primary_functionality, "payments")
        self.assertEqual(record.primary_functionality_name, "Paiement")

        kwargs = client.records.list.call_args.kwargs
        self.assertEqual(kwargs["select"].count("agil_feedbacksummary"), 1)
        self.assertIn("agil_receivedat ge 2026-10-01T00:00:00Z", kwargs["filter"])
        self.assertIn("agil_receivedat lt 2026-11-01T00:00:00Z", kwargs["filter"])
        self.assertIn("agil_softwareid eq 'dealym_crm'", kwargs["filter"])
        self.assertIn("agil_primaryfunctionality eq 'payments'", kwargs["filter"])
        self.assertEqual(
            kwargs["include_annotations"],
            "OData.Community.Display.V1.FormattedValue",
        )

    def test_choice_filters_are_applied_after_the_formatted_values_are_decoded(self):
        rows = [
            {
                "agil_feedbackreference": "negative-incident",
                "agil_receivedat": "2026-10-03T09:15:00Z",
                "agil_softwareid": "dealym_crm",
                "agil_feedbacksummary": "Le paiement est refusé.",
                "agil_sentiment": "negative",
                "agil_feedbacktype": 1,
                f"agil_feedbacktype{ANNOTATION}": "Signalement de problème",
                "agil_primaryfunctionality": "payments",
            },
            {
                "agil_feedbackreference": "positive-praise",
                "agil_receivedat": "2026-10-04T09:15:00Z",
                "agil_softwareid": "dealym_crm",
                "agil_feedbacksummary": "Le paiement est simple.",
                "agil_sentiment": "positive",
                "agil_feedbacktype": 2,
                f"agil_feedbacktype{ANNOTATION}": "Éloge / retour positif",
                "agil_primaryfunctionality": "payments",
            },
        ]
        client = FakeDataverseClient(rows)

        with (
            patch.object(dataverse_module, "ClientSecretCredential", return_value=object()),
            patch.object(dataverse_module, "DataverseClient", return_value=client),
        ):
            records = self._repository().list_for_insights(
                filters(
                    sentiment=SentimentLabel.NEGATIVE,
                    feedback_type=FeedbackType.ISSUE_REPORT,
                )
            )

        self.assertEqual([record.feedback_id for record in records], ["negative-incident"])
        query_filter = client.records.list.call_args.kwargs["filter"]
        self.assertNotIn("agil_feedbacktype eq", query_filter)
        self.assertNotIn("agil_sentiment eq", query_filter)

    def test_malformed_historical_rows_are_skipped_without_failing_valid_rows(self):
        rows = [
            {
                "agil_feedbackreference": "valid",
                "agil_receivedat": "2026-10-03T09:15:00Z",
                "agil_softwareid": "dealym_crm",
                "agil_feedbacksummary": "Un résumé valide.",
            },
            {
                "agil_feedbackreference": "missing-date",
                "agil_softwareid": "dealym_crm",
                "agil_feedbacksummary": "Cette ligne ne peut pas être utilisée.",
            },
        ]
        client = FakeDataverseClient(rows)

        with (
            patch.object(dataverse_module, "ClientSecretCredential", return_value=object()),
            patch.object(dataverse_module, "DataverseClient", return_value=client),
        ):
            records = self._repository().list_for_insights(filters())

        self.assertEqual([record.feedback_id for record in records], ["valid"])


if __name__ == "__main__":
    unittest.main()
