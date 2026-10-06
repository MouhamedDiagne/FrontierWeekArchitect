import unittest
from datetime import datetime, timezone

from app.clustering import (
    ClusteringConfig,
    ClusteringConfigurationError,
    EmbeddingResultError,
    build_feedback_representation,
    cluster_feedback_records,
)
from app.models import (
    FeedbackRecordForInsights,
    FeedbackType,
    ProblemCategory,
    SentimentLabel,
)


class MappingEmbeddingProvider:
    """A deterministic provider whose mapping keys are text fragments."""

    def __init__(self, vectors_by_fragment):
        self.vectors_by_fragment = vectors_by_fragment
        self.calls = []

    def embed(self, texts):
        self.calls.append(texts)
        vectors = []
        for text in texts:
            for fragment, vector in self.vectors_by_fragment.items():
                if fragment in text:
                    vectors.append(vector)
                    break
            else:
                raise AssertionError(f"No vector configured for: {text!r}")
        return vectors


def record(
    feedback_id,
    summary,
    *,
    raw_comment=None,
    software_id="dealym_crm",
    sentiment=SentimentLabel.NEGATIVE,
    feedback_type=FeedbackType.ISSUE_REPORT,
    problem_category=ProblemCategory.BILLING_PAYMENT,
    functionality="payments",
    day=1,
    client_id=None,
):
    return FeedbackRecordForInsights(
        feedback_id=feedback_id,
        received_at=datetime(2026, 10, day, tzinfo=timezone.utc),
        software_id=software_id,
        feedback_summary=summary,
        raw_comment=raw_comment,
        sentiment=sentiment,
        feedback_type=feedback_type,
        problem_category=problem_category,
        primary_functionality=functionality,
        client_id=client_id,
    )


class ClusteringTests(unittest.TestCase):
    def test_groups_similar_incidents_but_keeps_feature_request_separate(self):
        provider = MappingEmbeddingProvider(
            {
                "3D Secure payment fails": [1.0, 0.0],
                "Payment is rejected after 3D Secure": [0.98, 0.02],
                "3D Secure rejects payment": [0.97, -0.01],
                "Add 3D Secure payment support": [1.0, 0.0],
            }
        )
        feedbacks = [
            record("fb-1", "3D Secure payment fails.", day=1, client_id="client-a"),
            record("fb-2", "Payment is rejected after 3D Secure.", day=2, client_id="client-b"),
            record("fb-3", "3D Secure rejects payment.", day=3, client_id="client-a"),
            record(
                "fb-4",
                "Add 3D Secure payment support.",
                feedback_type=FeedbackType.FEATURE_REQUEST,
                problem_category=None,
                day=4,
            ),
        ]

        clusters = cluster_feedback_records(
            feedbacks,
            embedding_provider=provider,
            config=ClusteringConfig(max_cosine_distance=0.08),
        )

        by_members = {tuple(cluster.feedback_ids): cluster for cluster in clusters}
        issue_cluster = by_members[("fb-1", "fb-2", "fb-3")]
        feature_cluster = by_members[("fb-4",)]
        self.assertEqual(issue_cluster.status, "clustered")
        self.assertEqual(issue_cluster.member_count, 3)
        self.assertEqual(issue_cluster.unique_client_count, 2)
        self.assertEqual(issue_cluster.sentiment_distribution, {"negative": 3})
        self.assertEqual(issue_cluster.priority.volume, 3.0)
        self.assertEqual(issue_cluster.priority.severity, 2.0)
        self.assertEqual(feature_cluster.status, "singleton")

    def test_dissimilar_feedback_in_the_same_partition_stay_singletons(self):
        provider = MappingEmbeddingProvider(
            {
                "Payment receipt is missing": [1.0, 0.0],
                "Invoice is charged twice": [0.0, 1.0],
            }
        )
        clusters = cluster_feedback_records(
            [
                record("fb-1", "Payment receipt is missing."),
                record("fb-2", "Invoice is charged twice."),
            ],
            embedding_provider=provider,
            config=ClusteringConfig(max_cosine_distance=0.10),
        )

        self.assertEqual([cluster.status for cluster in clusters], ["singleton", "singleton"])
        self.assertEqual(
            {cluster.feedback_ids[0] for cluster in clusters}, {"fb-1", "fb-2"}
        )

    def test_raw_comment_is_a_embedding_fallback_but_is_never_exposed_as_an_example(self):
        raw_comment = "The export creates a blank file after the latest release."
        incomplete_record = record(
            "fb-1",
            None,
            raw_comment=raw_comment,
            problem_category=ProblemCategory.DATA_QUALITY_REPORTING,
        )
        provider = MappingEmbeddingProvider({"blank file": [1.0, 0.0]})

        representation = build_feedback_representation(incomplete_record)
        self.assertIn(raw_comment, representation)
        cluster = cluster_feedback_records(
            [incomplete_record],
            embedding_provider=provider,
        )[0]

        self.assertEqual(cluster.status, "needs_review")
        self.assertEqual(cluster.representative_examples, [])
        self.assertNotIn(raw_comment, cluster.model_dump_json())

    def test_missing_usable_text_does_not_call_embedding_provider(self):
        provider = MappingEmbeddingProvider({})
        cluster = cluster_feedback_records(
            [record("fb-1", "N/A", raw_comment=" ")],
            embedding_provider=provider,
        )[0]

        self.assertEqual(provider.calls, [])
        self.assertEqual(cluster.status, "needs_review")
        self.assertEqual(cluster.title, "Feedback à examiner")

    def test_records_without_optional_classifications_are_safe_to_cluster(self):
        provider = MappingEmbeddingProvider({"General feedback": [1.0, 0.0]})
        feedback = FeedbackRecordForInsights(
            feedback_id="fb-optional",
            received_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
            software_id="dealym_crm",
            feedback_summary="General feedback needs review.",
            raw_comment=None,
            sentiment=None,
            feedback_type=None,
            problem_category=None,
            primary_functionality=None,
        )

        cluster = cluster_feedback_records(
            [feedback], embedding_provider=provider
        )[0]

        self.assertEqual(cluster.status, "needs_review")
        self.assertEqual(cluster.feedback_type, None)
        self.assertEqual(cluster.dominant_problem_category, None)
        self.assertEqual(cluster.sentiment_distribution, {"unclassified": 1})

    def test_results_are_reproducible_when_input_order_changes(self):
        provider = MappingEmbeddingProvider(
            {
                "3D Secure payment fails": [1.0, 0.0],
                "Payment is rejected after 3D Secure": [0.99, 0.01],
            }
        )
        first = record("fb-1", "3D Secure payment fails.")
        second = record("fb-2", "Payment is rejected after 3D Secure.")
        config = ClusteringConfig(max_cosine_distance=0.08)

        forward = cluster_feedback_records(
            [first, second], embedding_provider=provider, config=config
        )
        reverse = cluster_feedback_records(
            [second, first], embedding_provider=provider, config=config
        )

        self.assertEqual(
            [item.model_dump(mode="json") for item in forward],
            [item.model_dump(mode="json") for item in reverse],
        )

    def test_rejects_invalid_embedding_response_and_duplicate_ids(self):
        provider = MappingEmbeddingProvider({"Payment receipt is missing": [0.0, 0.0]})
        with self.assertRaises(EmbeddingResultError):
            cluster_feedback_records(
                [record("fb-1", "Payment receipt is missing.")],
                embedding_provider=provider,
            )

        with self.assertRaises(ClusteringConfigurationError):
            cluster_feedback_records(
                [
                    record("duplicate", "Payment receipt is missing."),
                    record("duplicate", "Invoice is charged twice."),
                ],
                embedding_provider=provider,
            )


if __name__ == "__main__":
    unittest.main()
