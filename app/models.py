from enum import Enum
from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_INPUT_LENGTH = 4000
MAX_SOFTWARE_ID_LENGTH = 80

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


class FunctionalitySelection(BaseModel):
    """Internal structured response returned by the functionality model."""

    model_config = ConfigDict(extra="forbid")
    functionality_ids: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("functionality_ids")
    @classmethod
    def require_unique_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("functionality_ids must not contain duplicates")
        return value


class FunctionalityExtractionResult(BaseModel):
    """Resolved, catalog-backed product capabilities found in one feedback message."""

    functionalities: list[FunctionalityReference] = Field(default_factory=list)


class FeedbackAnalysisResult(SentimentAnalysisResult):
    """The complete analysis returned by the combined feedback tool."""

    software: SoftwareReference
    functionalities: list[FunctionalityReference] = Field(default_factory=list)


class FeedbackText(BaseModel):
    """Validated customer-feedback text used by service-specific operations."""

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

    
