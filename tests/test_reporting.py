import unittest
from datetime import datetime, timezone

from app.models import (
    ClusterPriority,
    FeedbackInsightsDataQuality,
    FeedbackInsightsRequest,
    FeedbackInsightsResult,
    FeedbackType,
    ProblemCategory,
    TemporaryFeedbackCluster,
    UserProfile,
)
from app.reporting import ProfiledInsightsReportBuilder


NOW = datetime(2026, 10, 6, tzinfo=timezone.utc)


def cluster(
    cluster_id: str,
    *,
    score: float,
    feedback_type: FeedbackType,
    category: ProblemCategory | None = None,
    status: str = "clustered",
) -> TemporaryFeedbackCluster:
    return TemporaryFeedbackCluster(
        temporary_id=cluster_id,
        title=cluster_id,
        description="Synthetic cluster for reporting tests.",
        status=status,
        software_id="targetym_ai",
        feedback_type=feedback_type,
        dominant_problem_category=category,
        feedback_ids=[cluster_id],
        member_count=1,
        unique_client_count=None,
        functionality_breakdown={},
        problem_category_breakdown={},
        sentiment_distribution={"negative": 1},
        first_occurrence=NOW,
        last_occurrence=NOW,
        representative_examples=[],
        average_similarity=None,
        confidence=0.8,
        priority=ClusterPriority(
            score=score,
            volume=1.0,
            severity=1.0,
            trend=1.0,
            segment_weight=1.0,
        ),
    )


def insights(clusters):
    return FeedbackInsightsResult(
        request=FeedbackInsightsRequest(
            start_date=datetime(2026, 10, 1, tzinfo=timezone.utc),
            end_date=datetime(2026, 11, 1, tzinfo=timezone.utc),
            software_id="targetym_ai",
            audience_profile=UserProfile.IT,
        ),
        total_feedbacks=len(clusters),
        clustered_feedbacks=sum(item.status == "clustered" for item in clusters),
        clusters=clusters,
        data_quality=FeedbackInsightsDataQuality(
            records_with_summary=len(clusters),
            records_using_raw_fallback=0,
            records_without_usable_representation=0,
        ),
        limitations=["Le nombre de clients uniques n'est pas disponible."],
    )


class ProfiledInsightsReportBuilderTests(unittest.TestCase):
    def setUp(self):
        self.technical = cluster(
            "technical",
            score=8.0,
            feedback_type=FeedbackType.ISSUE_REPORT,
            category=ProblemCategory.PERFORMANCE_SLOWDOWN,
        )
        self.praise = cluster(
            "praise",
            score=5.0,
            feedback_type=FeedbackType.POSITIVE_FEEDBACK,
        )
        self.review = cluster(
            "review",
            score=10.0,
            feedback_type=FeedbackType.ISSUE_REPORT,
            category=ProblemCategory.USABILITY_UX,
            status="needs_review",
        )

    def test_it_report_selects_technical_evidence_and_keeps_positive_separate(self):
        report = ProfiledInsightsReportBuilder.build(
            insights([self.technical, self.praise, self.review]),
            UserProfile.IT,
        )

        self.assertEqual(report.priority_signal_ids, ["technical"])
        self.assertEqual(report.positive_signal_ids, ["praise"])
        self.assertEqual(report.watch_list_ids, ["review"])
        self.assertEqual(report.suggested_follow_up_types, ["investigate", "reproduce", "check_logs"])
        self.assertIn("2026-10-01", report.scope.period)

    def test_management_keeps_all_confirmed_clusters_ranked_by_existing_priority(self):
        report = ProfiledInsightsReportBuilder.build(
            insights([self.praise, self.technical, self.review]),
            UserProfile.MANAGEMENT,
        )

        self.assertEqual(report.priority_signal_ids, ["technical", "praise"])
        self.assertEqual(report.positive_signal_ids, [])
        self.assertEqual(report.watch_list_ids, ["review"])
        self.assertEqual(report.suggested_follow_up_types, ["prioritize", "assign_owner", "review_next_cycle"])


if __name__ == "__main__":
    unittest.main()
