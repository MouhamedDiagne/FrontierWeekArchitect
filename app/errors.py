import json
import os
import re
import sys

from pydantic import ValidationError
from typing import Any

from .config import PROJECT_CONNECTION_STRING, AZURE_AI_LANGUAGE_KEY

_SENSITIVE_ERROR_VALUE_PATTERN = re.compile(
    r"(?i)\b(authorization|api[ _-]?key|connection[ _-]?string|password|secret|token)"
    r"\b\s*([:=])\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_MAX_ERROR_DETAIL_LENGTH = 500

class FeedbackAnalysisAgentError(Exception):
    """Base error for the sentiment agent."""


class ConfigurationError(FeedbackAnalysisAgentError):
    pass


class ProviderRequestError(FeedbackAnalysisAgentError):
    pass


class InvalidModelResponseError(FeedbackAnalysisAgentError):
    pass


def _safe_error_detail(error: Exception, *, sensitive_values: tuple[str, ...] = ()) -> str:
    """Return a useful diagnostic without echoing feedback, keys, or full payloads."""
    if isinstance(error, ValidationError):
        try:
            items = error.errors(include_input=False, include_url=False)
        except TypeError:
            items = error.errors()
        detail = "; ".join(
            (
                f"{'.'.join(str(part) for part in item.get('loc', ())) or 'input'}: "
                f"{item.get('msg', 'invalid value')}"
            )
            for item in items
        )
    elif isinstance(error, json.JSONDecodeError):
        detail = (
            f"{error.msg} at line {error.lineno}, column {error.colno}."
        )
    else:
        detail = str(error).strip() or "No additional diagnostic message."

    redaction_values = (
        *sensitive_values,
        PROJECT_CONNECTION_STRING or "",
        AZURE_AI_LANGUAGE_KEY or "",
    )
    for value in redaction_values:
        if isinstance(value, str) and value:
            detail = detail.replace(value, "<redacted>")

    detail = _SENSITIVE_ERROR_VALUE_PATTERN.sub(r"\1\2<redacted>", detail)
    detail = " ".join(detail.split())
    if len(detail) > _MAX_ERROR_DETAIL_LENGTH:
        detail = f"{detail[:_MAX_ERROR_DETAIL_LENGTH - 3]}..."
    return detail


def _log_error(
    step: str,
    event: str,
    error: Exception,
    *,
    sensitive_values: tuple[str, ...] = (),
) -> None:
    """Print a safe, actionable error diagnostic to the local terminal."""
    metadata: list[str] = []
    for attribute, label in (
        ("status_code", "status"),
        ("status", "status"),
        ("code", "provider_code"),
        ("request_id", "request_id"),
    ):
        value = getattr(error, attribute, None)
        if value not in (None, "") and not callable(value):
            value_detail = _safe_error_detail(
                RuntimeError(str(value)), sensitive_values=sensitive_values
            )
            metadata.append(f"{label}={value_detail}")

    metadata_text = f" {' '.join(metadata)}" if metadata else ""
    print(
        f"[feedback-agent][ERROR][{step}] event={event} "
        f"error_type={type(error).__name__}{metadata_text} "
        f"detail={_safe_error_detail(error, sensitive_values=sensitive_values)}",
        file=sys.stderr,
        flush=True,
    )
    try:
        setattr(error, "_feedback_agent_error_logged", True)
    except (AttributeError, TypeError):
        pass


def _error_was_logged(error: Exception) -> bool:
    """Tell whether a lower layer has already emitted a safe diagnostic."""
    return bool(getattr(error, "_feedback_agent_error_logged", False))


def _raise_language_error(operation: str, document: Any) -> None:
    """Raise a readable error for a per-document Azure Language failure."""
    error = document.error
    raise RuntimeError(f"Azure AI Language {operation} failed: {error.code} - {error.message}")

