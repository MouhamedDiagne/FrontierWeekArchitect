from enum import Enum
from pydantic import BaseModel, Field, field_validator

MAX_INPUT_LENGTH = 5000

class SentimentLabel(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    MIXED = "mixed"
    NEUTRAL = "neutral"

class SentimentAnalysisResult(BaseModel):
    sentiment: SentimentLabel
    percentage: float


class FunctionalityExtractionResult(BaseModel):
    """The concrete product capabilities found in one feedback message."""

    functionalities: list[str]


class FeedbackAnalysisResult(SentimentAnalysisResult):
    """The complete analysis returned by the combined feedback tool."""

    functionalities: list[str]

class FeedbackInput(BaseModel):
    feedback: str = Field(min_length=1, max_length=MAX_INPUT_LENGTH)

    @field_validator("feedback")
    @classmethod
    def validate_feedback(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("feedback must not be empty")
        return value

    
