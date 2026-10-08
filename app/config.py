import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

def _find_repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".env").exists():
            return parent
    return Path(__file__).resolve().parents[2]


REPO_ROOT = _find_repo_root()
# Load environment
env_path = REPO_ROOT / ".env"
load_dotenv(env_path)

PROJECT_CONNECTION_STRING = os.getenv("PROJECT_CONNECTION_STRING")
MODEL_DEPLOYMENT_NAME = os.getenv("MODEL_DEPLOYMENT_NAME", "gpt-4.1-mini")
AZURE_AI_LANGUAGE_ENDPOINT = os.getenv("AZURE_AI_LANGUAGE_ENDPOINT")
AZURE_AI_LANGUAGE_KEY = os.getenv("AZURE_AI_LANGUAGE_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")

DATAVERSE_URL = os.getenv("DATAVERSE_URL")
DATAVERSE_TENANT_ID = os.getenv("DATAVERSE_TENANT_ID")
DATAVERSE_CLIENT_ID = os.getenv("DATAVERSE_CLIENT_ID")
DATAVERSE_CLIENT_SECRET = os.getenv("DATAVERSE_CLIENT_SECRET")
DATAVERSE_FEEDBACK_TABLE = os.getenv("DATAVERSE_FEEDBACK_TABLE")
DATAVERSE_INSIGHT_ANALYSIS_TABLE = os.getenv("DATAVERSE_INSIGHT_ANALYSIS_TABLE")


def _positive_int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value in (None, ""):
        return default
    try:
        value = int(raw_value)
    except ValueError as error:
        raise RuntimeError(f"{name} must be a whole number.") from error
    if value <= 0:
        raise RuntimeError(f"{name} must be greater than zero.")
    return value


def _positive_float_env(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value in (None, ""):
        return default
    try:
        value = float(raw_value)
    except ValueError as error:
        raise RuntimeError(f"{name} must be a number.") from error
    if value <= 0:
        raise RuntimeError(f"{name} must be greater than zero.")
    return value


def _boolean_env(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value in (None, ""):
        return default
    normalized = raw_value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be true or false.")

EMBEDDING_MODEL_DEPLOYMENT_NAME = os.getenv(
    "EMBEDDING_MODEL_DEPLOYMENT_NAME",
    "",
)
EMBEDDING_BATCH_SIZE = _positive_int_env("EMBEDDING_BATCH_SIZE", 64)

CLUSTER_MAX_COSINE_DISTANCE = _positive_float_env(
    "CLUSTER_MAX_COSINE_DISTANCE",
    0.28,
)
if CLUSTER_MAX_COSINE_DISTANCE > 2:
    raise RuntimeError("CLUSTER_MAX_COSINE_DISTANCE must not exceed 2.")

CLUSTER_MIN_SIZE = _positive_int_env("CLUSTER_MIN_SIZE", 2)
CLUSTER_MAX_EXAMPLES = _positive_int_env("CLUSTER_MAX_EXAMPLES", 3)
if CLUSTER_MAX_EXAMPLES > 5:
    raise RuntimeError(
        "CLUSTER_MAX_EXAMPLES must not exceed 5 to bound representative evidence."
    )
CLUSTER_MAX_FEEDBACKS = _positive_int_env("CLUSTER_MAX_FEEDBACKS", 1000)
CLUSTER_LABELING_ENABLED = _boolean_env("CLUSTER_LABELING_ENABLED")
CLUSTER_LABEL_MODEL_DEPLOYMENT_NAME = os.getenv(
    "CLUSTER_LABEL_MODEL_DEPLOYMENT_NAME",
    MODEL_DEPLOYMENT_NAME,
)
