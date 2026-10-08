import unittest
from collections import Counter
from datetime import datetime, timezone

from pydantic import ValidationError

from app.models import (
    AudienceReport,
    AudienceReportScope,
    ClusterPeriodMetrics,
    ClusterPriority,
    FeedbackInsightsDataQuality,
    FeedbackInsightsMetrics,
    FeedbackInsightsRequest,
    FeedbackInsightsResult,
    FeedbackType,
    InsightPeriodMetrics,
    ProblemCategory,
    TemporaryFeedbackCluster,
    UserProfile,
)
from app.visualizations import (
    FeedbackVisualizationBuilder,
    KpiVisualizationSpec,
    VisualizationBuildError,
    VisualizationKind,
)


NOW = datetime(2026, 10, 6, tzinfo=timezone.utc)


def make_cluster(
    cluster_id: str,
    *,
    score: float,
    title: str | None = None,
    status: str = "clustered",
    feedback_type: FeedbackType = FeedbackType.ISSUE_REPORT,
    category: ProblemCategory | None = ProblemCategory.PERFORMANCE_SLOWDOWN,
    sentiment_distribution: dict[str, int] | None = None,
    with_period_metrics: bool = True,
) -> TemporaryFeedbackCluster:
    return TemporaryFeedbackCluster(
        temporary_id=cluster_id,
        title=title or f"Signal {cluster_id}",
        description="Synthetic cluster for visualisation tests.",
        status=status,
        software_id="targetym_ai",
        feedback_type=feedback_type,
        dominant_problem_category=category,
        feedback_ids=[cluster_id],
        member_count=1,
        unique_client_count=None,
        functionality_breakdown={},
        problem_category_breakdown={},
        sentiment_distribution=sentiment_distribution or {"negative": 1},
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
        period_metrics=(
            ClusterPeriodMetrics(
                current_count=2,
                previous_count=1,
                absolute_change=1,
                relative_change=1.0,
                trend="up",
            )
            if with_period_metrics
            else None
        ),
    )


def make_insights(
    clusters: list[TemporaryFeedbackCluster],
    *,
    with_comparison: bool = True,
    with_aggregate_metrics: bool = True,
) -> FeedbackInsightsResult:
    values = {
        "start_date": datetime(2026, 10, 1, tzinfo=timezone.utc),
        "end_date": datetime(2026, 11, 1, tzinfo=timezone.utc),
        "software_id": "targetym_ai",
        "audience_profile": UserProfile.IT,
    }
    if with_comparison:
        values.update(
            {
                "comparison_start_date": datetime(2026, 9, 1, tzinfo=timezone.utc),
                "comparison_end_date": datetime(2026, 10, 1, tzinfo=timezone.utc),
            }
        )
    return FeedbackInsightsResult(
        request=FeedbackInsightsRequest(**values),
        total_feedbacks=sum(cluster.member_count for cluster in clusters),
        clustered_feedbacks=sum(
            cluster.member_count for cluster in clusters if cluster.status == "clustered"
        ),
        clusters=clusters,
        metrics=(
            FeedbackInsightsMetrics(
                current=InsightPeriodMetrics(
                    feedback_count=sum(cluster.member_count for cluster in clusters),
                    sentiment_distribution=dict(sum(
                        (Counter(cluster.sentiment_distribution) for cluster in clusters), Counter()
                    )),
                    top_functionality_distribution=dict(sum(
                        (Counter(cluster.functionality_breakdown) for cluster in clusters), Counter()
                    )),
                    problem_category_distribution=dict(Counter(
                        cluster.dominant_problem_category.value
                        for cluster in clusters if cluster.dominant_problem_category is not None
                    )),
                )
            ) if with_aggregate_metrics else None
        ),
        data_quality=FeedbackInsightsDataQuality(
            records_with_summary=len(clusters),
            records_using_raw_fallback=0,
            records_without_usable_representation=0,
        ),
        limitations=["Synthetic limitation."],
    )


def make_report(
    *,
    priority_ids: list[str],
    positive_ids: list[str] | None = None,
    profile: UserProfile = UserProfile.IT,
) -> AudienceReport:
    return AudienceReport(
        profile=profile,
        scope=AudienceReportScope(
            period="2026-10-01 to 2026-11-01",
            software_id="targetym_ai",
            functionality_id=None,
            comparison_period="2026-09-01 to 2026-10-01",
        ),
        executive_focus="Priorités techniques.",
        priority_signal_ids=priority_ids,
        positive_signal_ids=positive_ids or [],
        watch_list_ids=[],
        suggested_follow_up_types=["investigate"],
        limitations=["Audience limitation."],
    )


def all_mapping_keys(value):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield key
            yield from all_mapping_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from all_mapping_keys(nested)


class FeedbackVisualizationBuilderTests(unittest.TestCase):
    def test_missing_sentiments_do_not_become_zero_percent(self):
        source = make_insights([make_cluster("unclassified", score=1)], with_comparison=False)
        source.request.audience_profile = UserProfile.MARKETING
        source.metrics.current.sentiment_distribution = {}

        result = FeedbackVisualizationBuilder.build(
            source, make_report(priority_ids=[], profile=UserProfile.MARKETING)
        )

        percentage = next(item for item in result.visualizations if item.id == "positive-sentiment-rate")
        self.assertIsNone(percentage.value)
        self.assertIsNone(percentage.model_dump(mode="json")["value"])
        self.assertNotIn("sentiment-distribution", [item.id for item in result.visualizations])

    def test_partial_functionality_coverage_is_explicit_and_counts_are_preserved(self):
        source = make_insights([make_cluster("one", score=1)], with_comparison=False)
        source.request.audience_profile = UserProfile.MARKETING
        source.metrics.current = InsightPeriodMetrics(
            feedback_count=3,
            sentiment_distribution={"positive": 2},
            top_functionality_distribution={"HR reporting": 1},
        )

        result = FeedbackVisualizationBuilder.build(
            source, make_report(priority_ids=[], profile=UserProfile.MARKETING)
        )

        bar = next(item for item in result.visualizations if item.id == "product-feedback-by-functionality")
        self.assertEqual(bar.data[0].value, 1)
        self.assertIn("1 feedback(s) représenté(s) sur 3", bar.caption)
        percentage = next(item for item in result.visualizations if item.id == "positive-sentiment-rate")
        self.assertEqual(percentage.value, 100)
        self.assertIn("2 sentiment(s) connu(s) / 3 feedback(s)", percentage.subtitle)
        donut = next(item for item in result.visualizations if item.id == "sentiment-distribution")
        self.assertIn("2 feedback(s) sur 3", donut.caption)

    def test_legacy_comparison_does_not_relabel_combined_distributions_as_current(self):
        source = make_insights(
            [make_cluster("both-periods", score=1)], with_aggregate_metrics=False
        )
        source.request.audience_profile = UserProfile.MARKETING

        result = FeedbackVisualizationBuilder.build(
            source, make_report(priority_ids=[], profile=UserProfile.MARKETING)
        )

        current = next(item for item in result.visualizations if item.id == "current-feedbacks")
        self.assertEqual(current.value, 2)  # ClusterPeriodMetrics.current_count, not member_count.
        percentage = next(item for item in result.visualizations if item.id == "positive-sentiment-rate")
        self.assertIsNone(percentage.value)
        self.assertNotIn("sentiment-distribution", [item.id for item in result.visualizations])
        self.assertTrue(any("Ancien snapshot comparatif" in item for item in result.limitations))

        source.clusters[0].period_metrics = None
        without_period_counts = FeedbackVisualizationBuilder.build(
            source, make_report(priority_ids=[], profile=UserProfile.MARKETING)
        )
        unavailable_count = next(
            item for item in without_period_counts.visualizations if item.id == "current-feedbacks"
        )
        self.assertIsNone(unavailable_count.value)

    def test_positive_signal_volume_uses_current_period_only(self):
        positive = make_cluster(
            "praise", score=1, feedback_type=FeedbackType.POSITIVE_FEEDBACK
        ).model_copy(update={"member_count": 3})
        source = make_insights([positive])
        source.request.audience_profile = UserProfile.MARKETING

        result = FeedbackVisualizationBuilder.build(
            source,
            make_report(priority_ids=[], positive_ids=["praise"], profile=UserProfile.MARKETING),
        )

        bar = next(item for item in result.visualizations if item.id == "positive-signals")
        self.assertEqual(bar.data[0].value, 2)
        table = next(item for item in result.visualizations if item.id == "cluster-summary")
        count_column = next(column for column in table.columns if column.key == "feedback_count")
        self.assertEqual(count_column.label, "Feedbacks (2 périodes)")
        self.assertEqual(table.rows[0].feedback_count, 3)

    def test_builds_a_bounded_safe_specification_for_valid_insights(self):
        technical = make_cluster("technical", score=9.0)
        praise = make_cluster(
            "praise",
            score=2.0,
            feedback_type=FeedbackType.POSITIVE_FEEDBACK,
            category=None,
            sentiment_distribution={"positive": 1},
        )
        review = make_cluster("review", score=5.0, status="needs_review")

        result = FeedbackVisualizationBuilder.build(
            make_insights([technical, praise, review]),
            make_report(priority_ids=["technical"], positive_ids=["praise"]),
        )

        self.assertEqual(result.schema_version, "1.0")
        self.assertEqual(result.source_cluster_ids, ["praise", "review", "technical"])
        self.assertLessEqual(len(result.visualizations), 8)
        self.assertEqual(
            [item.kind for item in result.visualizations],
            [
                VisualizationKind.KPI,
                VisualizationKind.KPI,
                VisualizationKind.KPI,
                VisualizationKind.KPI,
                VisualizationKind.BAR,
                VisualizationKind.BAR,
                VisualizationKind.LINE,
                VisualizationKind.TABLE,
            ],
        )

        bar = next(item for item in result.visualizations if item.kind == "bar")
        self.assertEqual(bar.cluster_ids, ["technical"])
        self.assertEqual(bar.data[0].cluster_ids, ["technical"])
        line = next(item for item in result.visualizations if item.kind == "line")
        self.assertEqual(line.series[0].cluster_id, "technical")
        table = next(item for item in result.visualizations if item.kind == "table")
        self.assertEqual(table.rows[0].cluster_id, "technical")

        # The transport schema has no raw feedback/comment field and cannot
        # smuggle arbitrary executable fields because every model forbids extras.
        payload = result.model_dump(mode="json")
        self.assertNotIn("raw_comment", set(all_mapping_keys(payload)))
        self.assertNotIn("python", set(all_mapping_keys(payload)))
        self.assertNotIn("sql", set(all_mapping_keys(payload)))
        for visualization in result.visualizations:
            rendered = visualization.model_dump(mode="json")
            self.assertIn("report_section", rendered)
            self.assertIn("inline_anchor", rendered)
            self.assertIn("caption", rendered)
            self.assertIn("legend", rendered)

    def test_zero_clusters_returns_only_kpis_and_an_empty_table(self):
        result = FeedbackVisualizationBuilder.build(
            make_insights([], with_comparison=False),
            make_report(priority_ids=[]),
        )

        self.assertEqual(
            [item.kind for item in result.visualizations],
            [
                VisualizationKind.KPI,
                VisualizationKind.KPI,
                VisualizationKind.KPI,
                VisualizationKind.KPI,
                VisualizationKind.TABLE,
            ],
        )
        table = result.visualizations[-1]
        self.assertEqual(table.rows, [])
        self.assertTrue(table.empty_message)
        self.assertTrue(any("Aucun cluster" in item for item in result.limitations))

    def test_rejects_audience_cluster_references_that_are_not_in_insights(self):
        with self.assertRaisesRegex(VisualizationBuildError, "absent from insights"):
            FeedbackVisualizationBuilder.build(
                make_insights([make_cluster("known", score=1.0)]),
                make_report(priority_ids=["unknown"]),
            )

    def test_pydantic_models_forbid_arbitrary_code_fields(self):
        with self.assertRaises(ValidationError):
            KpiVisualizationSpec.model_validate(
                {
                    "id": "unsafe",
                    "kind": "kpi",
                    "title": "Unsafe",
                    "value": 1,
                    "sql": "SELECT * FROM feedback",
                }
            )

    def test_limits_chart_and_table_items_for_large_input(self):
        clusters = [
            make_cluster(f"cluster-{index}", score=float(30 - index))
            for index in range(12)
        ]
        result = FeedbackVisualizationBuilder.build(
            make_insights(clusters),
            make_report(priority_ids=[cluster.temporary_id for cluster in clusters]),
        )

        bar = next(item for item in result.visualizations if item.kind == "bar")
        line = next(item for item in result.visualizations if item.kind == "line")
        table = next(item for item in result.visualizations if item.kind == "table")
        self.assertEqual(len(bar.data), 5)
        self.assertEqual(len(line.series), 4)
        self.assertEqual(len(table.rows), 10)
        self.assertLessEqual(len(result.visualizations), 8)

    def test_line_series_disambiguates_duplicate_cluster_titles(self):
        first = make_cluster("cluster-one", score=5.0, title="Validation bloquée")
        second = make_cluster("cluster-two", score=4.0, title="Validation bloquée")

        result = FeedbackVisualizationBuilder.build(
            make_insights([first, second]),
            make_report(priority_ids=["cluster-one", "cluster-two"]),
        )

        line = next(item for item in result.visualizations if item.kind == "line")
        labels = [series.label for series in line.series]
        self.assertEqual(len(labels), len(set(labels)))
        self.assertTrue(all(label.startswith("Validation bloquée") for label in labels))

    def test_visualization_choice_varies_by_audience_profile(self):
        technical = make_cluster("technical", score=9.0)
        praise = make_cluster(
            "praise",
            score=2.0,
            feedback_type=FeedbackType.POSITIVE_FEEDBACK,
            category=None,
            sentiment_distribution={"positive": 1},
        )
        source = make_insights(
            [
                technical.model_copy(
                    update={"functionality_breakdown": {"Exports": 1}}
                ),
                praise.model_copy(
                    update={"functionality_breakdown": {"Dossier salarié": 1}}
                ),
            ]
        )

        marketing_source = source.model_copy(
            update={
                "request": source.request.model_copy(
                    update={"audience_profile": UserProfile.MARKETING}
                )
            }
        )
        marketing = FeedbackVisualizationBuilder.build(
            marketing_source,
            make_report(
                priority_ids=[],
                positive_ids=["praise"],
                profile=UserProfile.MARKETING,
            ),
        )
        management_source = source.model_copy(
            update={
                "request": source.request.model_copy(
                    update={"audience_profile": UserProfile.MANAGEMENT}
                )
            }
        )
        management = FeedbackVisualizationBuilder.build(
            management_source,
            make_report(
                priority_ids=["technical"],
                profile=UserProfile.MANAGEMENT,
            ),
        )

        marketing_ids = {item.id for item in marketing.visualizations}
        management_ids = {item.id for item in management.visualizations}
        self.assertIn("product-feedback-by-functionality", marketing_ids)
        self.assertIn("positive-signals", marketing_ids)
        self.assertIn("sentiment-distribution", management_ids)
        self.assertIn("priority-signals", management_ids)
        self.assertNotEqual(marketing_ids, management_ids)


if __name__ == "__main__":
    unittest.main()
