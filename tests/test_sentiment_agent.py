import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from pydantic import ValidationError

from app import agent as agent_module
from app.models import (
    FeedbackAnalysisResult,
    FunctionalityExtractionResult,
    MAX_INPUT_LENGTH,
    SentimentAnalysisResult,
    SentimentLabel,
)


class FakeLanguageClient:
    def __init__(
        self,
        *,
        sentiment: str = "negative",
        positive: float = 0.01,
        neutral: float = 0.02,
        negative: float = 0.97,
    ) -> None:
        self.detect_calls = []
        self.sentiment_calls = []
        self.sentiment = sentiment
        self.scores = SimpleNamespace(
            positive=positive,
            neutral=neutral,
            negative=negative,
        )

    def detect_language(self, documents, **kwargs):
        self.detect_calls.append((documents, kwargs))
        return [
            SimpleNamespace(
                is_error=False,
                primary_language=SimpleNamespace(iso6391_name="fr"),
            )
        ]

    def analyze_sentiment(self, documents, **kwargs):
        self.sentiment_calls.append((documents, kwargs))
        return [
            SimpleNamespace(
                is_error=False,
                sentiment=self.sentiment,
                confidence_scores=self.scores,
            )
        ]


class FakeConversations:
    def __init__(self) -> None:
        self.deleted = []

    def create(self):
        return SimpleNamespace(id="conversation-1")

    def delete(self, conversation_id):
        self.deleted.append(conversation_id)


class FakeResponses:
    def __init__(self, responses) -> None:
        self._responses = iter(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return next(self._responses)


class FakeOpenAI:
    def __init__(self, responses) -> None:
        self.conversations = FakeConversations()
        self.responses = FakeResponses(responses)


class SentimentToolTests(unittest.TestCase):
    def test_analyze_sentiment_uses_detected_language_and_returns_score(self) -> None:
        fake_client = FakeLanguageClient()

        with (
            patch.object(agent_module, "AZURE_AI_LANGUAGE_ENDPOINT", "https://language.test"),
            patch.object(agent_module, "AZURE_AI_LANGUAGE_KEY", "test-key"),
            patch.object(agent_module, "TextAnalyticsClient", return_value=fake_client),
        ):
            result = agent_module.analyze_sentiment(
                "  Le portail ne fonctionne pas.  ", verbose=False
            )

        self.assertEqual(result.sentiment, SentimentLabel.NEGATIVE)
        self.assertEqual(result.percentage, 0.97)
        self.assertEqual(fake_client.detect_calls[0][0], ["Le portail ne fonctionne pas."])
        self.assertEqual(fake_client.sentiment_calls[0][1]["language"], "fr")
        self.assertTrue(fake_client.sentiment_calls[0][1]["disable_service_logs"])

    def test_analyze_sentiment_calculates_a_balance_score_for_mixed(self) -> None:
        fake_client = FakeLanguageClient(
            sentiment="mixed",
            positive=0.47,
            neutral=0.01,
            negative=0.52,
        )

        with (
            patch.object(agent_module, "AZURE_AI_LANGUAGE_ENDPOINT", "https://language.test"),
            patch.object(agent_module, "AZURE_AI_LANGUAGE_KEY", "test-key"),
            patch.object(agent_module, "TextAnalyticsClient", return_value=fake_client),
        ):
            result = agent_module.analyze_sentiment(
                "Le tableau de bord est excellent. L'export PDF echoue.",
                verbose=False,
            )

        self.assertEqual(result.sentiment, SentimentLabel.MIXED)
        self.assertEqual(result.percentage, 0.94)

    def test_analyze_sentiment_validates_feedback_before_calling_language_service(self) -> None:
        with self.assertRaises(ValidationError):
            agent_module.analyze_sentiment("   ", verbose=False)

        with self.assertRaises(ValidationError):
            agent_module.analyze_sentiment("x" * (MAX_INPUT_LENGTH + 1), verbose=False)

    def test_combined_tool_schema_requires_a_single_feedback_string(self) -> None:
        tool = agent_module.FEEDBACK_ANALYSIS_TOOL

        self.assertEqual(tool.name, "analyze_feedback")
        self.assertTrue(tool.strict)
        self.assertEqual(tool.parameters["required"], ["feedback"])
        self.assertFalse(tool.parameters["additionalProperties"])

    def test_create_registers_the_combined_tool_on_the_agent(self) -> None:
        fake_client = SimpleNamespace(
            agents=SimpleNamespace(
                create_version=Mock(
                    return_value=SimpleNamespace(
                        name="feedback-analyzer-agent",
                        version="1",
                    )
                )
            ),
            get_openai_client=Mock(return_value=SimpleNamespace()),
        )

        with patch.object(agent_module, "AIProjectClient", return_value=fake_client):
            agent = agent_module.FeedbackAnalyzerAgent(verbose=False)
            agent.create()

        definition = fake_client.agents.create_version.call_args.kwargs["definition"]
        self.assertEqual(
            [tool.name for tool in definition.tools],
            ["analyze_feedback"],
        )
        self.assertIn("analyze_feedback", definition.instructions)

    def test_extract_functionalities_uses_injected_model_with_a_strict_schema(self) -> None:
        extraction_response = SimpleNamespace(
            error=None,
            output_text='{"functionalities":["authentication","PDF export"]}',
        )
        fake_openai = FakeOpenAI([extraction_response])

        result = agent_module.extract_functionalities(
            "Je ne peux plus me connecter et l'export PDF echoue.",
            openai_client=fake_openai,
            model_deployment_name="functionality-model",
            verbose=False,
        )

        self.assertEqual(result.functionalities, ["authentication", "PDF export"])
        request = fake_openai.responses.calls[0]
        self.assertEqual(request["model"], "functionality-model")
        self.assertEqual(request["temperature"], 0)
        self.assertEqual(request["text"]["format"]["type"], "json_schema")
        self.assertTrue(request["text"]["format"]["strict"])
        self.assertNotIn("conversation", request)
        self.assertNotIn("extra_body", request)

    def test_analyze_feedback_combines_the_two_module_level_analyses(self) -> None:
        fake_openai = SimpleNamespace()

        with (
            patch.object(
                agent_module,
                "analyze_sentiment",
                return_value=SentimentAnalysisResult(
                    sentiment=SentimentLabel.NEGATIVE,
                    percentage=0.99,
                ),
            ) as analyze_sentiment,
            patch.object(
                agent_module,
                "extract_functionalities",
                return_value=FunctionalityExtractionResult(
                    functionalities=["billing"],
                ),
            ) as extract_functionalities,
        ):
            result = agent_module.analyze_feedback(
                "  The billing page is broken.  ",
                openai_client=fake_openai,
                model_deployment_name="functionality-model",
                verbose=False,
            )

        self.assertEqual(
            result,
            FeedbackAnalysisResult(
                sentiment=SentimentLabel.NEGATIVE,
                percentage=0.99,
                functionalities=["billing"],
            ),
        )
        analyze_sentiment.assert_called_once_with(
            "The billing page is broken.", verbose=False
        )
        extract_functionalities.assert_called_once_with(
            "The billing page is broken.",
            openai_client=fake_openai,
            model_deployment_name="functionality-model",
            verbose=False,
        )

    def test_agent_executes_and_returns_one_combined_tool_result(self) -> None:
        analysis_call = SimpleNamespace(
            type="function_call",
            name="analyze_feedback",
            arguments=json.dumps({"feedback": "The billing page is broken."}),
            call_id="call-1",
        )
        first_response = SimpleNamespace(
            output=[analysis_call],
            output_text="",
        )
        final_response = SimpleNamespace(
            output=[],
            output_text=(
                '{"sentiment":"negative","percentage":0.99,'
                '"functionalities":["billing"]}'
            ),
        )
        fake_openai = FakeOpenAI([first_response, final_response])
        agent = agent_module.FeedbackAnalyzerAgent(verbose=False)
        agent.agent = SimpleNamespace(
            name="feedback-analyzer-agent",
            version="1",
            id="agent-1",
        )
        agent.openai = fake_openai

        with patch.object(
            agent_module,
            "analyze_feedback",
            return_value=FeedbackAnalysisResult(
                sentiment=SentimentLabel.NEGATIVE,
                percentage=0.99,
                functionalities=["billing"],
            ),
        ) as analyze_feedback:
            result = agent.run("Analyze this customer feedback.")

        self.assertEqual(result, final_response.output_text)
        analyze_feedback.assert_called_once_with(
            "The billing page is broken.",
            openai_client=fake_openai,
            model_deployment_name=agent_module.MODEL_DEPLOYMENT_NAME,
            verbose=False,
        )
        self.assertEqual(len(fake_openai.responses.calls), 2)
        tool_outputs = [
            json.loads(item["output"])
            for item in fake_openai.responses.calls[1]["input"]
        ]
        self.assertEqual(
            tool_outputs,
            [
                {
                    "sentiment": "negative",
                    "percentage": 0.99,
                    "functionalities": ["billing"],
                }
            ],
        )
        self.assertEqual(
            fake_openai.responses.calls[0]["extra_body"]["agent_reference"]["id"],
            "agent-1",
        )
        self.assertEqual(fake_openai.conversations.deleted, ["conversation-1"])
