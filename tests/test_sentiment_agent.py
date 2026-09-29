import os
import unittest

from pydantic import ValidationError

# The current application creates its Gemini settings while importing app.agent.
# Supply harmless test values so these unit tests never need a real API key.
os.environ.setdefault("GEMINI_API_KEY", "test-api-key")
os.environ.setdefault("GEMINI_MODEL_NAME", "test-model")

from app.agent import FeedbackAnalyserAgent
from app.models import MAX_INPUT_LENGTH, SentimentLabel, SentimentResult


class FakeSentimentAnalyzer:
    def __init__(self, result: SentimentResult) -> None:
        self.result = result
        self.calls: list[str] = []

    def classify(self, feedback: str) -> SentimentResult:
        self.calls.append(feedback)
        return self.result


class FeedbackAnalyserAgentTests(unittest.TestCase):
    def test_returns_provider_sentiment_and_trims_feedback(self) -> None:
        sentiment_analyzer = FakeSentimentAnalyzer(
            SentimentResult(sentiment=SentimentLabel.POSITIVE)
        )
        agent = FeedbackAnalyserAgent(sentiment_analyzer)

        result = agent.analyzeSentiment("  The dashboard saves me hours every week.  ")

        self.assertEqual(result.sentiment, SentimentLabel.POSITIVE)
        self.assertEqual(sentiment_analyzer.calls, ["The dashboard saves me hours every week."])

    def test_rejects_blank_feedback_before_provider_call(self) -> None:
        sentiment_analyzer = FakeSentimentAnalyzer(
            SentimentResult(sentiment=SentimentLabel.NEUTRAL)
        )
        agent = FeedbackAnalyserAgent(sentiment_analyzer)

        with self.assertRaises(ValidationError):
            agent.analyzeSentiment("   ")

        self.assertEqual(sentiment_analyzer.calls, [])

    def test_rejects_feedback_longer_than_configured_limit(self) -> None:
        sentiment_analyzer = FakeSentimentAnalyzer(
            SentimentResult(sentiment=SentimentLabel.NEUTRAL)
        )
        agent = FeedbackAnalyserAgent(sentiment_analyzer)

        with self.assertRaises(ValidationError):
            agent.analyzeSentiment("x" * (MAX_INPUT_LENGTH + 1))

        self.assertEqual(sentiment_analyzer.calls, [])
