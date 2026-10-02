"""Runtime loading and validation for the Agiltym software catalog."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator


CATALOG_PATH = (
    Path(__file__).resolve().parents[1]
    / "knowledge"
    / "agiltym_software_catalog.json"
)
_IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


def _normalize_text(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be blank")
    return normalized


class CatalogFunctionality(BaseModel):
    """One canonical, provisional functionality in the runtime catalog."""

    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    catalog_status: str = Field(min_length=1, max_length=40)

    @field_validator("id")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        normalized = _normalize_text(value, field_name="id").lower()
        if not _IDENTIFIER_PATTERN.fullmatch(normalized):
            raise ValueError("id must use lowercase letters, digits, and underscores")
        return normalized

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _normalize_text(value, field_name="name")

    @field_validator("aliases")
    @classmethod
    def normalize_aliases(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(_normalize_text(value, field_name="alias") for value in values))


class SoftwareKnowledge(BaseModel):
    """One Agiltym application and its known functionality candidates."""

    id: str = Field(min_length=1, max_length=80)
    display_name: str = Field(min_length=1, max_length=120)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    description: str = Field(min_length=1, max_length=500)
    catalog_status: str = Field(min_length=1, max_length=40)
    functionalities: list[CatalogFunctionality] = Field(default_factory=list, max_length=50)

    @field_validator("id")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        normalized = _normalize_text(value, field_name="id").lower()
        if not _IDENTIFIER_PATTERN.fullmatch(normalized):
            raise ValueError("id must use lowercase letters, digits, and underscores")
        return normalized

    @field_validator("display_name", "description", "catalog_status")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        return _normalize_text(value, field_name="software field")

    @field_validator("aliases")
    @classmethod
    def normalize_aliases(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(_normalize_text(value, field_name="alias") for value in values))

    @model_validator(mode="after")
    def validate_unique_functionality_ids(self) -> "SoftwareKnowledge":
        functionality_ids = [feature.id for feature in self.functionalities]
        if len(functionality_ids) != len(set(functionality_ids)):
            raise ValueError("functionality ids must be unique within one software")
        return self


class SoftwareCatalog(BaseModel):
    """Validated contents of the versioned JSON knowledge catalog."""

    schema_version: str = Field(min_length=1, max_length=20)
    source_file: str = Field(min_length=1, max_length=260)
    applications: list[SoftwareKnowledge] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def validate_unique_application_ids(self) -> "SoftwareCatalog":
        application_ids = [application.id for application in self.applications]
        if len(application_ids) != len(set(application_ids)):
            raise ValueError("application ids must be unique")
        return self


@lru_cache(maxsize=1)
def load_software_catalog() -> SoftwareCatalog:
    """Load the catalog once per process; restart to adopt catalog file changes."""
    try:
        raw_catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except OSError as error:
        raise RuntimeError(f"Unable to read software catalog at {CATALOG_PATH}.") from error
    except json.JSONDecodeError as error:
        raise RuntimeError("Software catalog contains invalid JSON.") from error

    try:
        return SoftwareCatalog.model_validate(raw_catalog)
    except ValidationError as error:
        raise RuntimeError("Software catalog does not match the expected schema.") from error


def get_software_knowledge(
    software_id: str,
    *,
    catalog: SoftwareCatalog | None = None,
) -> SoftwareKnowledge:
    """Resolve a caller-provided canonical software identifier."""
    selected_catalog = catalog or load_software_catalog()
    normalized_id = software_id.strip().lower()
    for application in selected_catalog.applications:
        if application.id == normalized_id:
            return application

    supported_ids = ", ".join(application.id for application in selected_catalog.applications)
    raise ValueError(
        f"Unknown software_id '{normalized_id}'. Supported values: {supported_ids}."
    )


def build_agent_knowledge_context(
    catalog: SoftwareCatalog | None = None,
) -> str:
    """Return the compact, high-level catalog context suitable for agent instructions."""
    selected_catalog = catalog or load_software_catalog()
    return "\n".join(
        f"- {application.id} — {application.display_name}: {application.description}"
        for application in selected_catalog.applications
    )
