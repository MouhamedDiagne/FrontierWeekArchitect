import io
import json
import unittest
from contextlib import redirect_stderr
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from pydantic import ValidationError

from app import agents as agent_module
from app import dataverse as dataverse_module
from app import tools as tools_module
from app.models import (
    FeedbackAnalysisResult,
    FeedbackEnrichmentResult,
    FeedbackEnrichmentSelection,
    FeedbackInput,
    FeedbackType,
    FunctionalityReference,
    MAX_FEEDBACK_SUMMARY_LENGTH,
    MAX_INPUT_LENGTH,
    NO_VALUE_SENTINEL,
    ProblemCategory,
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
        self.created = []
        self.deleted = []

    def create(self):
        conversation_id = f"conversation-{len(self.created) + 1}"
        self.created.append(conversation_id)
        return SimpleNamespace(id=conversation_id)

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


class FakeFeedbackRepository:
    def __init__(self) -> None:
        self.calls = []

    def save(
        self,
        *,
        raw_comment,
        analysis,
        received_at,
        analyzed_at,
    ) -> str:
        self.calls.append(
            {
                "raw_comment": raw_comment,
                "analysis": analysis,
                "received_at": received_at,
                "analyzed_at": analyzed_at,
            }
        )
        return f"record-{len(self.calls)}"


class FakeDataverseClient:
    def __init__(self, record_id: str = "dataverse-record-1") -> None:
        self.records = SimpleNamespace(create=Mock(return_value=record_id))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None


def expected_analysis_result() -> FeedbackAnalysisResult:
    return FeedbackAnalysisResult(
        software=SoftwareReference(id="dealym_crm", name="Dealym CRM"),
        sentiment=SentimentLabel.NEGATIVE,
        percentage=0.99,
        language="en",
        primary_functionality=FunctionalityReference(
            id="opportunity_pipeline",
            name="Opportunity pipeline",
        ),
        feedback_type=FeedbackType.ISSUE_REPORT,
        problem_category=ProblemCategory.BUG_ERROR,
        feedback_summary="The sales pipeline is broken.",
    )


def make_ready_agent(responses):
    repository = FakeFeedbackRepository()
    agent = agent_module.FeedbackAnalyzerAgent(
        verbose=False,
        feedback_repository=repository,
    )
    agent.client = SimpleNamespace()
    agent.agent = SimpleNamespace(
        name="feedback-analyzer-agent",
        version="1",
        id="agent-1",
    )
    agent.openai = FakeOpenAI(responses)
    return agent, repository


class FeedbackAnalysisTests(unittest.TestCase):
    def test_analyze_sentiment_uses_detected_language_and_returns_score(self) -> None:
        fake_client = FakeLanguageClient()

        with (
            patch.object(
                tools_module,
                "AZURE_AI_LANGUAGE_ENDPOINT",
                "https://language.test",
            ),
            patch.object(tools_module, "AZURE_AI_LANGUAGE_KEY", "test-key"),
            patch.object(
                tools_module,
                "TextAnalyticsClient",
                return_value=fake_client,
            ),
        ):
            result = tools_module.analyze_sentiment(
                "  Le portail ne fonctionne pas.  ",
                verbose=False,
            )

        self.assertEqual(result.sentiment, SentimentLabel.NEGATIVE)
        self.assertEqual(result.percentage, 0.97)
        self.assertEqual(result.language, "fr")
        self.assertEqual(
            fake_client.detect_calls[0][0],
            ["Le portail ne fonctionne pas."],
        )
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
                tools_module,
                "AZURE_AI_LANGUAGE_ENDPOINT",
                "https://language.test",
            ),
            patch.object(tools_module, "AZURE_AI_LANGUAGE_KEY", "test-key"),
            patch.object(
                tools_module,
                "TextAnalyticsClient",
                return_value=fake_client,
            ),
        ):
            result = tools_module.analyze_sentiment(
                "Le tableau de bord est excellent. L'export PDF echoue.",
                verbose=False,
            )

        self.assertEqual(result.sentiment, SentimentLabel.MIXED)
        self.assertEqual(result.percentage, 0.94)

    def test_input_schema_validates_feedback_and_software_id(self) -> None:
        with self.assertRaises(ValidationError):
            tools_module.analyze_sentiment("   ", verbose=False)

        with self.assertRaises(ValidationError):
            tools_module.analyze_sentiment("x" * (MAX_INPUT_LENGTH + 1), verbose=False)

        with self.assertRaises(ValidationError):
            FeedbackInput(software_id="   ", feedback="Valid feedback")

        request = FeedbackInput(
            software_id="  DEALYM_CRM  ",
            feedback="  Valid feedback  ",
        )
        self.assertEqual(request.software_id, "dealym_crm")
        self.assertEqual(request.feedback, "Valid feedback")

    def test_tool_schema_requires_software_id_and_feedback(self) -> None:
        tool = tools_module.build_feedback_analysis_tool()

        self.assertEqual(tool.name, "analyze_feedback")
        self.assertTrue(tool.strict)
        self.assertEqual(tool.parameters["required"], ["software_id", "feedback"])
        self.assertFalse(tool.parameters["additionalProperties"])

    def test_create_registers_one_user_triggered_tool(self) -> None:
        repository = FakeFeedbackRepository()
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

        with (
            patch.object(agent_module, "PROJECT_CONNECTION_STRING", "https://test"),
            patch.object(agent_module, "AIProjectClient", return_value=fake_client),
        ):
            agent = agent_module.FeedbackAnalyzerAgent(
                verbose=False,
                feedback_repository=repository,
            )
            agent.create()

        definition = fake_client.agents.create_version.call_args.kwargs["definition"]
        self.assertEqual(
            [tool.name for tool in definition.tools],
            ["analyze_feedback", "analyze_feedback_insights"],
        )
        self.assertIn("Do not begin by asking which software", definition.instructions)
        self.assertIn("Use analyze_feedback only when the user explicitly asks", definition.instructions)
        self.assertIn("primary\nfunctionality", definition.instructions)
        self.assertIn("feedback type", definition.instructions)
        self.assertIn("analyze_feedback_insights", definition.instructions)
        self.assertIn("problem category", definition.instructions)
        self.assertIn("feedback summary", definition.instructions)
        self.assertIn("targetym_ai", definition.instructions)
        self.assertIn("Dealym CRM", definition.instructions)
        self.assertNotIn("opportunity_pipeline", definition.instructions)

    def test_extract_feedback_enrichment_uses_only_selected_software_catalog(self) -> None:
        extraction_response = SimpleNamespace(
            error=None,
            output_text=(
                '{"primary_functionality_id":"opportunity_pipeline",'
                '"feedback_type":"issue_report",'
                '"problem_category":"bug_error",'
                '"feedback_summary":"Le pipeline commercial ne fonctionne pas."}'
            ),
        )
        fake_openai = FakeOpenAI([extraction_response])
        software = tools_module.get_software_knowledge("dealym_crm")

        result = tools_module.extract_feedback_enrichment(
            "Le pipeline commercial est inutilisable.",
            software=software,
            openai_client=fake_openai,
            model_deployment_name="enrichment-model",
            verbose=False,
        )

        self.assertEqual(
            result.primary_functionality,
            FunctionalityReference(
                id="opportunity_pipeline",
                name="Opportunity pipeline",
            ),
        )
        self.assertEqual(result.feedback_type, FeedbackType.ISSUE_REPORT)
        self.assertEqual(result.problem_category, ProblemCategory.BUG_ERROR)
        self.assertEqual(
            result.feedback_summary,
            "Le pipeline commercial ne fonctionne pas.",
        )
        request = fake_openai.responses.calls[0]
        self.assertIn(
            "direct, clear, self-contained reformulation",
            request["instructions"],
        )
        schema = request["text"]["format"]["schema"]
        allowed_ids = schema["properties"]["primary_functionality_id"]["enum"]
        self.assertEqual(
            allowed_ids,
            [NO_VALUE_SENTINEL, *[feature.id for feature in software.functionalities]],
        )
        self.assertEqual(
            schema["properties"]["feedback_type"]["enum"],
            [item.value for item in FeedbackType],
        )
        self.assertEqual(
            schema["properties"]["problem_category"]["enum"],
            [
                NO_VALUE_SENTINEL,
                *[item.value for item in ProblemCategory],
            ],
        )
        self.assertEqual(
            schema["required"],
            [
                "primary_functionality_id",
                "feedback_type",
                "problem_category",
                "feedback_summary",
            ],
        )
        self.assertNotIn("uniqueItems", schema)
        self.assertNotIn("maxItems", schema)
        self.assertEqual(request["model"], "enrichment-model")
        self.assertEqual(request["temperature"], 0)
        self.assertTrue(request["text"]["format"]["strict"])
        self.assertIn("Dealym CRM", request["instructions"])
        self.assertNotIn("Targetym AI", request["instructions"])

    def test_extract_feedback_enrichment_rejects_a_foreign_catalog_identifier(self) -> None:
        extraction_response = SimpleNamespace(
            error=None,
            output_text=(
                '{"primary_functionality_id":"employee_records",'
                '"feedback_type":"issue_report",'
                '"problem_category":"bug_error",'
                '"feedback_summary":"Le pipeline commercial ne fonctionne pas."}'
            ),
        )

        with self.assertRaisesRegex(RuntimeError, "unsupported functionality identifier"):
            tools_module.extract_feedback_enrichment(
                "Le pipeline commercial est inutilisable.",
                software=tools_module.get_software_knowledge("dealym_crm"),
                openai_client=FakeOpenAI([extraction_response]),
                model_deployment_name="enrichment-model",
                verbose=False,
            )

    def test_extract_feedback_enrichment_converts_no_value_sentinel_to_none(self) -> None:
        extraction_response = SimpleNamespace(
            error=None,
            output_text=(
                f'{{"primary_functionality_id":"{NO_VALUE_SENTINEL}",'
                '"feedback_type":"positive_feedback",'
                f'"problem_category":"{NO_VALUE_SENTINEL}",'
                '"feedback_summary":"Le logiciel est très agréable à utiliser."}'
            ),
        )

        result = tools_module.extract_feedback_enrichment(
            "Le logiciel est très agréable à utiliser.",
            software=tools_module.get_software_knowledge("dealym_crm"),
            openai_client=FakeOpenAI([extraction_response]),
            model_deployment_name="enrichment-model",
            verbose=False,
        )

        self.assertIsNone(result.primary_functionality)
        self.assertIsNone(result.problem_category)
        self.assertEqual(result.feedback_type, FeedbackType.POSITIVE_FEEDBACK)

    def test_feedback_enrichment_validates_category_and_summary(self) -> None:
        with self.assertRaises(ValidationError):
            FeedbackEnrichmentSelection(
                primary_functionality_id=NO_VALUE_SENTINEL,
                feedback_type=FeedbackType.ISSUE_REPORT,
                problem_category=NO_VALUE_SENTINEL,
                feedback_summary="A concrete issue was reported.",
            )

        with self.assertRaises(ValidationError):
            FeedbackEnrichmentResult(
                feedback_type=FeedbackType.POSITIVE_FEEDBACK,
                problem_category=ProblemCategory.BUG_ERROR,
                feedback_summary="Great product.",
            )

        with self.assertRaises(ValidationError):
            FeedbackEnrichmentResult(
                feedback_type=FeedbackType.POSITIVE_FEEDBACK,
                feedback_summary="x" * (MAX_FEEDBACK_SUMMARY_LENGTH + 1),
            )

    def test_analyze_feedback_resolves_software_and_enrichment_references(self) -> None:
        enrichment_result = FeedbackEnrichmentResult(
            primary_functionality=FunctionalityReference(
                id="opportunity_pipeline",
                name="Opportunity pipeline",
            ),
            feedback_type=FeedbackType.ISSUE_REPORT,
            problem_category=ProblemCategory.BUG_ERROR,
            feedback_summary="The sales pipeline is broken.",
        )

        with (
            patch.object(
                tools_module,
                "analyze_sentiment",
                return_value=SentimentAnalysisResult(
                    sentiment=SentimentLabel.NEGATIVE,
                    percentage=0.99,
                    language="en",
                ),
            ) as analyze_sentiment,
            patch.object(
                tools_module,
                "extract_feedback_enrichment",
                return_value=enrichment_result,
            ) as extract_feedback_enrichment,
        ):
            result = tools_module.analyze_feedback(
                "  The sales pipeline is broken.  ",
                software_id="DEALYM_CRM",
                openai_client=SimpleNamespace(),
                model_deployment_name="functionality-model",
                verbose=False,
            )

        self.assertEqual(result, expected_analysis_result())
        analyze_sentiment.assert_called_once_with(
            "The sales pipeline is broken.",
            verbose=False,
        )
        extraction_call = extract_feedback_enrichment.call_args
        self.assertEqual(extraction_call.args, ("The sales pipeline is broken.",))
        self.assertEqual(extraction_call.kwargs["software"].id, "dealym_crm")

    def test_unknown_software_is_rejected_before_provider_calls(self) -> None:
        with patch.object(tools_module, "analyze_sentiment") as analyze_sentiment:
            with self.assertRaisesRegex(ValueError, "Unknown software_id"):
                tools_module.analyze_feedback(
                    "The feature is broken.",
                    software_id="unknown_product",
                    openai_client=SimpleNamespace(),
                    model_deployment_name="functionality-model",
                    verbose=False,
                )

        analyze_sentiment.assert_not_called()

    def test_tool_logs_a_safe_root_cause_and_returns_a_generic_error(self) -> None:
        feedback = "The customer feedback that must stay private."
        function_call = SimpleNamespace(
            name="analyze_feedback",
            arguments=json.dumps(
                {
                    "software_id": "dealym_crm",
                    "feedback": feedback,
                }
            ),
        )
        agent, _ = make_ready_agent([])
        session = agent.start_conversation()
        session.add_user_message(
            f"Please analyze feedback for Dealym CRM: {feedback}",
            datetime.now(timezone.utc),
        )
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
            execution = agent._execute_tool(function_call, session=session)

        self.assertEqual(
            json.loads(execution.output),
            {"error": "analyze_feedback could not be completed."},
        )
        diagnostic = diagnostic_output.getvalue()
        self.assertIn("[feedback-agent][ERROR][tool]", diagnostic)
        self.assertIn("event=tool_execution_failed", diagnostic)
        self.assertIn("Unauthorized", diagnostic)
        self.assertNotIn(feedback, diagnostic)
        self.assertNotIn("super-secret", diagnostic)

    def test_generic_chat_reuses_conversation_without_saving_feedback(self) -> None:
        response = SimpleNamespace(output=[], output_text="Hello. How can I help?")
        agent, repository = make_ready_agent([response])
        session = agent.start_conversation()

        turn = agent.send_message(session, "Hello")

        self.assertEqual(turn.reply, "Hello. How can I help?")
        self.assertIsNone(turn.analysis)
        self.assertEqual(repository.calls, [])
        self.assertEqual(agent.openai.responses.calls[0]["conversation"], session.conversation_id)
        self.assertEqual(agent.openai.conversations.deleted, [])

        agent.close_conversation(session)
        self.assertEqual(agent.openai.conversations.deleted, [session.conversation_id])

    def test_explicit_feedback_analysis_saves_once_after_final_agent_reply(self) -> None:
        feedback = "The sales pipeline is broken."
        analysis_call = SimpleNamespace(
            type="function_call",
            name="analyze_feedback",
            arguments=json.dumps(
                {"software_id": "dealym_crm", "feedback": feedback}
            ),
            call_id="call-1",
        )
        first_response = SimpleNamespace(output=[analysis_call], output_text="")
        final_response = SimpleNamespace(
            output=[],
            output_text="The feedback is negative.",
        )
        agent, repository = make_ready_agent([first_response, final_response])
        session = agent.start_conversation()
        received_at = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)

        with patch.object(
            agent_module,
            "analyze_feedback",
            return_value=expected_analysis_result(),
        ) as analyze_feedback:
            turn = agent.send_message(
                session,
                f"Please analyze this feedback for Dealym CRM: {feedback}",
                received_at=received_at,
            )

        self.assertEqual(turn.reply, "The feedback is negative.")
        self.assertEqual(turn.analysis, expected_analysis_result())
        self.assertEqual(turn.feedback_record_id, "record-1")
        self.assertEqual(len(repository.calls), 1)
        self.assertEqual(repository.calls[0]["raw_comment"], feedback)
        self.assertEqual(repository.calls[0]["received_at"], received_at)
        analyze_feedback.assert_called_once_with(
            feedback,
            software_id="dealym_crm",
            openai_client=agent.openai,
            model_deployment_name=agent_module.MODEL_DEPLOYMENT_NAME,
            verbose=False,
        )
        self.assertEqual(len(agent.openai.responses.calls), 2)
        self.assertEqual(
            [call["conversation"] for call in agent.openai.responses.calls],
            [session.conversation_id, session.conversation_id],
        )
        tool_output = json.loads(agent.openai.responses.calls[1]["input"][0]["output"])
        self.assertEqual(tool_output, expected_analysis_result().model_dump(mode="json"))
        self.assertEqual(agent.openai.conversations.deleted, [])

    def test_conversation_can_use_product_context_from_an_earlier_user_turn(self) -> None:
        feedback = "HR Reporting is excellent."
        product_turn = SimpleNamespace(
            output=[],
            output_text="Targetym AI noted. What would you like to do?",
        )
        analysis_call = SimpleNamespace(
            type="function_call",
            name="analyze_feedback",
            arguments=json.dumps(
                {"software_id": "targetym_ai", "feedback": feedback}
            ),
            call_id="call-1",
        )
        tool_turn = SimpleNamespace(output=[analysis_call], output_text="")
        final_turn = SimpleNamespace(output=[], output_text="The feedback is positive.")
        agent, repository = make_ready_agent([product_turn, tool_turn, final_turn])
        session = agent.start_conversation()
        feedback_received_at = datetime(2026, 10, 5, 13, 0, tzinfo=timezone.utc)
        targetym_result = FeedbackAnalysisResult(
            software=SoftwareReference(id="targetym_ai", name="Targetym AI"),
            sentiment=SentimentLabel.POSITIVE,
            percentage=1.0,
            language="en",
            primary_functionality=FunctionalityReference(
                id="hr_reporting",
                name="HR reporting",
            ),
            feedback_type=FeedbackType.POSITIVE_FEEDBACK,
            feedback_summary="HR Reporting is easy to use.",
        )

        agent.send_message(session, "I would like to discuss Targetym AI.")
        with patch.object(
            agent_module,
            "analyze_feedback",
            return_value=targetym_result,
        ):
            turn = agent.send_message(
                session,
                f"Please analyze this feedback: {feedback}",
                received_at=feedback_received_at,
            )

        self.assertEqual(turn.analysis, targetym_result)
        self.assertEqual(len(repository.calls), 1)
        self.assertEqual(repository.calls[0]["received_at"], feedback_received_at)
        self.assertEqual(
            [call["conversation"] for call in agent.openai.responses.calls],
            [session.conversation_id] * 3,
        )

    def test_invented_feedback_is_rejected_and_not_persisted(self) -> None:
        analysis_call = SimpleNamespace(
            type="function_call",
            name="analyze_feedback",
            arguments=json.dumps(
                {
                    "software_id": "dealym_crm",
                    "feedback": "Invented customer feedback.",
                }
            ),
            call_id="call-1",
        )
        first_response = SimpleNamespace(output=[analysis_call], output_text="")
        final_response = SimpleNamespace(
            output=[],
            output_text="Please paste the feedback you want analyzed.",
        )
        agent, repository = make_ready_agent([first_response, final_response])
        session = agent.start_conversation()

        with patch.object(agent_module, "analyze_feedback") as analyze_feedback:
            turn = agent.send_message(
                session,
                "Please analyze feedback for Dealym CRM.",
            )

        self.assertEqual(turn.analysis, None)
        self.assertEqual(repository.calls, [])
        analyze_feedback.assert_not_called()
        tool_output = json.loads(agent.openai.responses.calls[1]["input"][0]["output"])
        self.assertEqual(
            tool_output,
            {"error": "analyze_feedback received invalid input."},
        )

    def test_two_analysis_calls_in_one_turn_do_not_create_duplicate_records(self) -> None:
        feedback = "The sales pipeline is broken."
        first_call = SimpleNamespace(
            type="function_call",
            name="analyze_feedback",
            arguments=json.dumps(
                {"software_id": "dealym_crm", "feedback": feedback}
            ),
            call_id="call-1",
        )
        second_call = SimpleNamespace(
            type="function_call",
            name="analyze_feedback",
            arguments=json.dumps(
                {"software_id": "dealym_crm", "feedback": feedback}
            ),
            call_id="call-2",
        )
        first_response = SimpleNamespace(output=[first_call, second_call], output_text="")
        final_response = SimpleNamespace(output=[], output_text="Analysis complete.")
        agent, repository = make_ready_agent([first_response, final_response])
        session = agent.start_conversation()

        with patch.object(
            agent_module,
            "analyze_feedback",
            return_value=expected_analysis_result(),
        ) as analyze_feedback:
            agent.send_message(
                session,
                f"Please analyze this feedback for Dealym CRM: {feedback}",
            )

        self.assertEqual(len(repository.calls), 1)
        analyze_feedback.assert_called_once()
        outputs = [
            json.loads(item["output"])
            for item in agent.openai.responses.calls[1]["input"]
        ]
        self.assertEqual(outputs[0], expected_analysis_result().model_dump(mode="json"))
        self.assertEqual(
            outputs[1],
            {"error": "Only one feedback item can be analyzed per user message."},
        )


class DataversePersistenceTests(unittest.TestCase):
    def _repository(self) -> dataverse_module.DataverseFeedbackRepository:
        return dataverse_module.DataverseFeedbackRepository(
            base_url="https://example.crm.dynamics.com",
            tenant_id="tenant-id",
            client_id="client-id",
            client_secret="client-secret",
            table_logical_name="agil_feedback",
            verbose=False,
        )

    def test_save_writes_enrichment_fields_and_choice_labels(self) -> None:
        client = FakeDataverseClient()
        received_at = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
        analyzed_at = datetime(2026, 10, 5, 12, 1, tzinfo=timezone.utc)

        with (
            patch.object(dataverse_module, "ClientSecretCredential", return_value=object()),
            patch.object(dataverse_module, "DataverseClient", return_value=client),
        ):
            record_id = self._repository().save(
                raw_comment="The sales pipeline is broken.",
                analysis=expected_analysis_result(),
                received_at=received_at,
                analyzed_at=analyzed_at,
            )

        self.assertEqual(record_id, "dataverse-record-1")
        table_name, payload = client.records.create.call_args.args
        self.assertEqual(table_name, "agil_feedback")
        self.assertEqual(payload["agil_primaryfunctionality"], "opportunity_pipeline")
        self.assertEqual(payload["agil_primaryfunctionalityname"], "Opportunity pipeline")
        self.assertEqual(payload["agil_feedbacktype"], "Signalement de problème")
        self.assertEqual(payload["agil_problemcategory"], "Bug ou erreur")
        self.assertEqual(payload["agil_feedbacksummary"], "The sales pipeline is broken.")
        self.assertNotIn("agil_extractedfunctionalities", payload)

    def test_save_omits_optional_enrichment_fields_when_absent(self) -> None:
        client = FakeDataverseClient()
        analysis = FeedbackAnalysisResult(
            software=SoftwareReference(id="targetym_ai", name="Targetym AI"),
            sentiment=SentimentLabel.POSITIVE,
            percentage=1.0,
            language="en",
            feedback_type=FeedbackType.POSITIVE_FEEDBACK,
            feedback_summary="The software is easy to use.",
        )
        timestamp = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)

        with (
            patch.object(dataverse_module, "ClientSecretCredential", return_value=object()),
            patch.object(dataverse_module, "DataverseClient", return_value=client),
        ):
            self._repository().save(
                raw_comment="The software is easy to use.",
                analysis=analysis,
                received_at=timestamp,
                analyzed_at=timestamp,
            )

        payload = client.records.create.call_args.args[1]
        self.assertEqual(payload["agil_feedbacktype"], "Éloge / retour positif")
        self.assertNotIn("agil_primaryfunctionality", payload)
        self.assertNotIn("agil_primaryfunctionalityname", payload)
        self.assertNotIn("agil_problemcategory", payload)


if __name__ == "__main__":
    unittest.main()
