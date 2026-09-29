import os 
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from .errors import ConfigurationError


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str
    gemini_model_name: str

    @classmethod
    def from_environment(cls) -> "Settings":
        project_root = Path(__file__).resolve().parent
        load_dotenv(project_root / ".env")

        api_key = os.getenv("GEMINI_API_KEY")
        model_name = os.getenv("GEMINI_MODEL_NAME")
        if not api_key or not model_name:
            raise ConfigurationError("GEMINI_API_KEY is not configured.")

        return cls(
            gemini_api_key=api_key,
            gemini_model_name=model_name
        )

settings = Settings.from_environment()


