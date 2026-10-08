from enum import Enum
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

MAX_INPUT_LENGTH = 4000
MAX_SOFTWARE_ID_LENGTH = 80
MAX_FEEDBACK_SUMMARY_LENGTH = 280
MAX_INSIGHT_FILTER_VALUE_LENGTH = 120
MAX_REPRESENTATIVE_EVIDENCE_LENGTH = 320
MAX_INSIGHT_METRIC_BREAKDOWN_ITEMS = 20

# Foundry strict structured output requires a scalar value for every required
# field. This sentinel is used only between the model response and local
# validation, then converted to None in the domain result.
NO_VALUE_SENTINEL = "__none__"

class SentimentLabel(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    MIXED = "mixed"
    NEUTRAL = "neutral"

class SentimentAnalysisResult(BaseModel):
    sentiment: SentimentLabel
    percentage: float = Field(ge=0.0, le=1.0)
    language: str = Field(min_length=2, max_length=10)


class SoftwareReference(BaseModel):
    """Canonical identity of the caller-selected software."""

    id: str
    name: str


class FunctionalityReference(BaseModel):
    """Canonical functionality identity for reporting and UI display."""

    id: str
    name: str


class FeedbackType(str, Enum):
    """Primary intent expressed by a customer-feedback message."""

    ISSUE_REPORT = "issue_report"
    FEATURE_REQUEST = "feature_request"
    IMPROVEMENT_SUGGESTION = "improvement_suggestion"
    INFORMATION_REQUEST = "information_request"
    POSITIVE_FEEDBACK = "positive_feedback"
    OTHER_FEEDBACK = "other_feedback"


class UserProfile(str, Enum):
    """Audience profile used only to tailor a historical-report presentation."""

    MARKETING = "marketing"
    IT = "it"
    SUPPORT_SALES = "support_sales"
    MANAGEMENT = "management"


class ProblemCategory(str, Enum):
    """Primary category for a concrete customer-reported problem."""

    BUG_ERROR = "bug_error"
    PERFORMANCE_SLOWDOWN = "performance_slowdown"
    AVAILABILITY_RELIABILITY = "availability_reliability"
    USABILITY_UX = "usability_ux"
    ACCESS_AUTHENTICATION = "access_authentication"
    DATA_QUALITY_REPORTING = "data_quality_reporting"
    BILLING_PAYMENT = "billing_payment"
    INTEGRATION = "integration"
    DOCUMENTATION_INFORMATION = "documentation_information"
    SUPPORT_EXPERIENCE = "support_experience"
    SECURITY_PRIVACY = "security_privacy"
    OTHER_PROBLEM = "other_problem"


def _validate_feedback_classification(
    *,
    feedback_type: FeedbackType,
    problem_category: ProblemCategory | None,
) -> None:
    """Enforce the relationship between intent and its problem category."""

    if feedback_type is FeedbackType.ISSUE_REPORT and problem_category is None:
        raise ValueError("issue_report requires a problem_category")

    non_problem_feedback_types = {
        FeedbackType.FEATURE_REQUEST,
        FeedbackType.INFORMATION_REQUEST,
        FeedbackType.POSITIVE_FEEDBACK,
        FeedbackType.OTHER_FEEDBACK,
    }
    if feedback_type in non_problem_feedback_types and problem_category is not None:
        raise ValueError(
            f"{feedback_type.value} must not include a problem_category"
        )


class FeedbackEnrichmentSelection(BaseModel):
    """Raw scalar structured response returned by the enrichment model."""

    model_config = ConfigDict(extra="forbid")

    primary_functionality_id: str = Field(min_length=1, max_length=80)
    feedback_type: FeedbackType
    problem_category: str = Field(min_length=1, max_length=80)
    feedback_summary: str = Field(
        min_length=1,
        max_length=MAX_FEEDBACK_SUMMARY_LENGTH,
    )

    @field_validator("primary_functionality_id", "problem_category")
    @classmethod
    def normalize_transport_value(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("structured-output values must not be blank")
        return normalized

    @field_validator("problem_category")
    @classmethod
    def validate_problem_category_transport_value(cls, value: str) -> str:
        if value == NO_VALUE_SENTINEL:
            return value

        try:
            return ProblemCategory(value).value
        except ValueError as error:
            raise ValueError("problem_category is not supported") from error

    @field_validator("feedback_summary")
    @classmethod
    def normalize_feedback_summary(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("feedback_summary must not be blank")
        return normalized

    @model_validator(mode="after")
    def validate_classification(self) -> "FeedbackEnrichmentSelection":
        category = (
            None
            if self.problem_category == NO_VALUE_SENTINEL
            else ProblemCategory(self.problem_category)
        )
        _validate_feedback_classification(
            feedback_type=self.feedback_type,
            problem_category=category,
        )
        return self


class FeedbackEnrichmentResult(BaseModel):
    """Validated classification and catalog-backed enrichment for one feedback."""

    model_config = ConfigDict(extra="forbid")

    feedback_type: FeedbackType
    feedback_summary: str = Field(
        min_length=1,
        max_length=MAX_FEEDBACK_SUMMARY_LENGTH,
    )
    primary_functionality: FunctionalityReference | None = None
    problem_category: ProblemCategory | None = None

    @field_validator("feedback_summary")
    @classmethod
    def normalize_feedback_summary(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("feedback_summary must not be blank")
        return normalized

    @model_validator(mode="after")
    def validate_classification(self) -> "FeedbackEnrichmentResult":
        _validate_feedback_classification(
            feedback_type=self.feedback_type,
            problem_category=self.problem_category,
        )
        return self



class FeedbackAnalysisResult(SentimentAnalysisResult):
    """The complete analysis returned by the combined feedback tool."""

    software: SoftwareReference
    feedback_type: FeedbackType
    feedback_summary: str = Field(
        min_length=1,
        max_length=MAX_FEEDBACK_SUMMARY_LENGTH,
    )
    primary_functionality: FunctionalityReference | None = None
    problem_category: ProblemCategory | None = None

    @field_validator("feedback_summary")
    @classmethod
    def normalize_feedback_summary(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("feedback_summary must not be blank")
        return normalized

    @model_validator(mode="after")
    def validate_classification(self) -> "FeedbackAnalysisResult":
        _validate_feedback_classification(
            feedback_type=self.feedback_type,
            problem_category=self.problem_category,
        )
        return self


class FeedbackText(BaseModel):
    """Validated customer-feedback text used by service-specific operations."""

    model_config = ConfigDict(extra="forbid")

    feedback: str = Field(min_length=1, max_length=MAX_INPUT_LENGTH)

    @field_validator("feedback")
    @classmethod
    def validate_feedback(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("feedback must not be empty")
        return value

class FeedbackInput(FeedbackText):
    """The authoritative caller input for one software-specific feedback analysis."""

    model_config = ConfigDict(extra="forbid")
    software_id: str = Field(min_length=1, max_length=MAX_SOFTWARE_ID_LENGTH)

    @field_validator("software_id")
    @classmethod
    def validate_software_id(cls, value: str) -> str:
        value = value.strip().lower()
        if not value:
            raise ValueError("software_id must not be empty")
        return value

class FeedbackInsightsFilters(BaseModel):
    """Validated, server-side filters for reading historical feedback."""

    model_config = ConfigDict(extra="forbid")

    start_date: datetime
    end_date: datetime
    software_id: str | None = Field(default=None, max_length=MAX_SOFTWARE_ID_LENGTH)
    functionality_id: str | None = Field(
        default=None,
        max_length=MAX_INSIGHT_FILTER_VALUE_LENGTH,
    )
    sentiment: SentimentLabel | None = None
    feedback_type: FeedbackType | None = None

    @field_validator("start_date", "end_date")
    @classmethod
    def normalize_insight_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("insight timestamps must include a timezone")
        return value.astimezone(timezone.utc)

    @field_validator("software_id", "functionality_id")
    @classmethod
    def normalize_optional_filter(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        return normalized or None

    @model_validator(mode="after")
    def validate_date_range(self) -> "FeedbackInsightsFilters":
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be later than start_date")
        return self


class FeedbackInsightsRequest(FeedbackInsightsFilters):
    """One current period, optionally compared with an earlier period."""

    audience_profile: UserProfile
    comparison_start_date: datetime | None = None
    comparison_end_date: datetime | None = None

    @field_validator("comparison_start_date", "comparison_end_date")
    @classmethod
    def normalize_comparison_timestamp(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("comparison timestamps must include a timezone")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_comparison_range(self) -> "FeedbackInsightsRequest":
        has_start = self.comparison_start_date is not None
        has_end = self.comparison_end_date is not None
        if has_start != has_end:
            raise ValueError(
                "comparison_start_date and comparison_end_date must be provided together"
            )
        if has_start and self.comparison_end_date <= self.comparison_start_date:
            raise ValueError(
                "comparison_end_date must be later than comparison_start_date"
            )
        if has_start and not (
            self.comparison_end_date <= self.start_date
            or self.comparison_start_date >= self.end_date
        ):
            raise ValueError("comparison and current periods must not overlap")
        return self

    def current_filters(self) -> "FeedbackInsightsFilters":
        return FeedbackInsightsFilters(
            start_date=self.start_date,
            end_date=self.end_date,
            software_id=self.software_id,
            functionality_id=self.functionality_id,
            sentiment=self.sentiment,
            feedback_type=self.feedback_type,
        )

    def comparison_filters(self) -> "FeedbackInsightsFilters | None":
        if self.comparison_start_date is None or self.comparison_end_date is None:
            return None
        return FeedbackInsightsFilters(
            start_date=self.comparison_start_date,
            end_date=self.comparison_end_date,
            software_id=self.software_id,
            functionality_id=self.functionality_id,
            sentiment=self.sentiment,
            feedback_type=self.feedback_type,
        )

class FeedbackRecordForInsights(BaseModel):
    """Minimal, normalized feedback data used only for temporary insights."""

    model_config = ConfigDict(extra="forbid")

    feedback_id: str = Field(min_length=1, max_length=160)
    received_at: datetime
    software_id: str = Field(min_length=1, max_length=MAX_SOFTWARE_ID_LENGTH)
    feedback_summary: str | None = Field(default=None, max_length=MAX_FEEDBACK_SUMMARY_LENGTH)
    raw_comment: str | None = Field(default=None, max_length=MAX_INPUT_LENGTH)
    sentiment: SentimentLabel | None = None
    feedback_type: FeedbackType | None = None
    problem_category: ProblemCategory | None = None
    primary_functionality: str | None = Field(
        default=None,
        max_length=MAX_INSIGHT_FILTER_VALUE_LENGTH,
    )
    primary_functionality_name: str | None = Field(
        default=None,
        max_length=MAX_INSIGHT_FILTER_VALUE_LENGTH,
    )
    client_id: str | None = None
    segment: str | None = None

    @field_validator("received_at")
    @classmethod
    def normalize_received_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("received_at must include a timezone")
        return value.astimezone(timezone.utc)

    @field_validator(
        "feedback_summary",
        "raw_comment",
        "primary_functionality",
        "primary_functionality_name",
        "client_id",
        "segment",
        mode="before",
    )
    @classmethod
    def blank_values_are_none(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = " ".join(value.split())
            return normalized or None
        return value

class ConversationMessage(BaseModel):
    """A validated free-form message sent during a conversation."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=MAX_INPUT_LENGTH)

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message must not be empty")
        return value


class ConversationTurnResult(BaseModel):
    """The user-facing and machine-readable outcome of one chat turn."""

    reply: str
    analysis: FeedbackAnalysisResult | None = None
    feedback_record_id: str | None = None
    insights: "FeedbackInsightsResult | None" = None
    audience_report: "AudienceReport | None" = None
    insight_snapshot_id: str | None = None
    # Produced only by deterministic application code after an insight run.
    # It is intentionally transport-shaped here to avoid a circular dependency
    # on app.visualizations, which itself validates domain insight models.
    visualizations: dict[str, Any] | None = None


class FeedbackSubmissionResult(BaseModel):
    """A feedback analysis that was successfully persisted outside a chat turn.

    This intentionally contains no raw feedback text.  It is used by the
    local ingestion HTTP endpoint and lets a future form connector receive the
    same validated analysis contract as the conversational path.
    """

    model_config = ConfigDict(extra="forbid")

    analysis: FeedbackAnalysisResult
    feedback_record_id: str = Field(min_length=1)

class RepresentativeEvidenceSource(str, Enum):
    """Origin of a bounded cluster evidence excerpt.

    ``raw_fallback`` is never an unrestricted customer comment: it is only a
    short, locally-redacted excerpt used when no usable enriched summary is
    available for that feedback.  Keeping the provenance explicit lets the
    reporting model and the UI avoid presenting it as a model-generated
    summary.
    """

    SUMMARY = "summary"
    RAW_FALLBACK = "raw_fallback"


class ClusterExample(BaseModel):
    """A privacy-bounded representative item supporting one cluster.

    The canonical transport field is ``evidence_text``.  ``feedback_summary``
    remains an input-only compatibility alias so historical POC snapshots can
    still be read.  Raw comments are never represented as a field here.
    """

    model_config = ConfigDict(extra="forbid")

    feedback_id: str = Field(min_length=1, max_length=160)
    evidence_text: str = Field(
        min_length=1,
        max_length=MAX_REPRESENTATIVE_EVIDENCE_LENGTH,
        validation_alias=AliasChoices("evidence_text", "feedback_summary"),
    )
    source: RepresentativeEvidenceSource = RepresentativeEvidenceSource.SUMMARY
    received_at: datetime
    similarity_to_representative: float | None = Field(default=None, ge=-1, le=1)

    @field_validator("evidence_text")
    @classmethod
    def normalize_evidence_text(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("evidence_text must not be blank")
        return normalized

    @field_validator("received_at")
    @classmethod
    def normalize_received_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("received_at must include a timezone")
        return value.astimezone(timezone.utc)

    @property
    def feedback_summary(self) -> str:
        """Compatibility accessor for older internal callers.

        New code must use ``evidence_text`` and inspect ``source`` before
        quoting an item in a report.
        """

        return self.evidence_text


class ClusterPriority(BaseModel):
    """Transparent components of a cluster priority score."""

    model_config = ConfigDict(extra="forbid")

    score: float = Field(ge=0)
    volume: float = Field(ge=0)
    severity: float = Field(ge=0)
    trend: float = Field(ge=0)
    segment_weight: float = Field(ge=0)


class ClusterPeriodMetrics(BaseModel):
    """Counts for one cluster across the requested current/previous periods."""

    model_config = ConfigDict(extra="forbid")

    current_count: int = Field(ge=0)
    previous_count: int = Field(ge=0)
    absolute_change: int
    relative_change: float | None
    trend: Literal["new", "up", "stable", "down"]

class TemporaryFeedbackCluster(BaseModel):
    """An on-demand cluster; it is never persisted back to Dataverse."""

    model_config = ConfigDict(extra="forbid")

    temporary_id: str
    title: str
    description: str
    status: Literal["clustered", "singleton", "needs_review"]
    software_id: str
    feedback_type: FeedbackType | None
    dominant_problem_category: ProblemCategory | None
    feedback_ids: list[str]
    member_count: int = Field(ge=1)
    unique_client_count: int | None
    functionality_breakdown: dict[str, int]
    problem_category_breakdown: dict[str, int]
    sentiment_distribution: dict[str, int]
    first_occurrence: datetime
    last_occurrence: datetime
    representative_examples: list[ClusterExample]
    average_similarity: float | None
    confidence: float = Field(ge=0, le=1)
    priority: ClusterPriority
    period_metrics: ClusterPeriodMetrics | None = None


class FeedbackInsightsDataQuality(BaseModel):
    """Input-quality facts surfaced to the reporting agent and the user."""

    model_config = ConfigDict(extra="forbid")

    records_with_summary: int = Field(ge=0)
    records_using_raw_fallback: int = Field(ge=0)
    records_without_usable_representation: int = Field(ge=0)


class InsightPeriodMetrics(BaseModel):
    """Safe aggregate facts for one requested reporting period.

    These values are calculated directly from feedback records but contain no
    identifiers, raw comments, or summaries.  The functionality map is a
    bounded top list, which prevents a reporting payload from becoming a copy
    of the underlying database.
    """

    model_config = ConfigDict(extra="forbid")

    feedback_count: int = Field(ge=0)
    sentiment_distribution: dict[str, int] = Field(default_factory=dict)
    feedback_type_distribution: dict[str, int] = Field(default_factory=dict)
    problem_category_distribution: dict[str, int] = Field(default_factory=dict)
    top_functionality_distribution: dict[str, int] = Field(default_factory=dict)

    @field_validator(
        "sentiment_distribution",
        "feedback_type_distribution",
        "problem_category_distribution",
        "top_functionality_distribution",
    )
    @classmethod
    def validate_metric_distribution(cls, value: dict[str, int]) -> dict[str, int]:
        if len(value) > MAX_INSIGHT_METRIC_BREAKDOWN_ITEMS:
            raise ValueError("metric distributions must remain bounded")
        normalized: dict[str, int] = {}
        for label, count in value.items():
            clean_label = " ".join(str(label).split())[:MAX_INSIGHT_FILTER_VALUE_LENGTH]
            if not clean_label:
                raise ValueError("metric distribution labels must not be blank")
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                raise ValueError("metric distribution values must be non-negative integers")
            normalized[clean_label] = count
        return normalized


class FeedbackInsightsMetrics(BaseModel):
    """Aggregate metrics for the current period and optional comparison."""

    model_config = ConfigDict(extra="forbid")

    current: InsightPeriodMetrics
    comparison: InsightPeriodMetrics | None = None


class FeedbackInsightsResult(BaseModel):
    """Structured, read-only result used by the conversational reporting agent."""

    model_config = ConfigDict(extra="forbid")

    request: FeedbackInsightsRequest
    total_feedbacks: int = Field(ge=0)
    clustered_feedbacks: int = Field(ge=0)
    clusters: list[TemporaryFeedbackCluster]
    data_quality: FeedbackInsightsDataQuality
    # Optional only to keep snapshots created before aggregate metrics
    # backwards-readable during the POC migration.
    metrics: FeedbackInsightsMetrics | None = None
    limitations: list[str]


class AudienceReportScope(BaseModel):
    """Deterministic scope facts displayed by a profile-specific report."""

    model_config = ConfigDict(extra="forbid")

    period: str
    software_id: str | None
    functionality_id: str | None
    comparison_period: str | None = None


class AudienceReport(BaseModel):
    """Profile-specific selection guidance; it never changes insight facts."""

    model_config = ConfigDict(extra="forbid")

    profile: UserProfile
    scope: AudienceReportScope
    executive_focus: str
    priority_signal_ids: list[str]
    positive_signal_ids: list[str]
    watch_list_ids: list[str]
    suggested_follow_up_types: list[str]
    limitations: list[str]


class FeedbackInsightsToolResult(BaseModel):
    """Complete tool result: validated analytical evidence plus audience guidance."""

    model_config = ConfigDict(extra="forbid")

    insights: FeedbackInsightsResult
    audience_report: AudienceReport


class InsightRunSource(str, Enum):
    """Origin of a persisted historical-analysis snapshot."""

    CONVERSATION = "conversation"
    MANUAL = "manual"
    SCHEDULED = "scheduled"


class FeedbackInsightsSnapshot(BaseModel):
    """Immutable POC snapshot of clustering evidence and audience guidance."""

    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    source: InsightRunSource
    insights: FeedbackInsightsResult
    audience_report: AudienceReport

    @field_validator("generated_at")
    @classmethod
    def normalize_generated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at must include a timezone")
        return value.astimezone(timezone.utc)


class InsightsAnalysisRunResult(FeedbackInsightsToolResult):
    """Historical analysis returned outside a chat tool call."""

    insight_snapshot_id: str | None = None
