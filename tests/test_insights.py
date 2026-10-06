import unittest
from datetime import datetime, timezone

from app.clustering import ClusteringConfig
from app.insights import ClusterLabel, FeedbackInsightsService
from app.models import (
    FeedbackInsightsRequest,
    FeedbackRecordForInsights,
    FeedbackType,
    ProblemCategory,
    SentimentLabel,
)


class FakeReader:
    def __init__(self, *, current, previous):
        self.current = current
        self.previous = previous
        self.filters = []

    def list_for_insights(self, filters):
        self.filters.append(filters)
        return self.current if filters.start_date.month == 10 else self.previous


class MappingEmbeddingProvider:
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
                raise AssertionError(f"No vector configured for {text!r}")
        return vectors


class FakeLabelProvider:
    def __init__(self):
        self.cluster_ids = []

    def label_cluster(self, cluster):
        self.cluster_ids.append(cluster.temporary_id)
        return ClusterLabel(
            title="Échecs de paiement après vérification 3D Secure",
            description="Des paiements sont refusés après la vérification 3D Secure.",
        )


def record(feedback_id, summary, timestamp):
    return FeedbackRecordForInsights(
        feedback_id=feedback_id,
        received_at=timestamp,
        software_id="dealym_crm",
        feedback_summary=summary,
        raw_comment=None,
        sentiment=SentimentLabel.NEGATIVE,
        feedback_type=FeedbackType.ISSUE_REPORT,
        problem_category=ProblemCategory.BILLING_PAYMENT,
        primary_functionality="payments",
    )


def request(*, with_comparison=True):
    values = {
        "start_date": datetime(2026, 10, 1, tzinfo=timezone.utc),
        "end_date": datetime(2026, 11, 1, tzinfo=timezone.utc),
        "software_id": "dealym_crm",
        "audience_profile": "it",
    }
    if with_comparison:
        values.update(
            {
                "comparison_start_date": datetime(2026, 9, 1, tzinfo=timezone.utc),
                "comparison_end_date": datetime(2026, 10, 1, tzinfo=timezone.utc),
            }
        )
    return FeedbackInsightsRequest(**values)


class FeedbackInsightsServiceTests(unittest.TestCase):
    def _service(self, reader, embedding_provider, label_provider=None):
        return FeedbackInsightsService(
            feedback_reader=reader,
            embedding_provider=embedding_provider,
            clustering_config=ClusteringConfig(
                max_cosine_distance=0.08,
                max_feedbacks=20,
            ),
            cluster_label_provider=label_provider,
            verbose=False,
        )

    def test_clusters_both_periods_before_calculating_growth_and_priority(self):
        current = [
            record(
                "current-1",
                "Le paiement est refusé après la vérification 3D Secure.",
                datetime(2026, 10, 3, tzinfo=timezone.utc),
            ),
            record(
                "current-2",
                "La vérification 3D Secure bloque le paiement.",
                datetime(2026, 10, 4, tzinfo=timezone.utc),
            ),
        ]
        previous = [
            record(
                "previous-1",
                "Le paiement échoue après 3D Secure.",
                datetime(2026, 9, 21, tzinfo=timezone.utc),
            )
        ]
        reader = FakeReader(current=current, previous=previous)
        embeddings = MappingEmbeddingProvider(
            {
                "paiement est refusé": [1.0, 0.0],
                "vérification 3D Secure bloque": [0.99, 0.01],
                "paiement échoue": [0.98, -0.01],
            }
        )
        labels = FakeLabelProvider()

        result = self._service(reader, embeddings, labels).analyze(request())

        self.assertEqual(len(reader.filters), 2)
        self.assertEqual(result.total_feedbacks, 3)
        self.assertEqual(result.clustered_feedbacks, 3)
        self.assertEqual(len(result.clusters), 1)
        cluster = result.clusters[0]
        self.assertEqual(
            cluster.title,
            "Échecs de paiement après vérification 3D Secure",
        )
        self.assertEqual(cluster.period_metrics.current_count, 2)
        self.assertEqual(cluster.period_metrics.previous_count, 1)
        self.assertEqual(cluster.period_metrics.trend, "up")
        self.assertEqual(cluster.period_metrics.relative_change, 1.0)
        self.assertEqual(cluster.priority.volume, 2.0)
        self.assertEqual(cluster.priority.severity, 2.0)
        self.assertEqual(cluster.priority.trend, 2.0)
        self.assertEqual(cluster.priority.score, 8.0)
        self.assertEqual(labels.cluster_ids, [cluster.temporary_id])

    def test_empty_period_does_not_request_embeddings_and_surfaces_a_limit(self):
        reader = FakeReader(current=[], previous=[])
        embeddings = MappingEmbeddingProvider({})

        result = self._service(reader, embeddings).analyze(request(with_comparison=False))

        self.assertEqual(result.clusters, [])
        self.assertEqual(result.total_feedbacks, 0)
        self.assertEqual(embeddings.calls, [])
        self.assertTrue(any("Aucun feedback" in item for item in result.limitations))

    def test_request_rejects_overlapping_comparison_dates(self):
        with self.assertRaisesRegex(ValueError, "must not overlap"):
            FeedbackInsightsRequest(
                start_date=datetime(2026, 10, 1, tzinfo=timezone.utc),
                end_date=datetime(2026, 11, 1, tzinfo=timezone.utc),
                audience_profile="it",
                comparison_start_date=datetime(2026, 10, 15, tzinfo=timezone.utc),
                comparison_end_date=datetime(2026, 11, 15, tzinfo=timezone.utc),
            )


if __name__ == "__main__":
    unittest.main()
