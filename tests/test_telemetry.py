import os
import unittest
from unittest.mock import patch

from app import telemetry


class TelemetryBootstrapTests(unittest.TestCase):
    def setUp(self):
        telemetry._reset_for_tests()
        self._previous_capture = os.environ.get(
            "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"
        )

    def tearDown(self):
        telemetry._reset_for_tests()
        if self._previous_capture is None:
            os.environ.pop("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", None)
        else:
            os.environ[
                "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"
            ] = self._previous_capture

    def test_disabled_telemetry_does_not_configure_exporters(self):
        with patch.object(telemetry, "OBSERVABILITY_ENABLED", False), patch.object(
            telemetry, "_configure_exporters"
        ) as configure_exporters:
            self.assertFalse(telemetry.configure_telemetry("test-service"))

        configure_exporters.assert_not_called()

    def test_enabled_telemetry_configures_once_and_disables_content_by_default(self):
        fake_tracer = object()
        with patch.object(telemetry, "OBSERVABILITY_ENABLED", True), patch.object(
            telemetry, "APPLICATIONINSIGHTS_CONNECTION_STRING", "InstrumentationKey=test"
        ), patch.object(telemetry, "OBSERVABILITY_CAPTURE_MESSAGE_CONTENT", False), patch.object(
            telemetry, "OBSERVABILITY_ENABLE_FOUNDRY_GENAI_TRACING", False
        ), patch.object(
            telemetry, "_configure_exporters", return_value=fake_tracer
        ) as configure_exporters:
            self.assertTrue(telemetry.configure_telemetry("test-service"))
            self.assertTrue(telemetry.configure_telemetry("second-service"))

        configure_exporters.assert_called_once()
        settings = configure_exporters.call_args.args[0]
        self.assertEqual(settings.service_name, "test-service")
        self.assertFalse(settings.enable_foundry_genai_tracing)
        self.assertEqual(
            os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"],
            "false",
        )

    def test_exporter_failure_does_not_prevent_process_startup(self):
        with patch.object(telemetry, "OBSERVABILITY_ENABLED", True), patch.object(
            telemetry, "APPLICATIONINSIGHTS_CONNECTION_STRING", "InstrumentationKey=test"
        ), patch.object(
            telemetry, "OBSERVABILITY_ENABLE_FOUNDRY_GENAI_TRACING", False
        ), patch.object(
            telemetry, "_configure_exporters", side_effect=RuntimeError("unavailable")
        ):
            self.assertFalse(telemetry.configure_telemetry("test-service"))

    def test_explicit_content_capture_is_forwarded_to_process_environment(self):
        with patch.object(telemetry, "OBSERVABILITY_ENABLED", True), patch.object(
            telemetry, "APPLICATIONINSIGHTS_CONNECTION_STRING", "InstrumentationKey=test"
        ), patch.object(telemetry, "OBSERVABILITY_CAPTURE_MESSAGE_CONTENT", True), patch.object(
            telemetry, "OBSERVABILITY_ENABLE_FOUNDRY_GENAI_TRACING", False
        ), patch.object(
            telemetry, "_configure_exporters", return_value=object()
        ):
            self.assertTrue(telemetry.configure_telemetry("test-service"))

        self.assertEqual(
            os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"],
            "true",
        )
