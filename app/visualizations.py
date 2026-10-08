"""Deterministic, display-safe visualization specifications for feedback insights.

This module intentionally contains no model invocation, database access, SQL,
Python snippets, or raw customer comments.  It converts an already validated
``FeedbackInsightsResult`` and its ``AudienceReport`` into a small, strictly
typed view model that an API or Streamlit page can render without interpreting
agent-generated instructions.

The specifications carry stable cluster identifiers rather than copies of the
underlying feedback records.  A UI can therefore link a plotted signal back to
the evidence returned by the insights service while keeping visualisation data
bounded and safe to serialise.
"""

from __future__ import annotations

from collections import Counter
from enum import Enum
from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import (
    AudienceReport,
    AudienceReportScope,
    FeedbackInsightsResult,
    InsightPeriodMetrics,
    SentimentLabel,
    TemporaryFeedbackCluster,
    UserProfile,
)


# These limits deliberately keep a POC dashboard readable and protect a
# browser/API response from accidentally mirroring a large insight result.
MAX_VISUALIZATION_SPECS = 8
MAX_KPI_SPECS = 4
MAX_CHART_POINTS = 5
MAX_LINE_SERIES = 4
MAX_TABLE_ROWS = 10
MAX_CLUSTER_REFERENCES = 1_000
MAX_DISPLAY_TEXT_LENGTH = 180


class VisualizationBuildError(ValueError):
    """Raised when insights and audience guidance cannot safely be combined."""


class VisualizationKind(str, Enum):
    """Whitelisted renderer types; a frontend must never execute a free-form type."""

    KPI = "kpi"
    BAR = "bar"
    LINE = "line"
    DONUT = "donut"
    TABLE = "table"


class KpiValueFormat(str, Enum):
    """Display formatting known by the frontend, not an executable formatter."""

    COUNT = "count"
    SCORE = "score"
    PERCENT = "percent"


class ReportSection(str, Enum):
    """Whitelisted anchors for placing a visual after a report paragraph."""

    EXECUTIVE_SUMMARY = "executive_summary"
    CUSTOMER_SENTIMENT = "customer_sentiment"
    PRODUCT_EXPERIENCE = "product_experience"
    TECHNICAL_PRIORITIES = "technical_priorities"
    SUPPORT_EXPERIENCE = "support_experience"
    PERIOD_COMPARISON = "period_comparison"


class ClusterTableColumnKey(str, Enum):
    """Fixed table fields that a client is allowed to render."""

    SIGNAL = "signal"
    STATUS = "status"
    FEEDBACK_COUNT = "feedback_count"
    PRIORITY_SCORE = "priority_score"
    CONFIDENCE = "confidence"
    TREND = "trend"
    FEEDBACK_TYPE = "feedback_type"
    PROBLEM_CATEGORY = "problem_category"


def _normalize_text(value: str, *, fallback: str = "") -> str:
    """Normalize display text without accepting HTML, code, or opaque objects.

    The result is plain text.  Renderers must still use their normal escaped
    text components rather than an unsafe HTML API.
    """

    normalized = " ".join(value.split())
    return (normalized or fallback)[:MAX_DISPLAY_TEXT_LENGTH]


def _percentage_kpi(
    identifier: str,
    title: str,
    value: float | None,
    *,
    known_count: int,
    feedback_count: int,
) -> "KpiVisualizationSpec":
    """Create a consistently labelled percentage KPI without an invented zero."""

    return KpiVisualizationSpec(
        id=identifier,
        title=title,
        value=value,
        value_format=KpiValueFormat.PERCENT,
        subtitle=(
            f"Sur {known_count} sentiment(s) connu(s) / {feedback_count} feedback(s)"
            if value is not None
            else "Sentiment indisponible sur cette période"
        ),
        report_section=ReportSection.CUSTOMER_SENTIMENT,
        inline_anchor=ReportSection.CUSTOMER_SENTIMENT,
        caption="Pourcentage calculé seulement sur les feedbacks dont le sentiment est connu.",
    )


class _VisualizationModel(BaseModel):
    """Shared strict Pydantic configuration for every transport model here."""

    model_config = ConfigDict(extra="forbid")


class VisualizationLegendItem(_VisualizationModel):
    """A fixed-text legend item; it never contains executable styling."""

    label: str = Field(min_length=1, max_length=MAX_DISPLAY_TEXT_LENGTH)
    description: str | None = Field(default=None, max_length=MAX_DISPLAY_TEXT_LENGTH)

    @field_validator("label", "description")
    @classmethod
    def normalize_legend_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_text(value) or None


class VisualizationBase(_VisualizationModel):
    """Common, non-executable metadata for every visualisation."""

    id: str = Field(min_length=1, max_length=80)
    kind: VisualizationKind
    title: str = Field(min_length=1, max_length=MAX_DISPLAY_TEXT_LENGTH)
    # A report renderer can emit the paragraph for this section then place the
    # chart directly after it. The string is constrained to an enum so neither
    # an LLM nor a database value can supply arbitrary markup or selectors.
    report_section: ReportSection = ReportSection.EXECUTIVE_SUMMARY
    inline_anchor: ReportSection = ReportSection.EXECUTIVE_SUMMARY
    caption: str | None = Field(default=None, max_length=MAX_DISPLAY_TEXT_LENGTH)
    legend: list[VisualizationLegendItem] = Field(default_factory=list, max_length=8)
    cluster_ids: list[str] = Field(
        default_factory=list,
        max_length=MAX_CLUSTER_REFERENCES,
    )

    @field_validator("id")
    @classmethod
    def normalize_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("visualization id must not be blank")
        return normalized

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        normalized = _normalize_text(value)
        if not normalized:
            raise ValueError("visualization title must not be blank")
        return normalized

    @field_validator("caption")
    @classmethod
    def normalize_caption(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_text(value) or None

    @model_validator(mode="after")
    def validate_inline_anchor(self) -> "VisualizationBase":
        if self.inline_anchor is not self.report_section:
            raise ValueError("inline_anchor must match report_section")
        legend_labels = [item.label.casefold() for item in self.legend]
        if len(legend_labels) != len(set(legend_labels)):
            raise ValueError("visualization legend labels must be unique")
        return self

    @field_validator("cluster_ids")
    @classmethod
    def normalize_cluster_ids(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            cluster_id = value.strip()
            if not cluster_id:
                raise ValueError("cluster references must not be blank")
            if cluster_id not in seen:
                normalized.append(cluster_id)
                seen.add(cluster_id)
        return normalized


class KpiVisualizationSpec(VisualizationBase):
    """One compact, scalar KPI card."""

    kind: Literal[VisualizationKind.KPI] = VisualizationKind.KPI
    value: float | None = Field(ge=0)
    value_format: KpiValueFormat = KpiValueFormat.COUNT
    subtitle: str | None = Field(default=None, max_length=MAX_DISPLAY_TEXT_LENGTH)

    @field_validator("subtitle")
    @classmethod
    def normalize_subtitle(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_text(value) or None


class ChartDatum(_VisualizationModel):
    """One bounded non-executable datum for a bar or donut chart."""

    label: str = Field(min_length=1, max_length=MAX_DISPLAY_TEXT_LENGTH)
    value: float = Field(ge=0)
    # Aggregate breakdowns (for example, a current-period sentiment rate) are
    # intentionally not forced to claim a per-cluster attribution.
    cluster_ids: list[str] = Field(default_factory=list, max_length=MAX_CLUSTER_REFERENCES)

    @field_validator("label")
    @classmethod
    def normalize_label(cls, value: str) -> str:
        normalized = _normalize_text(value)
        if not normalized:
            raise ValueError("chart label must not be blank")
        return normalized

    @field_validator("cluster_ids")
    @classmethod
    def normalize_cluster_ids(cls, values: list[str]) -> list[str]:
        return VisualizationBase.normalize_cluster_ids(values)


class BarVisualizationSpec(VisualizationBase):
    """A ranked bar chart of audience-relevant cluster priority scores."""

    kind: Literal[VisualizationKind.BAR] = VisualizationKind.BAR
    value_label: str = Field(min_length=1, max_length=MAX_DISPLAY_TEXT_LENGTH)
    data: list[ChartDatum] = Field(min_length=1, max_length=MAX_CHART_POINTS)

    @field_validator("value_label")
    @classmethod
    def normalize_value_label(cls, value: str) -> str:
        normalized = _normalize_text(value)
        if not normalized:
            raise ValueError("bar value_label must not be blank")
        return normalized

    @model_validator(mode="after")
    def validate_chart_references(self) -> "BarVisualizationSpec":
        data_ids = {
            cluster_id
            for datum in self.data
            for cluster_id in datum.cluster_ids
        }
        if not data_ids.issubset(set(self.cluster_ids)):
            raise ValueError("bar chart data must only reference its clusters")
        return self


class DonutVisualizationSpec(VisualizationBase):
    """A sentiment distribution grouped only from existing cluster facts."""

    kind: Literal[VisualizationKind.DONUT] = VisualizationKind.DONUT
    value_label: str = Field(min_length=1, max_length=MAX_DISPLAY_TEXT_LENGTH)
    data: list[ChartDatum] = Field(min_length=1, max_length=5)

    @field_validator("value_label")
    @classmethod
    def normalize_value_label(cls, value: str) -> str:
        normalized = _normalize_text(value)
        if not normalized:
            raise ValueError("donut value_label must not be blank")
        return normalized

    @model_validator(mode="after")
    def validate_chart_references(self) -> "DonutVisualizationSpec":
        data_ids = {
            cluster_id
            for datum in self.data
            for cluster_id in datum.cluster_ids
        }
        if not data_ids.issubset(set(self.cluster_ids)):
            raise ValueError("donut chart data must only reference its clusters")
        return self


class LinePoint(_VisualizationModel):
    """One of the two fixed periods in a comparison series."""

    period: Literal["comparison", "current"]
    value: int = Field(ge=0)


class LineSeries(_VisualizationModel):
    """One cluster line, restricted to the comparison and current counts."""

    cluster_id: str = Field(min_length=1, max_length=160)
    label: str = Field(min_length=1, max_length=MAX_DISPLAY_TEXT_LENGTH)
    points: list[LinePoint] = Field(min_length=2, max_length=2)

    @field_validator("cluster_id")
    @classmethod
    def normalize_cluster_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("line series cluster_id must not be blank")
        return normalized

    @field_validator("label")
    @classmethod
    def normalize_label(cls, value: str) -> str:
        normalized = _normalize_text(value)
        if not normalized:
            raise ValueError("line series label must not be blank")
        return normalized

    @model_validator(mode="after")
    def require_one_point_per_period(self) -> "LineSeries":
        if {point.period for point in self.points} != {"comparison", "current"}:
            raise ValueError("line series must contain current and comparison points")
        return self


class LineVisualizationSpec(VisualizationBase):
    """A period-over-period trend chart for a handful of selected clusters."""

    kind: Literal[VisualizationKind.LINE] = VisualizationKind.LINE
    value_label: str = Field(min_length=1, max_length=MAX_DISPLAY_TEXT_LENGTH)
    series: list[LineSeries] = Field(min_length=1, max_length=MAX_LINE_SERIES)

    @field_validator("value_label")
    @classmethod
    def normalize_value_label(cls, value: str) -> str:
        normalized = _normalize_text(value)
        if not normalized:
            raise ValueError("line value_label must not be blank")
        return normalized

    @model_validator(mode="after")
    def validate_series_references(self) -> "LineVisualizationSpec":
        series_ids = [series.cluster_id for series in self.series]
        if len(series_ids) != len(set(series_ids)):
            raise ValueError("line series must refer to distinct clusters")
        if set(series_ids) != set(self.cluster_ids):
            raise ValueError("line series must match its cluster references")
        return self


class ClusterTableColumn(_VisualizationModel):
    """A fixed, display-only column definition for a cluster table."""

    key: ClusterTableColumnKey
    label: str = Field(min_length=1, max_length=MAX_DISPLAY_TEXT_LENGTH)

    @field_validator("label")
    @classmethod
    def normalize_label(cls, value: str) -> str:
        normalized = _normalize_text(value)
        if not normalized:
            raise ValueError("table column label must not be blank")
        return normalized


class ClusterTableRow(_VisualizationModel):
    """A safe, fixed-schema cluster summary row; it has no feedback text field."""

    cluster_id: str = Field(min_length=1, max_length=160)
    signal: str = Field(min_length=1, max_length=MAX_DISPLAY_TEXT_LENGTH)
    status: Literal["clustered", "singleton", "needs_review"]
    feedback_count: int = Field(ge=1)
    priority_score: float = Field(ge=0)
    confidence: float = Field(ge=0, le=1)
    trend: Literal["new", "up", "stable", "down"] | None = None
    feedback_type: str | None = Field(default=None, max_length=80)
    problem_category: str | None = Field(default=None, max_length=80)

    @field_validator("cluster_id")
    @classmethod
    def normalize_cluster_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("table row cluster_id must not be blank")
        return normalized

    @field_validator("signal")
    @classmethod
    def normalize_signal(cls, value: str) -> str:
        normalized = _normalize_text(value)
        if not normalized:
            raise ValueError("table row signal must not be blank")
        return normalized

    @field_validator("feedback_type", "problem_category")
    @classmethod
    def normalize_optional_category(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_text(value) or None


class TableVisualizationSpec(VisualizationBase):
    """A bounded table for navigating from a dashboard item to a cluster id."""

    kind: Literal[VisualizationKind.TABLE] = VisualizationKind.TABLE
    columns: list[ClusterTableColumn] = Field(min_length=1, max_length=8)
    rows: list[ClusterTableRow] = Field(max_length=MAX_TABLE_ROWS)
    empty_message: str | None = Field(default=None, max_length=MAX_DISPLAY_TEXT_LENGTH)

    @field_validator("empty_message")
    @classmethod
    def normalize_empty_message(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_text(value) or None

    @model_validator(mode="after")
    def validate_table_shape(self) -> "TableVisualizationSpec":
        column_keys = [column.key for column in self.columns]
        if len(column_keys) != len(set(column_keys)):
            raise ValueError("table columns must be unique")

        row_ids = [row.cluster_id for row in self.rows]
        if len(row_ids) != len(set(row_ids)):
            raise ValueError("table rows must refer to distinct clusters")
        if set(row_ids) != set(self.cluster_ids):
            raise ValueError("table rows must match its cluster references")
        if not self.rows and not self.empty_message:
            raise ValueError("an empty table requires an empty_message")
        return self


VisualizationSpec: TypeAlias = Annotated[
    KpiVisualizationSpec
    | BarVisualizationSpec
    | DonutVisualizationSpec
    | LineVisualizationSpec
    | TableVisualizationSpec,
    Field(discriminator="kind"),
]


class FeedbackVisualizations(_VisualizationModel):
    """A bounded, self-validating payload ready for an API or Streamlit renderer."""

    schema_version: Literal["1.0"] = "1.0"
    audience_profile: UserProfile
    scope: AudienceReportScope
    source_cluster_ids: list[str] = Field(max_length=MAX_CLUSTER_REFERENCES)
    visualizations: list[VisualizationSpec] = Field(
        min_length=1,
        max_length=MAX_VISUALIZATION_SPECS,
    )
    limitations: list[str]

    @field_validator("source_cluster_ids")
    @classmethod
    def normalize_source_cluster_ids(cls, values: list[str]) -> list[str]:
        return VisualizationBase.normalize_cluster_ids(values)

    @field_validator("limitations")
    @classmethod
    def normalize_limitations(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            item = _normalize_text(value)
            if item and item not in seen:
                normalized.append(item)
                seen.add(item)
        return normalized

    @model_validator(mode="after")
    def validate_references_and_ids(self) -> "FeedbackVisualizations":
        visualization_ids = [visualization.id for visualization in self.visualizations]
        if len(visualization_ids) != len(set(visualization_ids)):
            raise ValueError("visualization ids must be unique")

        source_ids = set(self.source_cluster_ids)
        for visualization in self.visualizations:
            unknown = set(visualization.cluster_ids) - source_ids
            if unknown:
                raise ValueError(
                    "visualization references cluster ids absent from the source result"
                )
        return self


class FeedbackVisualizationBuilder:
    """Build a finite, deterministic dashboard model from factual insight output.

    It does not infer new facts or change priority.  The audience report only
    selects existing cluster identifiers; all metrics and chart values come
    directly from the already computed insight result.
    """

    @classmethod
    def build(
        cls,
        insights: FeedbackInsightsResult,
        audience_report: AudienceReport,
    ) -> FeedbackVisualizations:
        insights = FeedbackInsightsResult.model_validate(insights)
        audience_report = AudienceReport.model_validate(audience_report)
        clusters_by_id = {
            cluster.temporary_id: cluster for cluster in insights.clusters
        }
        if len(clusters_by_id) != len(insights.clusters):
            raise VisualizationBuildError("Insights contain duplicate temporary cluster ids.")
        if audience_report.profile is not insights.request.audience_profile:
            raise VisualizationBuildError(
                "Audience report profile does not match the insight request profile."
            )
        cls._validate_audience_references(audience_report, clusters_by_id)

        ranked_clusters = cls._ranked_clusters(insights.clusters)
        focused_clusters = cls._focused_clusters(
            audience_report=audience_report,
            clusters_by_id=clusters_by_id,
            ranked_clusters=ranked_clusters,
        )

        visualizations: list[VisualizationSpec] = cls._kpis(
            insights=insights,
            audience_report=audience_report,
        )
        visualizations.extend(
            cls._profile_visualizations(
                insights=insights,
                audience_report=audience_report,
                ranked_clusters=ranked_clusters,
                focused_clusters=focused_clusters,
                clusters_by_id=clusters_by_id,
            )
        )
        visualizations.append(
            cls._cluster_table(
                ranked_clusters,
                focused_clusters,
                profile=audience_report.profile,
            )
        )
        if len(visualizations) > MAX_VISUALIZATION_SPECS:
            raise VisualizationBuildError("Visualization specification limit exceeded.")

        limitations = list(dict.fromkeys([
            *insights.limitations,
            *audience_report.limitations,
        ]))
        if insights.metrics is None and insights.request.comparison_start_date is not None:
            limitations.append(
                "Ancien snapshot comparatif : les répartitions par période sont indisponibles ; "
                "les distributions cumulées ne sont pas utilisées comme chiffres de la période courante."
            )
        if not ranked_clusters:
            limitations.append(
                "Aucun cluster n'est disponible pour construire des graphiques de signal."
            )

        return FeedbackVisualizations(
            audience_profile=audience_report.profile,
            scope=audience_report.scope,
            source_cluster_ids=sorted(clusters_by_id),
            visualizations=visualizations,
            limitations=limitations,
        )

    @classmethod
    def _profile_visualizations(
        cls,
        *,
        insights: FeedbackInsightsResult,
        audience_report: AudienceReport,
        ranked_clusters: list[TemporaryFeedbackCluster],
        focused_clusters: list[TemporaryFeedbackCluster],
        clusters_by_id: dict[str, TemporaryFeedbackCluster],
    ) -> list[VisualizationSpec]:
        """Choose a small, audience-relevant chart set instead of a fixed set."""

        profile = audience_report.profile
        current_metrics = cls._current_metrics(insights)
        all_cluster_ids = [cluster.temporary_id for cluster in ranked_clusters]
        positive_clusters = [
            clusters_by_id[cluster_id]
            for cluster_id in audience_report.positive_signal_ids
            if cluster_id in clusters_by_id
        ][:MAX_CHART_POINTS]
        charts: list[VisualizationSpec] = []

        if profile is UserProfile.MARKETING:
            charts.extend(
                item
                for item in (
                    cls._sentiment_donut(
                        current_metrics,
                        all_cluster_ids,
                        section=ReportSection.CUSTOMER_SENTIMENT,
                        title="Sentiment des clients sur la période",
                    ),
                    cls._breakdown_bar(
                        current_metrics.top_functionality_distribution,
                        all_cluster_ids,
                        chart_id="product-feedback-by-functionality",
                        title="Fonctionnalités les plus citées",
                        value_label="Nombre de feedbacks",
                        section=ReportSection.PRODUCT_EXPERIENCE,
                        caption=cls._breakdown_caption(
                            current_metrics.top_functionality_distribution,
                            current_metrics.feedback_count,
                            subject="fonctionnalité renseignée",
                        ),
                    ),
                    cls._signal_volume_bar(
                        positive_clusters,
                        chart_id="positive-signals",
                        title="Signaux positifs à valoriser",
                        section=ReportSection.PRODUCT_EXPERIENCE,
                        value_label="Nombre de feedbacks",
                    ),
                )
                if item is not None
            )
        elif profile is UserProfile.IT:
            charts.extend(
                item
                for item in (
                    cls._priority_bar(
                        focused_clusters,
                        section=ReportSection.TECHNICAL_PRIORITIES,
                        title="Signaux techniques à investiguer",
                    ),
                    cls._breakdown_bar(
                        current_metrics.problem_category_distribution,
                        all_cluster_ids,
                        chart_id="technical-problems-by-category",
                        title="Catégories de problèmes signalées",
                        value_label="Nombre de feedbacks",
                        section=ReportSection.TECHNICAL_PRIORITIES,
                        caption=cls._breakdown_caption(
                            current_metrics.problem_category_distribution,
                            current_metrics.feedback_count,
                            subject="catégorie de problème renseignée",
                        ),
                    ),
                    cls._trend_line(
                        insights=insights,
                        focused_clusters=focused_clusters,
                        section=ReportSection.PERIOD_COMPARISON,
                        title="Évolution des signaux techniques",
                    ),
                )
                if item is not None
            )
        elif profile is UserProfile.SUPPORT_SALES:
            charts.extend(
                item
                for item in (
                    cls._breakdown_bar(
                        current_metrics.feedback_type_distribution,
                        all_cluster_ids,
                        chart_id="customer-needs-by-type",
                        title="Nature des demandes clients",
                        value_label="Nombre de feedbacks",
                        section=ReportSection.SUPPORT_EXPERIENCE,
                        caption=cls._breakdown_caption(
                            current_metrics.feedback_type_distribution,
                            current_metrics.feedback_count,
                            subject="type renseigné",
                        ),
                    ),
                    cls._priority_bar(
                        focused_clusters,
                        section=ReportSection.SUPPORT_EXPERIENCE,
                        title="Sujets à traiter avec les clients",
                    ),
                    cls._trend_line(
                        insights=insights,
                        focused_clusters=focused_clusters,
                        section=ReportSection.PERIOD_COMPARISON,
                        title="Évolution des sujets à traiter",
                    ),
                )
                if item is not None
            )
        else:
            charts.extend(
                item
                for item in (
                    cls._priority_bar(
                        focused_clusters,
                        section=ReportSection.EXECUTIVE_SUMMARY,
                        title="Signaux prioritaires",
                    ),
                    cls._sentiment_donut(
                        current_metrics,
                        all_cluster_ids,
                        section=ReportSection.CUSTOMER_SENTIMENT,
                        title="Satisfaction perçue sur la période",
                    ),
                    cls._trend_line(
                        insights=insights,
                        focused_clusters=focused_clusters,
                        section=ReportSection.PERIOD_COMPARISON,
                        title="Évolution des signaux prioritaires",
                    ),
                )
                if item is not None
            )

        # Four KPI cards and one table leave room for exactly three charts.
        return charts[: MAX_VISUALIZATION_SPECS - MAX_KPI_SPECS - 1]

    @classmethod
    def build_specs(
        cls,
        insights: FeedbackInsightsResult,
        audience_report: AudienceReport,
    ) -> list[VisualizationSpec]:
        """Return only the renderer list for callers that already carry scope."""

        return cls.build(insights, audience_report).visualizations

    @staticmethod
    def _validate_audience_references(
        audience_report: AudienceReport,
        clusters_by_id: dict[str, TemporaryFeedbackCluster],
    ) -> None:
        referenced_ids = {
            *audience_report.priority_signal_ids,
            *audience_report.positive_signal_ids,
            *audience_report.watch_list_ids,
        }
        unknown = referenced_ids - set(clusters_by_id)
        if unknown:
            raise VisualizationBuildError(
                "Audience report references cluster ids that are absent from insights: "
                f"{', '.join(sorted(unknown))}."
            )

    @staticmethod
    def _ranked_clusters(
        clusters: list[TemporaryFeedbackCluster],
    ) -> list[TemporaryFeedbackCluster]:
        return sorted(
            clusters,
            key=lambda cluster: (-cluster.priority.score, cluster.temporary_id),
        )

    @classmethod
    def _focused_clusters(
        cls,
        *,
        audience_report: AudienceReport,
        clusters_by_id: dict[str, TemporaryFeedbackCluster],
        ranked_clusters: list[TemporaryFeedbackCluster],
    ) -> list[TemporaryFeedbackCluster]:
        selected_ids: list[str] = []
        for cluster_id in audience_report.priority_signal_ids:
            if cluster_id not in selected_ids:
                selected_ids.append(cluster_id)

        # A report may legitimately have no profile-specific priorities.  In
        # that case show confirmed clusters, still sorted by the precomputed
        # priority score, instead of inventing an audience-specific ranking.
        if not selected_ids:
            selected_ids = [
                cluster.temporary_id
                for cluster in ranked_clusters
                if cluster.status == "clustered"
            ]
        return [
            clusters_by_id[cluster_id]
            for cluster_id in selected_ids[:MAX_CHART_POINTS]
        ]

    @classmethod
    def _current_metrics(cls, insights: FeedbackInsightsResult) -> InsightPeriodMetrics:
        """Prefer server-calculated current-period metrics; retain POC snapshot compatibility."""

        if insights.metrics is not None:
            return insights.metrics.current
        if insights.request.comparison_start_date is not None:
            # Legacy clusters pool both periods. Their distributions cannot be
            # split accurately, unlike counts carried by period_metrics.
            return InsightPeriodMetrics(
                feedback_count=sum(
                    cluster.period_metrics.current_count
                    for cluster in insights.clusters
                    if cluster.period_metrics is not None
                ),
            )
        sentiments: Counter[str] = Counter()
        feedback_types: Counter[str] = Counter()
        problem_categories: Counter[str] = Counter()
        functionalities: Counter[str] = Counter()
        for cluster in insights.clusters:
            for label, count in cluster.sentiment_distribution.items():
                sentiments[label] += count
            if cluster.feedback_type is not None:
                feedback_types[cluster.feedback_type.value] += cluster.member_count
            if cluster.dominant_problem_category is not None:
                problem_categories[cluster.dominant_problem_category.value] += cluster.member_count
            for label, count in cluster.functionality_breakdown.items():
                functionalities[label] += count
        return InsightPeriodMetrics(
            feedback_count=insights.total_feedbacks,
            sentiment_distribution=dict(sentiments),
            feedback_type_distribution=dict(feedback_types),
            problem_category_distribution=dict(problem_categories),
            top_functionality_distribution=dict(
                sorted(functionalities.items(), key=lambda item: (-item[1], item[0].casefold()))[:20]
            ),
        )

    @classmethod
    def _kpis(
        cls,
        *,
        insights: FeedbackInsightsResult,
        audience_report: AudienceReport,
    ) -> list[KpiVisualizationSpec]:
        current = cls._current_metrics(insights)
        known_sentiments = sum(current.sentiment_distribution.values())
        positive_rate = (
            round(100 * current.sentiment_distribution.get("positive", 0) / known_sentiments, 1)
            if known_sentiments else None
        )
        negative_or_mixed = (
            current.sentiment_distribution.get("negative", 0)
            + current.sentiment_distribution.get("mixed", 0)
        )
        confirmed_count = sum(cluster.status == "clustered" for cluster in insights.clusters)
        needs_review_count = sum(cluster.status == "needs_review" for cluster in insights.clusters)
        priority_count = len(audience_report.priority_signal_ids)
        current_count_unknown = (
            insights.metrics is None
            and insights.request.comparison_start_date is not None
            and any(cluster.period_metrics is None for cluster in insights.clusters)
        )
        common = [
            KpiVisualizationSpec(
                id="current-feedbacks",
                title="Feedbacks sur la période",
                value=None if current_count_unknown else float(current.feedback_count),
                subtitle=(
                    "Volume courant indisponible dans cet ancien snapshot"
                    if current_count_unknown else "Périmètre courant demandé"
                ),
                report_section=ReportSection.EXECUTIVE_SUMMARY,
                inline_anchor=ReportSection.EXECUTIVE_SUMMARY,
                caption="Volume de feedbacks inclus dans cette analyse.",
            )
        ]
        if audience_report.profile is UserProfile.MARKETING:
            return [
                *common,
                _percentage_kpi(
                    "positive-sentiment-rate", "Sentiments positifs", positive_rate,
                    known_count=known_sentiments, feedback_count=current.feedback_count,
                ),
                KpiVisualizationSpec(
                    id="positive-signals-count", title="Signaux positifs à valoriser",
                    value=float(len(audience_report.positive_signal_ids)),
                    subtitle="Clusters positifs confirmés",
                    report_section=ReportSection.PRODUCT_EXPERIENCE,
                    inline_anchor=ReportSection.PRODUCT_EXPERIENCE,
                ),
                KpiVisualizationSpec(
                    id="product-areas-mentioned", title="Fonctionnalités citées",
                    value=float(len(current.top_functionality_distribution)),
                    subtitle="Fonctionnalités distinctes dans le top de la période",
                    report_section=ReportSection.PRODUCT_EXPERIENCE,
                    inline_anchor=ReportSection.PRODUCT_EXPERIENCE,
                ),
            ]
        if audience_report.profile is UserProfile.IT:
            return [
                *common,
                KpiVisualizationSpec(
                    id="negative-or-mixed-feedbacks", title="Feedbacks négatifs ou mitigés",
                    value=(
                        None if current_count_unknown or (current.feedback_count and not known_sentiments)
                        else float(negative_or_mixed)
                    ),
                    subtitle="Parmi les sentiments détectés",
                    report_section=ReportSection.TECHNICAL_PRIORITIES,
                    inline_anchor=ReportSection.TECHNICAL_PRIORITIES,
                ),
                KpiVisualizationSpec(
                    id="technical-priority-signals", title="Signaux techniques prioritaires",
                    value=float(priority_count), subtitle="À investiguer",
                    report_section=ReportSection.TECHNICAL_PRIORITIES,
                    inline_anchor=ReportSection.TECHNICAL_PRIORITIES,
                ),
                KpiVisualizationSpec(
                    id="technical-problem-categories", title="Catégories de problème",
                    value=float(len(current.problem_category_distribution)),
                    subtitle="Classifiées dans la période courante",
                    report_section=ReportSection.TECHNICAL_PRIORITIES,
                    inline_anchor=ReportSection.TECHNICAL_PRIORITIES,
                ),
            ]
        if audience_report.profile is UserProfile.SUPPORT_SALES:
            customer_needs = sum(
                count for label, count in current.feedback_type_distribution.items()
                if label in {"issue_report", "feature_request", "information_request", "improvement_suggestion"}
            )
            return [
                *common,
                KpiVisualizationSpec(
                    id="customer-needs", title="Demandes ou problèmes clients",
                    value=(
                        None if current_count_unknown or (
                            current.feedback_count and not current.feedback_type_distribution
                        ) else float(customer_needs)
                    ),
                    subtitle="Demandes, signalements ou besoins d'information",
                    report_section=ReportSection.SUPPORT_EXPERIENCE,
                    inline_anchor=ReportSection.SUPPORT_EXPERIENCE,
                ),
                KpiVisualizationSpec(
                    id="support-priority-signals", title="Sujets prioritaires",
                    value=float(priority_count), subtitle="À qualifier ou traiter",
                    report_section=ReportSection.SUPPORT_EXPERIENCE,
                    inline_anchor=ReportSection.SUPPORT_EXPERIENCE,
                ),
                KpiVisualizationSpec(
                    id="signals-needing-review", title="Signaux à vérifier",
                    value=float(needs_review_count), subtitle="À valider avant action client",
                    report_section=ReportSection.SUPPORT_EXPERIENCE,
                    inline_anchor=ReportSection.SUPPORT_EXPERIENCE,
                ),
            ]
        return [
            *common,
            _percentage_kpi(
                "positive-sentiment-rate", "Sentiments positifs", positive_rate,
                known_count=known_sentiments, feedback_count=current.feedback_count,
            ),
            KpiVisualizationSpec(
                id="priority-signals-count", title="Signaux prioritaires",
                value=float(priority_count or confirmed_count), subtitle="Clusters confirmés à suivre",
                report_section=ReportSection.EXECUTIVE_SUMMARY,
                inline_anchor=ReportSection.EXECUTIVE_SUMMARY,
            ),
            KpiVisualizationSpec(
                id="signals-needing-review", title="Signaux à vérifier",
                value=float(needs_review_count), subtitle="À confirmer avant arbitrage",
                report_section=ReportSection.EXECUTIVE_SUMMARY,
                inline_anchor=ReportSection.EXECUTIVE_SUMMARY,
            ),
        ]


    @staticmethod
    def _priority_bar(
        clusters: list[TemporaryFeedbackCluster],
        *,
        section: ReportSection,
        title: str,
    ) -> BarVisualizationSpec | None:
        if not clusters:
            return None
        data = [
            ChartDatum(
                label=_display_cluster_title(cluster),
                value=cluster.priority.score,
                cluster_ids=[cluster.temporary_id],
            )
            for cluster in clusters
        ]
        return BarVisualizationSpec(
            id="priority-signals",
            title=title,
            cluster_ids=[cluster.temporary_id for cluster in clusters],
            value_label="Score de priorité",
            data=data,
            report_section=section,
            inline_anchor=section,
            caption="Classement déterministe fondé sur le volume, la sévérité et, si disponible, l'évolution.",
            legend=[
                VisualizationLegendItem(
                    label="Score de priorité",
                    description="Plus le score est élevé, plus le signal mérite une attention.",
                )
            ],
        )

    @staticmethod
    def _signal_volume_bar(
        clusters: list[TemporaryFeedbackCluster],
        *,
        chart_id: str,
        title: str,
        section: ReportSection,
        value_label: str,
    ) -> BarVisualizationSpec | None:
        if not clusters:
            return None
        return BarVisualizationSpec(
            id=chart_id,
            title=title,
            cluster_ids=[cluster.temporary_id for cluster in clusters],
            value_label=value_label,
            data=[
                ChartDatum(
                    label=_display_cluster_title(cluster),
                    value=float(
                        cluster.period_metrics.current_count
                        if cluster.period_metrics is not None
                        else cluster.member_count
                    ),
                    cluster_ids=[cluster.temporary_id],
                )
                for cluster in clusters
            ],
            report_section=section,
            inline_anchor=section,
            caption="Feedbacks de la période courante regroupés dans chaque signal confirmé.",
            legend=[VisualizationLegendItem(label=value_label)],
        )

    @staticmethod
    def _breakdown_caption(
        breakdown: dict[str, int], feedback_count: int, *, subject: str
    ) -> str:
        """Explain coverage without treating missing classifications as zero mentions."""

        shown = sum(sorted(breakdown.values(), reverse=True)[:MAX_CHART_POINTS])
        return (
            f"{shown} feedback(s) représenté(s) sur {feedback_count}. "
            f"Seulement ceux avec {subject} ; {MAX_CHART_POINTS} catégories maximum."
        )

    @staticmethod
    def _breakdown_bar(
        breakdown: dict[str, int],
        cluster_ids: list[str],
        *,
        chart_id: str,
        title: str,
        value_label: str,
        section: ReportSection,
        caption: str,
    ) -> BarVisualizationSpec | None:
        items = sorted(
            ((label, count) for label, count in breakdown.items() if count > 0),
            key=lambda item: (-item[1], item[0].casefold()),
        )[:MAX_CHART_POINTS]
        if not items:
            return None
        return BarVisualizationSpec(
            id=chart_id,
            title=title,
            cluster_ids=cluster_ids,
            value_label=value_label,
            data=[ChartDatum(label=label, value=float(count)) for label, count in items],
            report_section=section,
            inline_anchor=section,
            caption=caption,
            legend=[VisualizationLegendItem(label=value_label)],
        )

    @staticmethod
    def _sentiment_donut(
        current_metrics: InsightPeriodMetrics,
        cluster_ids: list[str],
        *,
        section: ReportSection,
        title: str,
    ) -> DonutVisualizationSpec | None:
        counts = {
            label: count
            for label, count in current_metrics.sentiment_distribution.items()
            if count > 0
        }
        if not counts:
            return None
        known_order = [label.value for label in SentimentLabel]
        labels = [
            *[label for label in known_order if label in counts],
            *sorted(label for label in counts if label not in known_order),
        ]
        return DonutVisualizationSpec(
            id="sentiment-distribution",
            title=title,
            cluster_ids=cluster_ids,
            value_label="Nombre de feedbacks",
            data=[ChartDatum(label=label, value=float(counts[label])) for label in labels],
            report_section=section,
            inline_anchor=section,
            caption=(
                f"Sentiment connu pour {sum(counts.values())} feedback(s) "
                f"sur {current_metrics.feedback_count} dans la période courante."
            ),
            legend=[
                VisualizationLegendItem(
                    label=label,
                    description=f"{counts[label]} feedback(s)",
                )
                for label in labels
            ],
        )


    @staticmethod
    def _trend_line(
        *,
        insights: FeedbackInsightsResult,
        focused_clusters: list[TemporaryFeedbackCluster],
        section: ReportSection,
        title: str,
    ) -> LineVisualizationSpec | None:
        if (
            insights.request.comparison_start_date is None
            or insights.request.comparison_end_date is None
        ):
            return None
        comparable = [
            cluster
            for cluster in focused_clusters
            if cluster.period_metrics is not None
        ][:MAX_LINE_SERIES]
        if not comparable:
            return None
        series_labels = FeedbackVisualizationBuilder._unique_line_series_labels(
            comparable
        )
        return LineVisualizationSpec(
            id="signal-trends",
            title=title,
            cluster_ids=[cluster.temporary_id for cluster in comparable],
            value_label="Nombre de feedbacks",
            series=[
                LineSeries(
                    cluster_id=cluster.temporary_id,
                    label=series_labels[cluster.temporary_id],
                    points=[
                        LinePoint(period="comparison", value=cluster.period_metrics.previous_count),
                        LinePoint(period="current", value=cluster.period_metrics.current_count),
                    ],
                )
                for cluster in comparable
            ],
            report_section=section,
            inline_anchor=section,
            caption="Comparaison entre la période de référence et la période courante.",
            legend=[
                VisualizationLegendItem(
                    label=series_labels[cluster.temporary_id],
                    description=(
                        f"{cluster.period_metrics.previous_count} en comparaison, "
                        f"{cluster.period_metrics.current_count} sur la période courante"
                    ),
                )
                for cluster in comparable
            ],
        )


    @staticmethod
    def _unique_line_series_labels(
        clusters: list[TemporaryFeedbackCluster],
    ) -> dict[str, str]:
        """Return readable, distinct labels for dataframe-backed line series.

        A cluster title is descriptive rather than an identifier, so two
        unrelated clusters may legitimately share it. Streamlit pivots the
        comparison points by series label; duplicate labels would make that
        pivot ambiguous. Keep the ordinary title when possible and append a
        short stable part of the cluster identifier only when needed.
        """

        base_labels = {
            cluster.temporary_id: _display_cluster_title(cluster)
            for cluster in clusters
        }
        base_counts = Counter(base_labels.values())
        labels: dict[str, str] = {}
        used_labels: set[str] = set()

        for cluster in clusters:
            cluster_id = cluster.temporary_id
            base_label = base_labels[cluster_id]
            candidate = base_label
            if base_counts[base_label] > 1:
                suffix = f" · {cluster_id[-8:]}"
                candidate = f"{base_label[: MAX_DISPLAY_TEXT_LENGTH - len(suffix)]}{suffix}"

            duplicate_index = 2
            while candidate in used_labels:
                suffix = f" · {cluster_id[-8:]} #{duplicate_index}"
                candidate = (
                    f"{base_label[: MAX_DISPLAY_TEXT_LENGTH - len(suffix)]}{suffix}"
                )
                duplicate_index += 1

            labels[cluster_id] = candidate
            used_labels.add(candidate)
        return labels

    @classmethod
    def _cluster_table(
        cls,
        ranked_clusters: list[TemporaryFeedbackCluster],
        focused_clusters: list[TemporaryFeedbackCluster],
        *,
        profile: UserProfile,
    ) -> TableVisualizationSpec:
        focused_ids = {cluster.temporary_id for cluster in focused_clusters}
        ordered = [
            *focused_clusters,
            *(
                cluster
                for cluster in ranked_clusters
                if cluster.temporary_id not in focused_ids
            ),
        ][:MAX_TABLE_ROWS]
        rows = [
            ClusterTableRow(
                cluster_id=cluster.temporary_id,
                signal=_display_cluster_title(cluster),
                status=cluster.status,
                feedback_count=cluster.member_count,
                priority_score=cluster.priority.score,
                confidence=cluster.confidence,
                trend=(
                    cluster.period_metrics.trend
                    if cluster.period_metrics is not None
                    else None
                ),
                feedback_type=(
                    cluster.feedback_type.value
                    if cluster.feedback_type is not None
                    else None
                ),
                problem_category=(
                    cluster.dominant_problem_category.value
                    if cluster.dominant_problem_category is not None
                    else None
                ),
            )
            for cluster in ordered
        ]
        return TableVisualizationSpec(
            id="cluster-summary",
            title="Synthèse des signaux",
            cluster_ids=[row.cluster_id for row in rows],
            columns=[
                ClusterTableColumn(
                    key=ClusterTableColumnKey.SIGNAL,
                    label="Signal",
                ),
                ClusterTableColumn(
                    key=ClusterTableColumnKey.STATUS,
                    label="Statut",
                ),
                ClusterTableColumn(
                    key=ClusterTableColumnKey.FEEDBACK_COUNT,
                    label=(
                        "Feedbacks (2 périodes)"
                        if any(cluster.period_metrics is not None for cluster in ordered)
                        else "Feedbacks"
                    ),
                ),
                ClusterTableColumn(
                    key=ClusterTableColumnKey.PRIORITY_SCORE,
                    label="Priorité",
                ),
                ClusterTableColumn(
                    key=ClusterTableColumnKey.CONFIDENCE,
                    label="Confiance",
                ),
                ClusterTableColumn(
                    key=ClusterTableColumnKey.TREND,
                    label="Évolution",
                ),
                ClusterTableColumn(
                    key=ClusterTableColumnKey.FEEDBACK_TYPE,
                    label="Type",
                ),
                ClusterTableColumn(
                    key=ClusterTableColumnKey.PROBLEM_CATEGORY,
                    label="Catégorie",
                ),
            ],
            rows=rows,
            report_section=(
                ReportSection.TECHNICAL_PRIORITIES
                if profile is UserProfile.IT
                else (
                    ReportSection.PRODUCT_EXPERIENCE
                    if profile is UserProfile.MARKETING
                    else (
                        ReportSection.SUPPORT_EXPERIENCE
                        if profile is UserProfile.SUPPORT_SALES
                        else ReportSection.EXECUTIVE_SUMMARY
                    )
                )
            ),
            inline_anchor=(
                ReportSection.TECHNICAL_PRIORITIES
                if profile is UserProfile.IT
                else (
                    ReportSection.PRODUCT_EXPERIENCE
                    if profile is UserProfile.MARKETING
                    else (
                        ReportSection.SUPPORT_EXPERIENCE
                        if profile is UserProfile.SUPPORT_SALES
                        else ReportSection.EXECUTIVE_SUMMARY
                    )
                )
            ),
            caption=(
                "Le volume cumule les deux périodes ; la priorité porte sur la période courante."
                if any(cluster.period_metrics is not None for cluster in ordered)
                else "Signaux identifiés, avec leur volume, leur statut et leur priorité."
            ),
            legend=[
                VisualizationLegendItem(
                    label="Priorité",
                    description="Score calculé à partir du volume, de la sévérité et de l'évolution.",
                ),
                VisualizationLegendItem(
                    label="Confiance",
                    description="Cohérence sémantique et couverture des résumés du cluster.",
                ),
            ],
            empty_message=(
                "Aucun signal regroupé n'est disponible pour cette période."
                if not rows
                else None
            ),
        )


def _display_cluster_title(cluster: TemporaryFeedbackCluster) -> str:
    """Use an existing safe insight label, never a raw feedback comment."""

    return _normalize_text(cluster.title, fallback=cluster.temporary_id) or cluster.temporary_id


def build_visualization_specs(
    insights: FeedbackInsightsResult,
    audience_report: AudienceReport,
) -> list[VisualizationSpec]:
    """Convenience function for API handlers that only need renderer specs."""

    return FeedbackVisualizationBuilder.build_specs(insights, audience_report)
