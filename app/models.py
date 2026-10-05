from enum import Enum

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

MAX_INPUT_LENGTH = 4000
MAX_SOFTWARE_ID_LENGTH = 80
MAX_FEEDBACK_SUMMARY_LENGTH = 280

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

    
