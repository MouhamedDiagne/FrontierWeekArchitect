import os
import sys
from azure.ai.projects.models import AgentVersionDetails

from .agents import FeedbackAnalyzerAgent
from .config import PROJECT_CONNECTION_STRING, MODEL_DEPLOYMENT_NAME,AZURE_AI_LANGUAGE_ENDPOINT, AZURE_AI_LANGUAGE_KEY
from .knowledge import load_software_catalog
from .errors import _error_was_logged, _log_error


def main() -> None:
    stage = "project_connection_configuration"
    feedback = ""
    try:
        if not PROJECT_CONNECTION_STRING:
            raise RuntimeError("PROJECT_CONNECTION_STRING must be configured.")

        print("=== Feedback Analyzer Agent ===")
        print("Creating agent...")

        feedback_analyzer = FeedbackAnalyzerAgent(verbose=True)
        stage = "agent_creation"
        feedback_analyzer.create()
        if feedback_analyzer.client is None or feedback_analyzer.agent is None:
            raise RuntimeError("Project Client or Agent are not configured")
        print(
            "Created: "
            f"{feedback_analyzer.agent.name} "
            f"(version {feedback_analyzer.agent.version})"
        )

        stage = "knowledge_catalog_loading"
        catalog = load_software_catalog()
        available_software = ", ".join(
            f"{application.id} ({application.display_name})"
            for application in catalog.applications
        )
        stage = "interactive_input"
        software_id = input(f"Enter the software ID [{available_software}]: ")
        feedback = input("Enter the customer feedback: ")

        stage = "agent_run"
        analysis_result = feedback_analyzer.run(feedback, software_id=software_id)

        print(analysis_result)
    except Exception as error:
        if not _error_was_logged(error):
            _log_error(
                "main",
                f"{stage}_failed",
                error,
                sensitive_values=(feedback,),
            )
        print(
            "Feedback analysis stopped. Review the [ERROR] diagnostic above.",
            file=sys.stderr,
            flush=True,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
