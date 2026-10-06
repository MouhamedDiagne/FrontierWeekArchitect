import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from app import agents as agent_module
from app import tools as tools_module
from app.models import (
    FeedbackInsightsDataQuality,
    FeedbackInsightsRequest,
    FeedbackInsightsResult,
)


class FakeConversations:
    def __init__(self):
        self.created = []

    def create(self):
        conversation_id = f"conversation-{len(self.created) + 1}"
        self.created.append(conversation_id)
        return SimpleNamespace(id=conversation_id)

    def delete(self, conversation_id):
        return None


class FakeResponses:
    def __init__(self, responses):
        self._responses = iter(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return next(self._responses)


class FakeFeedbackRepository:
    def __init__(self):
        self.save_calls = []

    def save(self, **kwargs):
        self.save_calls.append(kwargs)
        return "record-1"


class FakeInsightsService:
    def __init__(self, result):
        self.result = result
        self.requests = []

    def analyze(self, request):
        self.requests.append(request)
        return self.result


def insight_result():
    request = FeedbackInsightsRequest(
        start_date=datetime(2026, 10, 1, tzinfo=timezone.utc),
        end_date=datetime(2026, 11, 1, tzinfo=timezone.utc),
        software_id="dealym_crm",
        audience_profile="management",
    )
    return FeedbackInsightsResult(
        request=request,
        total_feedbacks=0,
        clustered_feedbacks=0,
        clusters=[],
        data_quality=FeedbackInsightsDataQuality(
            records_with_summary=0,
            records_using_raw_fallback=0,
            records_without_usable_representation=0,
        ),
        limitations=["Aucun feedback ne correspond à la période courante demandée."],
    )


class AgentInsightsToolTests(unittest.TestCase):
    def test_system_prompt_has_structured_reporting_instructions(self):
        prompt = agent_module.build_agent_system_prompt()

        for heading in (
            "## Role",
            "## Missions",
            "## Comment mener à bien chaque mission",
            "## Règles Générales",
            "## Limitations",
            "## Outils à disposition",
            "## Guard-rails",
            "## Fallbacks",
        ):
            self.assertIn(heading, prompt)
        self.assertIn("audience_profile", prompt)
        self.assertIn("insights contains", prompt)
        self.assertIn("audience_report contains", prompt)

    def test_historical_tool_schema_requires_dates_and_uses_nullable_optional_filters(self):
        tool = tools_module.build_feedback_insights_tool()

        self.assertTrue(tool.strict)
        self.assertEqual(tool.name, "analyze_feedback_insights")
        self.assertEqual(
            tool.parameters["required"],
            [
                "start_date",
                "end_date",
                "software_id",
                "functionality_id",
                "sentiment",
                "feedback_type",
                "audience_profile",
                "comparison_start_date",
                "comparison_end_date",
            ],
        )
        self.assertIn(
            "null",
            tool.parameters["properties"]["software_id"]["type"],
        )
        self.assertEqual(
            tool.parameters["properties"]["audience_profile"]["enum"],
            ["marketing", "it", "support_sales", "management"],
        )

    def test_historical_tool_uses_injected_service_and_never_persists_a_feedback(self):
        result = insight_result()
        service = FakeInsightsService(result)
        repository = FakeFeedbackRepository()
        function_call = SimpleNamespace(
            type="function_call",
            name="analyze_feedback_insights",
            call_id="report-call-1",
            arguments=json.dumps(
                {
                    "start_date": "2026-10-01T00:00:00Z",
                    "end_date": "2026-11-01T00:00:00Z",
                    "software_id": "dealym_crm",
                    "functionality_id": None,
                    "sentiment": None,
                    "feedback_type": None,
                    "audience_profile": "management",
                    "comparison_start_date": None,
                    "comparison_end_date": None,
                }
            ),
        )
        first_response = SimpleNamespace(output=[function_call], output_text="")
        final_response = SimpleNamespace(
            output=[],
            output_text="Aucun feedback n'a été trouvé pour octobre.",
        )
        openai = SimpleNamespace(
            conversations=FakeConversations(),
            responses=FakeResponses([first_response, final_response]),
        )
        agent = agent_module.FeedbackAnalyzerAgent(
            feedback_repository=repository,
            insights_service=service,
            verbose=False,
        )
        agent.client = SimpleNamespace()
        agent.agent = SimpleNamespace(
            name="feedback-analyzer-agent",
            version="1",
            id="agent-1",
        )
        agent.openai = openai
        session = agent.start_conversation()

        turn = agent.send_message(
            session,
            "Fais un rapport sur Dealym CRM pour octobre 2026.",
        )

        self.assertEqual(turn.reply, "Aucun feedback n'a été trouvé pour octobre.")
        self.assertEqual(turn.insights, result)
        self.assertEqual(turn.audience_report.profile.value, "management")
        self.assertEqual(repository.save_calls, [])
        self.assertEqual(service.requests[0].software_id, "dealym_crm")
        tool_output = json.loads(openai.responses.calls[1]["input"][0]["output"])
        self.assertEqual(tool_output["insights"], result.model_dump(mode="json"))
        self.assertEqual(tool_output["audience_report"]["profile"], "management")
        self.assertEqual(tool_output["audience_report"]["priority_signal_ids"], [])


if __name__ == "__main__":
    unittest.main()
