"""Small, deterministic presentation helpers for the Streamlit interface.

Values come from the API's visualization specifications.  These helpers do not
run model code, fetch data, or import the backend; their only output is a
Vega-Lite specification, display text, or an HTML table with escaped content.
"""

from __future__ import annotations

from enum import Enum
from html import escape
from math import ceil, isfinite
from numbers import Real
from typing import Any


SENTIMENT_COLORS = {
    "positive": "#087f81",
    "negative": "#c74747",
    "mixed": "#b77916",
    "neutral": "#69788c",
}
SERIES_COLORS = ["#087f81", "#5366b8", "#b77916", "#b94e7c"]
DISPLAY_LABELS = {
    "positive": "Positif",
    "negative": "Négatif",
    "mixed": "Mitigé",
    "neutral": "Neutre",
    "clustered": "Signal confirmé",
    "singleton": "Retour isolé",
    "needs_review": "À vérifier",
    "new": "Nouveau",
    "up": "En hausse",
    "stable": "Stable",
    "down": "En baisse",
    "comparison": "Période de référence",
    "current": "Période courante",
    "issue_report": "Signalement de problème",
    "feature_request": "Demande de fonctionnalité",
    "improvement_suggestion": "Suggestion d’amélioration",
    "information_request": "Besoin d’information",
    "positive_feedback": "Éloge / retour positif",
    "other_feedback": "Autre retour",
    "bug_error": "Bug ou erreur",
    "performance_slowdown": "Performance / lenteur",
    "availability_reliability": "Disponibilité / fiabilité",
    "usability_ux": "Difficulté d’usage / UX",
    "access_authentication": "Accès / authentification",
    "data_quality_reporting": "Qualité des données / reporting",
    "billing_payment": "Paiement / facturation",
    "integration": "Intégration",
    "documentation_information": "Documentation / information",
    "support_experience": "Expérience avec le support",
    "security_privacy": "Sécurité / confidentialité",
    "other_problem": "Autre problème",
    "marketing": "Marketing",
    "it": "IT",
    "support_sales": "Support / Sales",
    "management": "Management",
}


def _enum_value(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value


def display_label(value: Any) -> str:
    """Translate known transport enums, preserving free-form names and titles."""

    value = _enum_value(value)
    if value is None or value == "":
        return "—"
    return DISPLAY_LABELS.get(str(value), str(value))


def display_value(value: Any, value_format: str | None = None) -> str:
    """Format factual scalars; percent values are already on a 0–100 scale."""

    if value is None:
        return "—"
    if not isinstance(value, Real) or isinstance(value, bool):
        return display_label(value)
    if not isfinite(value):
        return "—"
    value_format = _enum_value(value_format)
    if value_format in {"count", "integer"}:
        rendered = f"{value:,.0f}"
    else:
        rendered = f"{value:,.1f}".rstrip("0").rstrip(".")
    rendered = rendered.replace(",", "\u202f").replace(".", ",")
    return f"{rendered} %" if value_format in {"percent", "percentage"} else rendered


def _light_config() -> dict[str, Any]:
    return {
        "background": "#ffffff",
        "view": {"stroke": None},
        "axis": {
            "labelColor": "#475569",
            "titleColor": "#475569",
            "labelFontSize": 12,
            "titleFontSize": 12,
            "titleFontWeight": "normal",
            "gridColor": "#e8eef2",
            "domain": False,
            "ticks": False,
            "labelPadding": 8,
            "titlePadding": 12,
        },
        "legend": {
            "labelColor": "#475569",
            "titleColor": "#475569",
            "labelFontSize": 12,
            "symbolSize": 90,
            "labelLimit": 280,
            "orient": "bottom",
            "columns": 2,
            "padding": 8,
        },
        "range": {"category": SERIES_COLORS},
    }


def _numeric_axis(maximum: float, *, count: bool) -> dict[str, Any]:
    axis: dict[str, Any] = {"tickCount": 4}
    if count:
        # Explicit integer ticks prevent 0.05, 0.10, etc. for a one-item bar.
        step = max(1, ceil(maximum / 4))
        upper = max(1, ceil(maximum / step) * step)
        axis.update({"values": list(range(0, upper + 1, step)), "format": "d"})
    else:
        axis["format"] = ".2~f"
    return axis


def _is_count(specification: dict[str, Any]) -> bool:
    return specification.get("value_format") in {"count", "integer"} or (
        "nombre" in str(specification.get("value_label", "")).casefold()
        or "feedback" in str(specification.get("value_label", "")).casefold()
    )


def _chart_rows(specification: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for datum in specification.get("data", [])[:5]:
        value = datum.get("value")
        if not isinstance(value, Real) or isinstance(value, bool) or not isfinite(value) or value < 0:
            continue
        label = _enum_value(datum.get("label", ""))
        rows.append({"label": display_label(label), "value": value, "raw_label": label})
    return rows


def build_chart_spec(specification: dict[str, Any]) -> dict[str, Any] | None:
    """Build bounded charts with translated labels, stable colors and real units."""

    kind = _enum_value(specification.get("kind"))
    common = {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "config": _light_config(),
        "padding": {"left": 2, "right": 32, "top": 8, "bottom": 2},
    }
    value_label = str(specification.get("value_label") or "Valeur")
    if kind in {"bar", "donut"}:
        rows = _chart_rows(specification)
        if not rows:
            return None
        count = _is_count(specification)
        for row in rows:
            row["value_text"] = display_value(row["value"], "count" if count else "score")
        tooltip = [
            {"field": "label", "type": "nominal", "title": "Sujet"},
            {"field": "value", "type": "quantitative", "title": value_label, "format": "d" if count else ".2~f"},
        ]
        if kind == "bar":
            maximum = max(row["value"] for row in rows)
            return {
                **common,
                "height": max(70, 42 * len(rows)),
                "data": {"values": rows},
                "encoding": {
                    "y": {
                        "field": "label", "type": "nominal", "title": None,
                        "sort": [row["label"] for row in rows],
                        "axis": {"labelLimit": 230, "labelPadding": 10},
                    },
                    "x": {
                        "field": "value", "type": "quantitative", "title": value_label,
                        "scale": {"zero": True, "domainMin": 0, "domainMax": max(1, maximum * 1.14)},
                        "axis": _numeric_axis(maximum, count=count),
                    },
                    "tooltip": tooltip,
                },
                "layer": [
                    {"mark": {"type": "bar", "size": 22, "cornerRadiusEnd": 4, "color": "#087f81"}},
                    {"mark": {"type": "text", "align": "left", "dx": 6, "color": "#334155", "fontSize": 12},
                     "encoding": {"text": {"field": "value_text", "type": "nominal"}}},
                ],
            }
        total = sum(row["value"] for row in rows)
        if total <= 0:
            return None
        for row in rows:
            row["share"] = row["value"] / total
            row["share_text"] = display_value(100 * row["share"], "percent")
        colors = [SENTIMENT_COLORS.get(row["raw_label"], SERIES_COLORS[index % 4]) for index, row in enumerate(rows)]
        return {
            **common,
            "height": 190,
            "data": {"values": rows},
            "encoding": {
                "theta": {"field": "value", "type": "quantitative", "stack": True},
                "order": {"field": "raw_label", "type": "nominal"},
                "color": {
                    "field": "label", "type": "nominal", "title": None,
                    "scale": {"domain": [row["label"] for row in rows], "range": colors},
                },
                "tooltip": [*tooltip, {"field": "share", "type": "quantitative", "title": "Part", "format": ".1%"}],
            },
            "layer": [
                {"mark": {"type": "arc", "innerRadius": 55, "outerRadius": 88, "stroke": "#ffffff", "strokeWidth": 2}},
                {"mark": {"type": "text", "radius": 72, "fill": "#ffffff", "fontSize": 11, "fontWeight": "bold"},
                 "encoding": {"text": {"condition": {"test": "datum.share >= 0.09", "field": "share_text", "type": "nominal"}, "value": ""}}},
            ],
        }
    if kind == "line":
        periods = ["comparison", "current"]
        period_labels = specification.get("period_labels") or {}
        labels_by_period = {period: str(period_labels.get(period) or display_label(period)) for period in periods}
        rows = []
        for index, series in enumerate(specification.get("series", [])[:4]):
            for point in series.get("points", []):
                period = point.get("period")
                value = point.get("value")
                if period not in periods or not isinstance(value, Real) or not isfinite(value) or value < 0:
                    continue
                if point.get("label") or point.get("period_label"):
                    labels_by_period[period] = str(point.get("label") or point["period_label"])
                rows.append({"series": display_label(series.get("label")), "series_id": str(series.get("cluster_id") or index),
                             "period": period, "value": value, "order": periods.index(period)})
        if not rows:
            return None
        for row in rows:
            row["period_label"] = labels_by_period[row["period"]]
        return {
            **common,
            "height": 200,
            "data": {"values": rows},
            "mark": {"type": "line", "point": {"filled": True, "size": 65}, "strokeWidth": 2.5},
            "encoding": {
                "x": {"field": "period_label", "type": "ordinal", "sort": [labels_by_period[period] for period in periods],
                      "title": None, "axis": {"labelAngle": 0, "labelLimit": 280}},
                "y": {"field": "value", "type": "quantitative", "title": value_label,
                      "scale": {"zero": True}, "axis": _numeric_axis(max(row["value"] for row in rows), count=True)},
                "color": {"field": "series", "type": "nominal", "title": None, "scale": {"range": SERIES_COLORS}},
                "detail": {"field": "series_id", "type": "nominal"},
                "order": {"field": "order", "type": "quantitative"},
                "tooltip": [
                    {"field": "series", "type": "nominal", "title": "Signal"},
                    {"field": "period_label", "type": "nominal", "title": "Période"},
                    {"field": "value", "type": "quantitative", "title": value_label, "format": "d"},
                ],
            },
        }
    return None


def render_table_html(specification: dict[str, Any]) -> str:
    """Render a compact, accessible light-theme table; escape every API value."""

    columns = specification.get("columns", [])[:8]
    rows = specification.get("rows", [])[:10]
    title = escape(str(specification.get("title") or "Synthèse des signaux"), quote=True)
    parts = [f'<div class="report-table-wrap" role="region" aria-label="{title}" tabindex="0">',
             '<table class="report-table"><thead><tr>']
    for column in columns:
        parts.append(f'<th scope="col">{escape(display_label(column.get("label")))}</th>')
    parts.append("</tr></thead><tbody>")
    for row in rows:
        parts.append("<tr>")
        for column in columns:
            key = _enum_value(column.get("key"))
            value = row.get(key)
            css_class = ""
            if key == "confidence" and isinstance(value, Real):
                text = display_value(value * 100, "percent")
                css_class = ' class="report-table-number"'
            elif key in {"feedback_count", "priority_score"}:
                text = display_value(value, "count" if key == "feedback_count" else "score")
                css_class = ' class="report-table-number"'
            else:
                text = display_label(value)
            if key == "signal":
                css_class = ' class="report-table-signal"'
            parts.append(f"<td{css_class}>{escape(text)}</td>")
        parts.append("</tr>")
    if not rows:
        message = escape(str(specification.get("empty_message") or "Aucun signal disponible."))
        parts.append(f'<tr><td colspan="{max(1, len(columns))}">{message}</td></tr>')
    parts.append("</tbody></table></div>")
    return "".join(parts)
