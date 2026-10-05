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

DATAVERSE_URL=os.getenv("DATAVERSE_URL")
DATAVERSE_TENANT_ID=os.getenv("DATAVERSE_TENANT_ID")
DATAVERSE_CLIENT_ID=os.getenv("DATAVERSE_CLIENT_ID")
DATAVERSE_CLIENT_SECRET=os.getenv("DATAVERSE_CLIENT_SECRET")
DATAVERSE_FEEDBACK_TABLE=os.getenv("DATAVERSE_FEEDBACK_TABLE")


