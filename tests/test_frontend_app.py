"""Exercise report rendering and session navigation without remote services."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch


APP = str(Path(__file__).resolve().parents[1] / "frontend" / "streamlit_app.py")
VISUALS = {
    "visualizations": [
        {"id": "total", "kind": "kpi", "title": "Feedbacks", "value": 3, "value_format": "count"},
        {"id": "rate", "kind": "kpi", "title": "Sentiments positifs", "value": 100, "value_format": "percent"},
        {"id": "sentiments", "kind": "donut", "title": "Sentiments", "data": [{"label": "positive", "value": 3}]},
        {"id": "features", "kind": "bar", "title": "Fonctionnalités", "value_label": "Nombre de feedbacks",
         "data": [{"label": "Reporting RH", "value": 1}]},
        {"id": "signals", "kind": "table", "title": "Signaux", "columns": [
            {"key": "signal", "label": "Signal"}, {"key": "status", "label": "Statut"},
            {"key": "confidence", "label": "Confiance"}],
         "rows": [{"signal": "Reporting facile à utiliser", "status": "singleton", "confidence": 0.5}]},
    ],
}


def response(payload):
    return SimpleNamespace(status_code=200, ok=True, json=lambda: payload)


@unittest.skipUnless(importlib.util.find_spec("streamlit"), "Install frontend requirements to exercise the UI")
class FrontendAppTests(unittest.TestCase):
    def setUp(self):
        from streamlit.testing.v1 import AppTest
        self.app = AppTest.from_file(APP).run(timeout=15)
        self.assertFalse(self.app.exception)

    def test_history_preserves_messages_and_resumes_from_dashboard_without_sidebar(self):
        self.assertEqual(len(self.app.sidebar), 0)
        old_key = self.app.session_state["active_conversation_key"]
        with patch("requests.request", side_effect=[response({"session_id": "test-session"}), response({"reply": "## Résultat\n\n**Analyse** terminée."})]) as request:
            self.app.button(key="live_prompt_Identifier les insatisfactions").click().run(timeout=15)
        self.assertFalse(self.app.exception)
        self.assertEqual(request.call_count, 2)
        self.app.button(key="main_new_conversation").click().run(timeout=15)
        self.assertFalse(self.app.exception)
        self.assertEqual(len(self.app.session_state["conversation_history"]), 2)
        with patch("requests.request", return_value=response({"snapshot": {}, "visualizations": {}})):
            self.app.button(key="main_dashboard_navigation").click().run(timeout=15)
        self.assertEqual(self.app.session_state["active_view"], "dashboard")
        label = next(label for label, key in self.app.session_state["conversation_option_map"].items() if key == old_key)
        self.app.selectbox(key="conversation_selector").select(label).run(timeout=15)
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.session_state["active_view"], "assistant")
        self.assertEqual(self.app.session_state["conversation_id"], "test-session")
        self.assertEqual(len(self.app.session_state["messages"]), 3)

    def test_small_report_renders_markdown_units_and_compact_facts(self):
        message = {"role": "assistant", "text": "### Synthèse\n\n**Trois** retours.\n\n[[visual:sentiments]]\n\n### Détail",
                   "visualizations": VISUALS}
        key = self.app.session_state["active_conversation_key"]
        self.app.session_state["conversation_history"][key]["messages"] = [message]
        self.app.run(timeout=15)
        self.assertFalse(self.app.exception)
        markdown = [item for item in self.app.markdown if item.value.startswith("### Synthèse")]
        self.assertEqual(len(markdown), 1)
        self.assertFalse(markdown[0].proto.allow_html)
        rendered = "\n".join(item.value for item in self.app.markdown)
        self.assertIn("100 %", rendered)
        self.assertIn("Retour isolé", rendered)
        self.assertIn("50 %", rendered)
        self.assertEqual(rendered.count('<div class="single-label">Positif'), 1)
        self.assertNotIn("[[visual:", rendered)
        self.assertEqual(len(self.app.get("vega_lite_chart")), 0)

    def test_dashboard_renders_multiple_category_chart_from_saved_snapshot(self):
        bundle = {"visualizations": [{"id": "distribution", "kind": "donut", "title": "Sentiments", "value_label": "Nombre de feedbacks",
                                        "data": [{"label": "positive", "value": 8}, {"label": "negative", "value": 2}]}]}
        payload = {"snapshot": {"generated_at": "2026-10-08T07:59:21Z", "source": "conversation",
                                "audience_report": {"profile": "marketing", "scope": {}},
                                "insights": {"request": {"start_date": "2026-09-08T00:00:00Z", "end_date": "2026-10-08T00:00:00Z"}}},
                   "visualizations": bundle}
        with patch("requests.request", return_value=response(payload)) as request:
            self.app.button(key="main_dashboard_navigation").click().run(timeout=15)
        self.assertFalse(self.app.exception)
        request.assert_called_once()
        self.assertEqual(request.call_args.args[0], "GET")
        self.assertEqual(len(self.app.get("vega_lite_chart")), 1)
        captions = " ".join(item.value for item in self.app.caption)
        self.assertIn("08/10/2026 à 07:59 UTC", captions)
        self.assertIn("08/09/2026 → 08/10/2026 (fin exclue)", captions)


if __name__ == "__main__":
    unittest.main()
