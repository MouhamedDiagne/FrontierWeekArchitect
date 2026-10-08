"""Presentation regressions from the POC's real report screenshots."""

import unittest

from frontend.presentation import (
    SENTIMENT_COLORS,
    build_chart_spec,
    display_label,
    display_value,
    render_table_html,
)


class FrontendPresentationTests(unittest.TestCase):
    def test_percentages_keep_the_backend_scale_and_unknown_is_not_zero(self):
        self.assertEqual(display_value(100, "percent"), "100 %")
        self.assertEqual(display_value(12.5, "percentage"), "12,5 %")
        self.assertEqual(display_value(None, "percent"), "—")
        self.assertEqual(display_value(1200, "count"), "1\u202f200")

    def test_one_feedback_never_uses_fractional_count_ticks_or_a_giant_bar(self):
        chart = build_chart_spec({"kind": "bar", "value_label": "Nombre de feedbacks",
                                  "data": [{"label": "Reporting RH", "value": 1}]})
        self.assertEqual(chart["encoding"]["x"]["axis"]["values"], [0, 1])
        self.assertEqual(chart["encoding"]["x"]["axis"]["format"], "d")
        self.assertEqual(chart["layer"][0]["mark"]["size"], 22)
        self.assertLessEqual(chart["height"], 100)
        self.assertEqual(chart["data"]["values"][0]["value_text"], "1")

    def test_priority_chart_retains_fractional_scores(self):
        chart = build_chart_spec({"kind": "bar", "value_label": "Score de priorité",
                                  "data": [{"label": "Sujet", "value": 2.4}]})
        self.assertNotEqual(chart["encoding"]["x"]["axis"]["format"], "d")
        self.assertEqual(chart["data"]["values"][0]["value_text"], "2,4")

    def test_sentiment_color_does_not_depend_on_sort_or_missing_categories(self):
        chart = build_chart_spec({"kind": "donut", "value_label": "Nombre de feedbacks", "data": [
            {"label": "negative", "value": 2}, {"label": "positive", "value": 8}]})
        scale = chart["encoding"]["color"]["scale"]
        self.assertEqual(dict(zip(scale["domain"], scale["range"])), {
            "Négatif": SENTIMENT_COLORS["negative"], "Positif": SENTIMENT_COLORS["positive"],
        })
        self.assertEqual(chart["data"]["values"][0]["share_text"], "20 %")

    def test_line_comparison_stays_chronological_and_preserves_explicit_labels(self):
        chart = build_chart_spec({"kind": "line", "series": [{"label": "Signal", "points": [
            {"period": "current", "value": 2, "label": "Avril 2026"},
            {"period": "comparison", "value": 1, "label": "Mars 2026"},
        ]}]})
        self.assertEqual(chart["encoding"]["x"]["sort"], ["Mars 2026", "Avril 2026"])
        self.assertEqual(chart["encoding"]["y"]["axis"]["format"], "d")

    def test_table_escapes_content_translates_enums_and_formats_confidence(self):
        table = render_table_html({"title": '<script>alert("x")</script>', "columns": [
            {"key": "signal", "label": "<b>Signal</b>"},
            {"key": "status", "label": "Statut"},
            {"key": "confidence", "label": "Confiance"},
            {"key": "trend", "label": "Évolution"},
        ], "rows": [{"signal": '<img src=x onerror="attack()">', "status": "needs_review",
                     "confidence": 0.5, "trend": None}]})
        self.assertNotIn("<script>", table)
        self.assertNotIn("<img", table)
        self.assertNotIn("<b>", table)
        self.assertIn("&lt;img", table)
        self.assertIn("À vérifier", table)
        self.assertIn("50 %", table)
        self.assertIn("—", table)
        self.assertIn('class="report-table-signal"', table)
        self.assertEqual(display_label("performance_slowdown"), "Performance / lenteur")

    def test_empty_and_unsupported_charts_are_not_drawn(self):
        self.assertIsNone(build_chart_spec({"kind": "bar", "data": []}))
        self.assertIsNone(build_chart_spec({"kind": "donut", "data": [{"label": "positive", "value": 0}]}))
        self.assertIsNone(build_chart_spec({"kind": "script"}))


if __name__ == "__main__":
    unittest.main()
