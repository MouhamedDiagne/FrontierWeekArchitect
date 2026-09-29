import os
from pathlib import Path
from dotenv import load_dotenv



# Resolve repo root by finding .env in parent directories.
def _find_repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".env").exists():
            return parent
    return Path(__file__).resolve().parents[2]

REPO_ROOT = _find_repo_root()

print("#####################")
print(REPO_ROOT)
print("#####################")

#Loading Environment
env_path = REPO_ROOT / ".env"
load_dotenv(env_path) 

PROJECT_CONNECTION_STRING = os.getenv("PROJECT_CONNECTION_STRING")
MODEL_DEPLOYMENT_NAME = os.getenv("MODEL_DEPLOYMENT_NAME")
