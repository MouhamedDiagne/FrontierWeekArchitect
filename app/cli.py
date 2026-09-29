import argparse
import sys

from pydantic import ValidationError

from .config import Settings
from .errors import FeedbackAnalysisAgentError
from .tools import GeminiSentimentProvider
from .agent import FeedbackAnalyserAgent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Classify the sentiment of customer feedback."
    )
    parser.add_argument("--text", required=True, help="Customer feedback text")
    args = parser.parse_args(argv)

    try:
        agent = FeedbackAnalyserAgent(GeminiSentimentProvider())
        result = agent.analyzeSentiment(args.text)
    except ValidationError:
        print('{"error":"invalid_input"}', file=sys.stderr)
        return 2
    except FeedbackAnalysisAgentError as exc:
        print(f'{{"error":"{type(exc).__name__}"}}', file=sys.stderr)
        return 4

    print(result.model_dump_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())