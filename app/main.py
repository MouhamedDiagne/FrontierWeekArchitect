"""Command-line entry point for the conversational feedback assistant."""

from __future__ import annotations

import sys

from .agents import FeedbackAnalyzerAgent
from .config import PROJECT_CONNECTION_STRING
from .conversation import ConversationSession
from .dataverse import DataverseFeedbackRepository
from .errors import _error_was_logged, _log_error


EXIT_COMMANDS = {"/exit", "/quit"}


def _close_session_quietly(
    agent: FeedbackAnalyzerAgent,
    session: ConversationSession | None,
) -> None:
    if session is None:
        return

    try:
        agent.close_conversation(session)
    except Exception as error:
        _log_error("main", "conversation_cleanup_failed", error)


def main() -> None:
    stage = "project_connection_configuration"
    last_message = ""
    feedback_analyzer: FeedbackAnalyzerAgent | None = None
    session: ConversationSession | None = None
    exit_code = 0

    try:
        if not PROJECT_CONNECTION_STRING:
            raise RuntimeError("PROJECT_CONNECTION_STRING must be configured.")

        print("Creating Database Client...")
        repository = DataverseFeedbackRepository.from_environment(verbose=True)

        print("=== Feedback Analyzer Agent ===")
        print("Creating agent...")
        feedback_analyzer = FeedbackAnalyzerAgent(
            verbose=True,
            feedback_repository=repository,
            feedback_reader=repository,
        )

        stage = "agent_creation"
        feedback_analyzer.create()
        if feedback_analyzer.client is None or feedback_analyzer.agent is None:
            raise RuntimeError("Project Client or Agent are not configured.")

        print(
            "Created: "
            f"{feedback_analyzer.agent.name} "
            f"(version {feedback_analyzer.agent.version})"
        )

        stage = "conversation_creation"
        session = feedback_analyzer.start_conversation()
        print("Assistant: Hello. I am the Agiltym assistant. How can I help you?")
        print("Type /quit to end the conversation.")

        while True:
            try:
                last_message = input("\nYou: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nAssistant: Goodbye.")
                break

            if last_message.casefold() in EXIT_COMMANDS:
                print("Assistant: Goodbye.")
                break

            if not last_message:
                continue

            try:
                stage = "conversation_turn"
                turn = feedback_analyzer.send_message(session, last_message)
                print(f"Assistant: {turn.reply}")
            except Exception as error:
                if not _error_was_logged(error):
                    _log_error(
                        "main",
                        "conversation_turn_failed",
                        error,
                        sensitive_values=(last_message,),
                    )
                print(
                    "Assistant: I could not process that message. Please try again.",
                    file=sys.stderr,
                    flush=True,
                )
    except Exception as error:
        exit_code = 1
        if not _error_was_logged(error):
            _log_error(
                "main",
                f"{stage}_failed",
                error,
                sensitive_values=(last_message,),
            )
        print(
            "Feedback assistant stopped. Review the [ERROR] diagnostic above.",
            file=sys.stderr,
            flush=True,
        )
    finally:
        if feedback_analyzer is not None:
            _close_session_quietly(feedback_analyzer, session)
            try:
                feedback_analyzer.cleanup()
            except Exception as error:
                _log_error("main", "agent_cleanup_failed", error)
                exit_code = 1

    if exit_code:
        raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
