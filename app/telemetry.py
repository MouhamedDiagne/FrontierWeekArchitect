"""Safe, optional OpenTelemetry bootstrap for the feedback prototype.

This module deliberately does not create Azure resources.  When explicitly
enabled, it configures the local process to export bounded operational spans to
an already configured Application Insights resource.  Feedback text, generated
summaries, prompts, tool arguments and Dataverse payloads must never be added
as custom span attributes.
"""

from __future__ import annotations

import atexit
import os
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Lock
from typing import Iterator, Mapping

from .config import (
    APPLICATIONINSIGHTS_CONNECTION_STRING,
    OBSERVABILITY_CAPTURE_MESSAGE_CONTENT,
    OBSERVABILITY_ENABLE_FOUNDRY_GENAI_TRACING,
    OBSERVABILITY_ENABLED,
)

_CONFIGURATION_LOCK = Lock()
_configured = False
_tracer = None


@dataclass(frozen=True)
class TelemetrySettings:
    """Resolved, non-secret telemetry configuration for one process."""

    enabled: bool
    connection_string: str | None
    service_name: str
    capture_message_content: bool
    enable_foundry_genai_tracing: bool


def settings_from_environment(default_service_name: str) -> TelemetrySettings:
    """Resolve telemetry settings without exposing the connection string."""

    return TelemetrySettings(
        enabled=OBSERVABILITY_ENABLED,
        connection_string=APPLICATIONINSIGHTS_CONNECTION_STRING,
        service_name=os.getenv("OTEL_SERVICE_NAME", default_service_name),
        capture_message_content=OBSERVABILITY_CAPTURE_MESSAGE_CONTENT,
        enable_foundry_genai_tracing=OBSERVABILITY_ENABLE_FOUNDRY_GENAI_TRACING,
    )


def _log(message: str) -> None:
    print(f"[feedback-agent][telemetry] {message}")


def _configure_exporters(settings: TelemetrySettings):
    """Configure SDK exporters and return the tracer used by custom spans."""

    from azure.monitor.opentelemetry import configure_azure_monitor
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource

    configure_azure_monitor(
        connection_string=settings.connection_string,
        enable_live_metrics=True,
        logger_name="agiltym.feedback",
        resource=Resource.create(
            {
                "service.name": settings.service_name,
                "service.namespace": "agiltym",
            }
        ),
    )

    # GenAI spans use experimental Foundry instrumentation.  Keep it behind a
    # separate opt-in: some SDK combinations cannot safely enrich an
    # unsampled/non-recording span (the business path must always win).
    azure_experimental_tracing_enabled = os.getenv(
        "AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING", ""
    ).strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if settings.enable_foundry_genai_tracing and azure_experimental_tracing_enabled:
        from azure.ai.projects.telemetry import AIProjectInstrumentor

        AIProjectInstrumentor().instrument()
    else:
        _log(
            "Azure Monitor enabled; experimental Foundry GenAI spans are disabled."
        )
    return trace.get_tracer("agiltym.feedback")


def configure_telemetry(service_name: str) -> bool:
    """Configure Azure Monitor once, returning whether local export is active.

    Telemetry is intentionally best-effort: invalid optional monitoring
    configuration must not prevent the feedback service from starting.
    """

    global _configured, _tracer
    settings = settings_from_environment(service_name)
    if not settings.enabled:
        return False
    if not settings.connection_string:
        _log("Disabled: APPLICATIONINSIGHTS_CONNECTION_STRING is not configured.")
        return False

    with _CONFIGURATION_LOCK:
        if _configured:
            return True

        # Foundry tracing reads this during instrumentation.  Keep client
        # feedback and agent content out of telemetry unless someone makes the
        # privacy decision explicit for this process.
        os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] = (
            "true" if settings.capture_message_content else "false"
        )

        try:
            _tracer = _configure_exporters(settings)
            _configured = True
            atexit.register(flush_telemetry)
            _log(
                "Azure Monitor export enabled; feedback and message content capture is "
                f"{'enabled' if settings.capture_message_content else 'disabled'}."
            )
            return True
        except Exception as error:
            # Do not include the connection string or request data in logs.
            _log(
                "Could not configure Azure Monitor; continuing without local telemetry "
                f"({type(error).__name__})."
            )
            return False


def flush_telemetry() -> None:
    """Best-effort exporter flush for short-lived CLI and scheduled processes."""

    if not _configured:
        return
    try:
        from opentelemetry import trace

        provider = trace.get_tracer_provider()
        force_flush = getattr(provider, "force_flush", None)
        if callable(force_flush):
            force_flush(timeout_millis=5_000)
    except Exception as error:
        _log(f"Could not flush telemetry ({type(error).__name__}).")


@contextmanager
def traced_operation(
    name: str,
    *,
    attributes: Mapping[str, str | int | float | bool] | None = None,
) -> Iterator[None]:
    """Create a bounded business span or yield silently when monitoring is off."""

    if not _configured or _tracer is None:
        yield
        return

    from opentelemetry.trace import Status, StatusCode

    with _tracer.start_as_current_span(name) as span:
        if attributes:
            for key, value in attributes.items():
                span.set_attribute(key, value)
        try:
            yield
        except Exception as error:
            # Do not record the exception message: it can include feedback or
            # provider response content.  The error type is enough for POC
            # diagnostics and matches the existing safe terminal logging.
            span.set_attribute("error.type", type(error).__name__)
            span.set_status(Status(StatusCode.ERROR))
            raise


def _reset_for_tests() -> None:
    """Reset module state for isolated unit tests; not a runtime API."""

    global _configured, _tracer
    with _CONFIGURATION_LOCK:
        _configured = False
        _tracer = None
