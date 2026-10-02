import io
import json
import unittest
from contextlib import redirect_stderr
from types import SimpleNamespace
from unittest.mock import Mock, patch

from pydantic import ValidationError

from app import agents as agent_module
from app.knowledge import get_software_knowledge, load_software_catalog
from app.models import (
    FeedbackAnalysisResult,
    FeedbackInput,
    FunctionalityExtractionResult,
    FunctionalityReference,
    MAX_INPUT_LENGTH,
    SentimentAnalysisResult,
    SentimentLabel,
    SoftwareReference,
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


def expected_analysis_result() -> FeedbackAnalysisResult:
    return FeedbackAnalysisResult(
        software=SoftwareReference(id="dealym_crm", name="Dealym CRM"),
        sentiment=SentimentLabel.NEGATIVE,
        percentage=0.99,
        functionalities=[
            FunctionalityReference(
                id="opportunity_pipeline",
                name="Opportunity pipeline",
            )
        ],
    )


class FeedbackAnalysisTests(unittest.TestCase):
    def test_analyze_sentiment_uses_detected_language_and_returns_score(self) -> None:
        fake_client = FakeLanguageClient()

        with (
            patch.object(
                agent_module,
                "AZURE_AI_LANGUAGE_ENDPOINT",
                "https://language.test",
            ),
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
            patch.object(
                agent_module,
                "AZURE_AI_LANGUAGE_ENDPOINT",
                "https://language.test",
            ),
            patch.object(agent_module, "AZURE_AI_LANGUAGE_KEY", "test-key"),
            patch.object(agent_module, "TextAnalyticsClient", return_value=fake_client),
        ):
            result = agent_module.analyze_sentiment(
                "Le tableau de bord est excellent. L'export PDF echoue.",
                verbose=False,
            )

        self.assertEqual(result.sentiment, SentimentLabel.MIXED)
        self.assertEqual(result.percentage, 0.94)

    def test_input_schema_validates_feedback_and_software_id(self) -> None:
        with self.assertRaises(ValidationError):
            agent_module.analyze_sentiment("   ", verbose=False)

        with self.assertRaises(ValidationError):
            agent_module.analyze_sentiment("x" * (MAX_INPUT_LENGTH + 1), verbose=False)

        with self.assertRaises(ValidationError):
            FeedbackInput(software_id="   ", feedback="Valid feedback")

        request = FeedbackInput(
            software_id="  DEALYM_CRM  ",
            feedback="  Valid feedback  ",
        )
        self.assertEqual(request.software_id, "dealym_crm")
        self.assertEqual(request.feedback, "Valid feedback")

    def test_tool_schema_requires_software_id_and_feedback(self) -> None:
        catalog = load_software_catalog()
        tool = agent_module.build_feedback_analysis_tool(catalog)

        self.assertEqual(tool.name, "analyze_feedback")
        self.assertTrue(tool.strict)
        self.assertEqual(tool.parameters["required"], ["software_id", "feedback"])
        self.assertFalse(tool.parameters["additionalProperties"])
        self.assertEqual(
            tool.parameters["properties"]["software_id"]["enum"],
            [application.id for application in catalog.applications],
        )

    def test_create_registers_one_tool_and_compact_knowledge_context(self) -> None:
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
        self.assertEqual([tool.name for tool in definition.tools], ["analyze_feedback"])
        self.assertIn("targetym_ai", definition.instructions)
        self.assertIn("Dealym CRM", definition.instructions)
        self.assertNotIn("opportunity_pipeline", definition.instructions)
        self.assertNotIn("employee_records", definition.instructions)

    def test_extract_functionalities_uses_only_selected_software_catalog(self) -> None:
        extraction_response = SimpleNamespace(
            error=None,
            output_text='{"functionality_ids":["opportunity_pipeline"]}',
        )
        fake_openai = FakeOpenAI([extraction_response])
        software = get_software_knowledge("dealym_crm")

        result = agent_module.extract_functionalities(
            "Le pipeline commercial est inutilisable.",
            software=software,
            openai_client=fake_openai,
            model_deployment_name="functionality-model",
            verbose=False,
        )

        self.assertEqual(
            result.functionalities,
            [
                FunctionalityReference(
                    id="opportunity_pipeline",
                    name="Opportunity pipeline",
                )
            ],
        )
        request = fake_openai.responses.calls[0]
        schema = request["text"]["format"]["schema"]
        allowed_ids = schema["properties"]["functionality_ids"]["items"]["enum"]
        self.assertEqual(allowed_ids, [feature.id for feature in software.functionalities])
        self.assertNotIn("uniqueItems", schema["properties"]["functionality_ids"])
        self.assertNotIn("maxItems", schema["properties"]["functionality_ids"])
        self.assertEqual(request["model"], "functionality-model")
        self.assertEqual(request["temperature"], 0)
        self.assertTrue(request["text"]["format"]["strict"])
        self.assertIn("Dealym CRM", request["instructions"])
        self.assertIn("opportunity_pipeline", request["instructions"])
        self.assertNotIn("Targetym AI", request["instructions"])
        self.assertNotIn("employee_records", request["instructions"])
        self.assertNotIn("conversation", request)
        self.assertNotIn("extra_body", request)

    def test_extract_functionalities_rejects_a_foreign_catalog_identifier(self) -> None:
        extraction_response = SimpleNamespace(
            error=None,
            output_text='{"functionality_ids":["employee_records"]}',
        )
        fake_openai = FakeOpenAI([extraction_response])

        with self.assertRaisesRegex(RuntimeError, "unsupported identifier"):
            agent_module.extract_functionalities(
                "Le pipeline commercial est inutilisable.",
                software=get_software_knowledge("dealym_crm"),
                openai_client=fake_openai,
                model_deployment_name="functionality-model",
                verbose=False,
            )

    def test_analyze_feedback_resolves_software_and_functionality_references(self) -> None:
        fake_openai = SimpleNamespace()
        functionality_result = FunctionalityExtractionResult(
            functionalities=[
                FunctionalityReference(
                    id="opportunity_pipeline",
                    name="Opportunity pipeline",
                )
            ]
        )

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
                return_value=functionality_result,
            ) as extract_functionalities,
        ):
            result = agent_module.analyze_feedback(
                "  The sales pipeline is broken.  ",
                software_id="DEALYM_CRM",
                openai_client=fake_openai,
                model_deployment_name="functionality-model",
                verbose=False,
            )

        self.assertEqual(result, expected_analysis_result())
        analyze_sentiment.assert_called_once_with(
            "The sales pipeline is broken.", verbose=False
        )
        extract_functionalities.assert_called_once()
        extraction_call = extract_functionalities.call_args
        self.assertEqual(extraction_call.args, ("The sales pipeline is broken.",))
        self.assertEqual(extraction_call.kwargs["software"].id, "dealym_crm")
        self.assertEqual(extraction_call.kwargs["openai_client"], fake_openai)
        self.assertEqual(extraction_call.kwargs["model_deployment_name"], "functionality-model")

    def test_unknown_software_is_rejected_before_provider_calls(self) -> None:
        with patch.object(agent_module, "analyze_sentiment") as analyze_sentiment:
            with self.assertRaisesRegex(ValueError, "Unknown software_id"):
                agent_module.analyze_feedback(
                    "The feature is broken.",
                    software_id="unknown_product",
                    openai_client=SimpleNamespace(),
                    model_deployment_name="functionality-model",
                    verbose=False,
                )

        analyze_sentiment.assert_not_called()

    def test_tool_logs_a_safe_root_cause_but_returns_a_generic_error(self) -> None:
        feedback = "The customer feedback that must stay private."
        request = FeedbackInput(software_id="dealym_crm", feedback=feedback)
        function_call = SimpleNamespace(
            name="analyze_feedback",
            arguments=json.dumps(request.model_dump()),
        )
        agent = agent_module.FeedbackAnalyzerAgent(verbose=False)
        diagnostic_output = io.StringIO()

        with (
            patch.object(
                agent_module,
                "analyze_feedback",
                side_effect=RuntimeError(
                    f"Unauthorized while processing {feedback}; api_key=super-secret"
                ),
            ),
            redirect_stderr(diagnostic_output),
        ):
            output = agent._execute_tool(function_call, request=request)

        self.assertEqual(
            json.loads(output),
            {"error": "analyze_feedback could not be completed."},
        )
        diagnostic = diagnostic_output.getvalue()
        self.assertIn("[feedback-agent][ERROR][tool]", diagnostic)
        self.assertIn("event=tool_execution_failed", diagnostic)
        self.assertIn("Unauthorized", diagnostic)
        self.assertNotIn(feedback, diagnostic)
        self.assertNotIn("super-secret", diagnostic)

    def test_missing_language_configuration_logs_a_safe_diagnostic(self) -> None:
        feedback = "Private feedback text."
        diagnostic_output = io.StringIO()

        with (
            patch.object(agent_module, "AZURE_AI_LANGUAGE_ENDPOINT", None),
            patch.object(agent_module, "AZURE_AI_LANGUAGE_KEY", "language-secret"),
            redirect_stderr(diagnostic_output),
            self.assertRaisesRegex(RuntimeError, "must be configured"),
        ):
            agent_module.analyze_sentiment(feedback, verbose=False)

        diagnostic = diagnostic_output.getvalue()
        self.assertIn("event=language_configuration_failed", diagnostic)
        self.assertNotIn(feedback, diagnostic)
        self.assertNotIn("language-secret", diagnostic)

    def test_agent_executes_and_returns_one_validated_combined_tool_result(self) -> None:
        analysis_call = SimpleNamespace(
            type="function_call",
            name="analyze_feedback",
            arguments=json.dumps(
                {
                    "software_id": "dealym_crm",
                    "feedback": "The sales pipeline is broken.",
                }
            ),
            call_id="call-1",
        )
        first_response = SimpleNamespace(output=[analysis_call], output_text="")
        final_response = SimpleNamespace(output=[], output_text='{"ignored": true}')
        fake_openai = FakeOpenAI([first_response, final_response])
        agent = agent_module.FeedbackAnalyzerAgent(verbose=False)
        agent.agent = SimpleNamespace(
            name="feedback-analyzer-agent",
            version="1",
            id="agent-1",
        )
        agent.openai = fake_openai
        analysis_result = expected_analysis_result()

        with patch.object(
            agent_module,
            "analyze_feedback",
            return_value=analysis_result,
        ) as analyze_feedback:
            result = agent.run(
                "The sales pipeline is broken.",
                software_id="dealym_crm",
            )

        self.assertEqual(result, analysis_result.model_dump_json())
        analyze_feedback.assert_called_once_with(
            "The sales pipeline is broken.",
            software_id="dealym_crm",
            openai_client=fake_openai,
            model_deployment_name=agent_module.MODEL_DEPLOYMENT_NAME,
            verbose=False,
        )
        self.assertEqual(
            json.loads(fake_openai.responses.calls[0]["input"]),
            {
                "software_id": "dealym_crm",
                "feedback": "The sales pipeline is broken.",
            },
        )
        self.assertEqual(len(fake_openai.responses.calls), 2)
        tool_outputs = [
            json.loads(item["output"])
            for item in fake_openai.responses.calls[1]["input"]
        ]
        self.assertEqual(tool_outputs, [analysis_result.model_dump(mode="json")])
        self.assertEqual(
            fake_openai.responses.calls[0]["extra_body"]["agent_reference"]["id"],
            "agent-1",
        )
        self.assertEqual(fake_openai.conversations.deleted, ["conversation-1"])

    def test_agent_rejects_a_tool_call_that_changes_the_selected_software(self) -> None:
        agent = agent_module.FeedbackAnalyzerAgent(verbose=False)
        request = FeedbackInput(
            software_id="dealym_crm",
            feedback="The sales pipeline is broken.",
        )
        mismatched_call = SimpleNamespace(
            name="analyze_feedback",
            arguments=json.dumps(
                {
                    "software_id": "bleom_vie",
                    "feedback": "The sales pipeline is broken.",
                }
            ),
        )

        with patch.object(agent_module, "analyze_feedback") as analyze_feedback:
            output = agent._execute_tool(mismatched_call, request=request)

        self.assertEqual(
            json.loads(output),
            {
                "error": (
                    "Tool request did not preserve the caller-provided software "
                    "and feedback."
                )
            },
        )
        analyze_feedback.assert_not_called()
