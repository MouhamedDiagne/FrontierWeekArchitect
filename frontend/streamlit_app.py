"""Interface Streamlit locale du copilote Feedback Agiltym.

L'interface appelle exclusivement l'API HTTP locale. Elle n'importe pas le
package backend et ne contient aucun identifiant Azure, Foundry ou Dataverse.
"""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from itertools import count
import os
import re
from uuid import uuid4

import requests
import streamlit as st

from presentation import build_chart_spec, display_label, display_value, render_table_html


API_BASE_URL = os.getenv("FEEDBACK_API_URL", "http://127.0.0.1:8000").rstrip("/")
API_TIMEOUT_SECONDS = 120
_BLOCK_IDS = count()
QUICK_MESSAGE_PAYLOADS = (
    (
        "Analyse ce feedback concernant Targetym AI : « Le téléchargement du "
        "rapport produit un fichier vide dans Pilotage. »"
    ),
    (
        "Quels sont les principaux motifs d’insatisfaction sur Targetym AI au "
        "cours des 30 derniers jours ?"
    ),
    (
        "Prépare une synthèse Marketing sur l’ensemble des logiciels pour les "
        "30 derniers jours."
    ),
)


st.set_page_config(
    page_title="Agiltym Feedback Copilot",
    page_icon="✦",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# The prototype must also render when a Streamlit runner restores no widget
# state yet (for example on the very first page load).
if "conversation_id" not in st.session_state:
    st.session_state.conversation_id = None
if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant",
            "text": (
                "Je peux vous aider à analyser les retours clients, identifier "
                "des tendances et préparer des rapports adaptés à votre métier. "
                "Par quoi souhaitons-nous commencer ?"
            ),
        }
    ]
if "active_view" not in st.session_state:
    st.session_state.active_view = "assistant"
if "pending_message" not in st.session_state:
    st.session_state.pending_message = None


def inject_styles(dark_mode: bool) -> None:
    """Define the standalone visual identity of the prototype."""

    palette = (
        """
        --canvas: #111827; --surface: #192535; --surface-soft: #202e3f;
        --ink: #f5f8fb; --body: #c2ceda; --muted: #9aabbd;
        --accent: #50c9c0; --accent-strong: #79ded7; --accent-soft: #193f40;
        --line: #304153; --sidebar: #0b1320; --sidebar-surface: #17253a;
        --on-accent: #072728; --shadow: 0 6px 22px rgba(0,0,0,.18);
        """
        if dark_mode
        else """
        --canvas: #f7f9f9; --surface: #ffffff; --surface-soft: #f0f6f5;
        --ink: #182347; --body: #526273; --muted: #6d7b8a;
        --accent: #087f81; --accent-strong: #006e70; --accent-soft: #e3f2ef;
        --line: #dce5e5; --sidebar: #182347; --sidebar-surface: #27345f;
        --on-accent: #ffffff; --shadow: 0 6px 22px rgba(24,35,71,.055);
        """
    )

    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap');

        :root {
            __PALETTE__
        }

        * { font-family: 'DM Sans', sans-serif; }
        #MainMenu, footer, [data-testid="stHeader"] { display: none; }
        [data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] { display: none !important; }
        .stApp { background: var(--canvas); color: var(--ink); }
        .block-container {
            max-width: 1200px;
            padding: 1.15rem 2rem 1.85rem;
        }

        .eyebrow {
            color: var(--accent); font-size: .72rem; letter-spacing: .13em;
            text-transform: uppercase; font-weight: 700; margin-bottom: .38rem;
        }
        h1 {
            color: var(--ink); font-size: 2.15rem !important;
            line-height: 1.12 !important; margin: 0 !important;
        }
        .topbar {
            display: flex; align-items: center; justify-content: space-between;
            padding: .15rem 0 1.15rem; border-bottom: 1px solid var(--line);
            margin-bottom: 1.45rem;
        }
        .topbar-title { font-size: .88rem; color: var(--body); margin-top: .28rem; }
        .status-pill {
            display: inline-flex; gap: .42rem; align-items: center;
            background: var(--accent-soft); color: var(--accent-strong); border: 1px solid var(--line);
            border-radius: 999px; padding: .43rem .7rem; font-size: .75rem; font-weight: 700;
        }
        .status-dot { width: 7px; height: 7px; border-radius: 999px; background: var(--accent); }
        .st-key-primary_navigation {
            position: sticky; top: .35rem; z-index: 20; background: var(--canvas);
            padding: .35rem 0 .55rem; margin-bottom: .35rem;
        }
        .st-key-primary_navigation .stButton > button {
            min-height: 42px !important; padding: .42rem .75rem !important;
            text-align: center !important; justify-content: center !important;
        }
        .st-key-primary_navigation .stButton > button[kind="primary"] {
            background: var(--accent) !important; border-color: var(--accent) !important;
            color: var(--on-accent) !important;
        }

        .hero {
            background: var(--surface); border: 1px solid var(--line); border-radius: 18px; padding: 1.35rem 1.4rem;
            margin-bottom: 1rem; position: relative; overflow: hidden;
        }
        .hero:after {
            content: ''; position: absolute; width: 160px; height: 160px;
            background: var(--accent-soft); border-radius: 50%; right: -58px; top: -76px; opacity: .95;
        }
        .hero h2 { color: var(--ink); font-size: 1.2rem; margin: 0 0 .3rem; }
        .hero p { color: var(--body); margin: 0; max-width: 700px; font-size: .9rem; }
        .hero-mark { color: var(--accent); font-weight: 700; }

        .section-label { color: var(--muted); font-size: .72rem; font-weight: 700; text-transform: uppercase; letter-spacing: .1em; margin: .7rem 0 .5rem; }
        [data-testid="stMain"] .stButton > button,
        .stMain .stButton > button,
        section.main .stButton > button {
            background: var(--surface) !important; color: var(--ink) !important; border: 1px solid var(--line) !important;
            border-radius: 11px; padding: .55rem .6rem; min-height: 52px; font-size: .8rem;
            text-align: left; line-height: 1.25; font-weight: 600;
        }
        [data-testid="stMain"] .stButton > button:hover,
        .stMain .stButton > button:hover,
        section.main .stButton > button:hover { border-color: var(--accent) !important; color: var(--accent) !important; background: var(--accent-soft) !important; }

        [data-testid="stChatMessage"] {
            background: transparent; padding: .25rem 0 .4rem; gap: .6rem;
        }
        [data-testid="stChatMessage"] [data-testid="stChatMessageAvatarUser"] {
            background: var(--accent) !important; color: var(--on-accent) !important;
        }
        [data-testid="stChatMessage"] [data-testid="stChatMessageAvatarAssistant"] {
            background: var(--ink) !important; color: var(--surface) !important;
        }
        .assistant-response {
            background: var(--surface); border: 1px solid var(--line); border-radius: 6px 16px 16px 16px;
            padding: .9rem 1rem; box-shadow: var(--shadow);
        }
        .assistant-response p { margin: 0; color: var(--body); font-size: .9rem; line-height: 1.48; }
        .user-response {
            background: var(--accent); color: var(--on-accent); border-radius: 16px 6px 16px 16px;
            padding: .68rem .85rem; width: fit-content; max-width: 85%; margin-left: auto;
            font-size: .9rem;
        }
        .result-card {
            background: var(--surface-soft); border: 1px solid var(--line); border-left: 3px solid var(--accent);
            border-radius: 10px; padding: .8rem .9rem; margin-top: .7rem;
        }
        .result-title { color: var(--ink); font-size: .77rem; font-weight: 700; margin-bottom: .55rem; }
        .result-row { display: flex; flex-wrap: wrap; gap: .45rem; }
        .tag { display: inline-block; padding: .25rem .48rem; border-radius: 999px; font-size: .69rem; font-weight: 700; }
        .tag-primary { color: var(--accent-strong); background: var(--accent-soft); }
        .tag-neutral { color: var(--body); background: var(--surface); border: 1px solid var(--line); }
        .result-summary { color: var(--body); font-size: .79rem; margin-top: .62rem; }

        .context-card {
            background: var(--surface); color: var(--ink); border: 1px solid var(--line); border-top: 3px solid var(--accent);
            border-radius: 16px; padding: 1rem 1.05rem; margin-top: .45rem;
        }
        .context-title { font-size: .75rem; color: var(--accent); letter-spacing: .1em; text-transform: uppercase; font-weight: 700; }
        .context-card h3 { color: var(--ink); font-size: 1rem; margin: .35rem 0 .75rem; }
        .context-line { border-top: 1px solid var(--line); padding: .65rem 0 0; margin-top: .55rem; }
        .context-line span { display: block; color: var(--muted); font-size: .7rem; margin-bottom: .18rem; }
        .context-line strong { color: var(--ink); font-size: .83rem; font-weight: 600; }
        .info-card {
            background: var(--surface); border: 1px solid var(--line); border-radius: 15px; padding: 1rem;
            margin-top: .9rem;
        }
        .info-card h3 { font-size: .9rem; color: var(--ink); margin: 0 0 .65rem; }
        .info-item { display: flex; gap: .5rem; align-items: flex-start; margin: .55rem 0; color: var(--body); font-size: .77rem; line-height: 1.32; }
        .info-dot { color: var(--accent); font-size: .9rem; margin-top: -.1rem; }
        [data-testid="stChatInput"] { padding-top: .55rem; }
        [data-testid="stChatInput"] textarea {
            background: var(--surface) !important; color: var(--ink) !important; border: 1px solid var(--line) !important;
            border-radius: 13px !important; box-shadow: var(--shadow) !important;
        }
        [data-testid="stChatInput"] textarea::placeholder { color: var(--muted) !important; }
        .analysis-progress {
            display: flex; align-items: center; gap: .55rem; color: var(--body);
            background: var(--surface-soft); border: 1px solid var(--line); border-radius: 11px;
            padding: .62rem .78rem; margin: .7rem 0 .35rem; font-size: .82rem;
        }
        .analysis-progress-dot {
            width: 8px; height: 8px; border-radius: 50%; background: var(--accent);
            box-shadow: 0 0 0 4px var(--accent-soft); animation: pulse 1.1s ease-in-out infinite;
        }
        @keyframes pulse { 50% { opacity: .45; transform: scale(.78); } }
        .visualization-heading {
            color: var(--ink); font-size: .92rem; font-weight: 700; margin: .5rem 0 .1rem;
        }
        .visualization-caption { color: var(--body); font-size: .79rem; margin: 0 0 .15rem; }
        .visualization-legend { color: var(--muted); font-size: .73rem; margin: .15rem 0 0; }
        [data-testid="stVerticalBlockBorderWrapper"] {
            background: var(--surface); border-color: var(--line) !important; border-radius: 14px;
            margin: .35rem 0 !important;
        }
        [data-testid="stVegaLiteChart"] { margin: 0 !important; }
        /* Native Streamlit components must use the same palette as the page,
           including when a browser previously selected Streamlit's dark theme. */
        .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5,
        .stApp h6, [data-testid="stMetricValue"], [data-testid="stMetricLabel"] {
            color: var(--ink) !important;
        }
        [data-testid="stMarkdownContainer"], [data-testid="stCaptionContainer"],
        [data-testid="stWidgetLabel"], [data-testid="stExpander"] summary {
            color: var(--body) !important;
        }
        [data-testid="stMainBlockContainer"] { padding-top: .65rem; }
        .st-key-primary_navigation {
            top: 0; padding: .65rem 0; margin-bottom: .4rem;
            border-bottom: 1px solid var(--line);
        }
        .nav-brand { color: var(--ink); font-size: 1rem; font-weight: 700; }
        .nav-brand span { color: var(--accent); }
        .st-key-primary_navigation button,
        [data-testid="stPopover"] button {
            min-height: 40px !important; font-size: .82rem !important;
            background: var(--surface); color: var(--ink);
            border: 1px solid var(--line); border-radius: 10px;
        }
        [data-testid="stPopoverBody"] {
            background: var(--surface); color: var(--ink); border-color: var(--line);
        }
        [data-baseweb="select"] > div,
        [data-baseweb="popover"] [role="listbox"],
        [data-baseweb="popover"] [role="option"] {
            background: var(--surface) !important; color: var(--ink) !important;
        }
        [data-baseweb="select"] input { color: var(--ink) !important; }
        [data-testid="stChatInput"] {
            background: var(--surface) !important; border: 1px solid var(--line);
            border-radius: 14px; padding: .35rem !important;
        }
        [data-testid="stChatInput"] > div { background: var(--surface) !important; }
        [data-testid="stChatInput"] textarea { border: 0 !important; box-shadow: none !important; }
        [data-testid="stChatInputSubmitButton"] { color: var(--accent) !important; }
        [class*="st-key-response_"] {
            background: var(--surface); border: 1px solid var(--line);
            border-radius: 6px 16px 16px 16px; padding: 1rem 1.2rem;
        }
        [class*="st-key-response_"] h1, [class*="st-key-response_"] h2,
        [class*="st-key-response_"] h3, [class*="st-key-response_"] h4 {
            font-size: 1.07rem !important; line-height: 1.4 !important;
            padding: .4rem 0 .2rem !important; margin: .4rem 0 .15rem !important;
        }
        [class*="st-key-response_"] p, [class*="st-key-response_"] li {
            color: var(--body); font-size: .94rem; line-height: 1.6;
        }
        [class*="st-key-response_"] p:last-child { margin-bottom: 0; }
        [class*="st-key-visual_"] {
            background: var(--surface); border: 1px solid var(--line);
            border-radius: 14px; padding: .85rem 1rem; margin: .1rem 0;
        }
        [class*="st-key-visual_"] > [data-testid="stVerticalBlock"] { gap: .45rem; }
        .visual-title { color: var(--ink); font-size: .97rem; font-weight: 700; margin: 0; }
        .visualization-caption { line-height: 1.45; margin: .2rem 0; }
        .visualization-legend { line-height: 1.4; margin: .1rem 0; }
        .kpi-card { min-height: 104px; }
        .kpi-label { color: var(--body); font-size: .78rem; font-weight: 600; margin-bottom: .2rem; }
        .kpi-value { color: var(--ink); font-size: 1.8rem; font-weight: 700; line-height: 1.25; }
        .kpi-note { color: var(--muted); font-size: .73rem; line-height: 1.4; margin-top: .3rem; }
        .single-datum { display: flex; align-items: center; gap: 1rem; padding: .55rem 0; }
        .single-value { color: var(--accent-strong); font-size: 1.7rem; font-weight: 700; white-space: nowrap; }
        .single-label { color: var(--ink); font-size: .9rem; line-height: 1.4; overflow-wrap: anywhere; }
        .single-note { color: var(--muted); font-size: .76rem; margin-top: .1rem; }
        .report-table-wrap { overflow-x: auto; border: 1px solid var(--line); border-radius: 10px; }
        .report-table { width: 100%; border-collapse: collapse; font-size: .79rem; background: var(--surface); color: var(--body); }
        .report-table th { background: var(--surface-soft); color: var(--ink); text-align: left; font-weight: 600; }
        .report-table td, .report-table th { padding: .65rem .75rem; border-bottom: 1px solid var(--line); vertical-align: top; }
        .report-table tr:last-child td { border-bottom: 0; }
        .report-table-signal { min-width: 230px; max-width: 420px; white-space: normal; overflow-wrap: anywhere; }
        .report-table-number { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
        .demo-note {
            text-align: center; color: var(--muted); font-size: .68rem; margin: .75rem 0 0;
        }
        @media(max-width: 900px) {
            .block-container { padding: 1rem; }
            h1 { font-size: 1.72rem !important; }
        }
        </style>
        """.replace("__PALETTE__", palette),
        unsafe_allow_html=True,
    )


def _api_request(
    method: str,
    path: str,
    *,
    payload: dict[str, object] | None = None,
    not_found_message: str | None = None,
) -> dict[str, object]:
    """Call the local API without exposing backend details to the UI."""

    try:
        response = requests.request(
            method,
            f"{API_BASE_URL}{path}",
            json=payload,
            timeout=API_TIMEOUT_SECONDS,
        )
    except requests.RequestException as error:
        raise RuntimeError(
            "Le backend local est indisponible. Démarrez l'API puis réessayez."
        ) from error

    if response.status_code == 404:
        raise RuntimeError(
            not_found_message
            or "Cette conversation n'est plus disponible. Démarrez une nouvelle conversation."
        )
    if not response.ok:
        raise RuntimeError(
            f"Le backend n'a pas pu traiter la demande (HTTP {response.status_code})."
        )
    if response.status_code == 204:
        return {}
    return response.json()


def _now_label() -> str:
    """Return a compact local label used only in the browser-session history."""

    return datetime.now().strftime("%d/%m · %H:%M:%S")


def _initial_conversation_messages() -> list[dict[str, object]]:
    return [
        {
            "role": "assistant",
            "text": "Nouvelle conversation prête. Comment puis-je vous aider ?",
        }
    ]


def _new_conversation_record() -> dict[str, object]:
    """Create browser-session metadata without creating a remote session yet."""

    timestamp = _now_label()
    return {
        "conversation_id": None,
        "messages": _initial_conversation_messages(),
        "title": "Nouvelle conversation",
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def _sync_legacy_conversation_state() -> None:
    """Keep the former state keys available while the UI migrates to history."""

    records = st.session_state.conversation_history
    active_key = st.session_state.active_conversation_key
    active = records[active_key]
    st.session_state.conversation_id = active.get("conversation_id")
    st.session_state.messages = active["messages"]


def _ensure_conversation_history() -> None:
    """Migrate the original single-session UI into a local session history."""

    records = st.session_state.get("conversation_history")
    active_key = st.session_state.get("active_conversation_key")
    if isinstance(records, dict) and records:
        if not isinstance(active_key, str) or active_key not in records:
            st.session_state.active_conversation_key = next(iter(records))
        _sync_legacy_conversation_state()
        return

    key = uuid4().hex
    legacy_messages = st.session_state.get("messages")
    messages = (
        legacy_messages
        if isinstance(legacy_messages, list) and legacy_messages
        else _initial_conversation_messages()
    )
    timestamp = _now_label()
    st.session_state.conversation_history = {
        key: {
            "conversation_id": st.session_state.get("conversation_id"),
            "messages": messages,
            "title": "Nouvelle conversation",
            "created_at": timestamp,
            "updated_at": timestamp,
        }
    }
    st.session_state.active_conversation_key = key
    st.session_state.conversation_selector = key
    _sync_legacy_conversation_state()


def _active_conversation_record() -> dict[str, object]:
    _ensure_conversation_history()
    return st.session_state.conversation_history[
        st.session_state.active_conversation_key
    ]


def _conversation_label(conversation_key: str) -> str:
    record = st.session_state.conversation_history[conversation_key]
    title = str(record.get("title") or "Nouvelle conversation")
    updated_at = str(record.get("updated_at") or "")
    return f"{title[:46]} · {updated_at}" if updated_at else title[:46]


def _conversation_option_map() -> dict[str, str]:
    """Build human-readable, unique selectbox labels for local sessions."""

    labels: dict[str, str] = {}
    for position, conversation_key in enumerate(
        reversed(st.session_state.conversation_history),
        start=1,
    ):
        label = _conversation_label(conversation_key)
        if label in labels:
            label = f"{label} · {position}"
        labels[label] = conversation_key
    st.session_state.conversation_option_map = labels
    return labels


def _activate_conversation(conversation_key: str) -> None:
    if conversation_key not in st.session_state.conversation_history:
        return
    st.session_state.active_conversation_key = conversation_key
    st.session_state.pending_message = None
    _sync_legacy_conversation_state()


def _on_conversation_selected() -> None:
    selected_label = st.session_state.get("conversation_selector")
    option_map = st.session_state.get("conversation_option_map")
    if isinstance(selected_label, str) and isinstance(option_map, dict):
        selected = option_map.get(selected_label)
        if isinstance(selected, str):
            _activate_conversation(selected)
            st.session_state.active_view = "assistant"


def _start_new_conversation() -> None:
    """Keep old local/remote sessions available and switch to a blank one."""

    _ensure_conversation_history()
    conversation_key = uuid4().hex
    st.session_state.conversation_history[conversation_key] = _new_conversation_record()
    _activate_conversation(conversation_key)
    # The history selector may already be instantiated when a
    # header action creates a session.  Defer its visual update to the next
    # rerun, before Streamlit creates the selectbox again.
    st.session_state.conversation_selector_needs_sync = True


def _sync_conversation_selector_before_widgets() -> None:
    """Synchronize the history selector only before its widget is created."""

    if not st.session_state.pop("conversation_selector_needs_sync", False):
        return

    labels = _conversation_option_map()
    active_key = st.session_state.active_conversation_key
    st.session_state.conversation_selector = next(
        label for label, key in labels.items() if key == active_key
    )


def _primary_navigation() -> None:
    """Keep navigation and session history in the page, without a sidebar."""

    with st.container(key="primary_navigation"):
        brand, new_conversation_column, dashboard_column, history_column = st.columns(
            [1.5, 1.45, 1.0, 1.1],
            vertical_alignment="center",
        )
        with brand:
            st.markdown('<div class="nav-brand">Agiltym <span>· Feedback</span></div>', unsafe_allow_html=True)
        with new_conversation_column:
            if st.button(
                "＋ Nouvelle conversation",
                key="main_new_conversation",
                type="primary",
                width="stretch",
            ):
                _start_new_conversation()
                st.session_state.active_view = "assistant"
                st.rerun()

        with dashboard_column:
            on_dashboard = st.session_state.active_view == "dashboard"
            dashboard_label = "← Assistant" if on_dashboard else "▦ Dashboard"
            if st.button(
                dashboard_label,
                key="main_dashboard_navigation",
                width="stretch",
            ):
                st.session_state.active_view = (
                    "assistant" if on_dashboard else "dashboard"
                )
                st.rerun()

        with history_column:
            history_count = len(st.session_state.conversation_history)
            with st.popover(f"Historique ({history_count})", width="stretch"):
                st.markdown("**Vos conversations**")
                conversation_options = _conversation_option_map()
                active_label = next(
                    label for label, key in conversation_options.items()
                    if key == st.session_state.active_conversation_key
                )
                # Labels can change after the first message; the active UUID is
                # the source of truth, before this selectbox is instantiated.
                st.session_state.conversation_selector = active_label
                st.selectbox(
                    "Reprendre une conversation",
                    options=list(conversation_options),
                    key="conversation_selector",
                    on_change=_on_conversation_selected,
                )
                st.caption("Historique conservé pendant cette session de navigateur.")


def _message_title(text: str) -> str:
    normalized = " ".join(text.split())
    if not normalized:
        return "Nouvelle conversation"
    return f"{normalized[:44]}…" if len(normalized) > 44 else normalized


def _append_active_message(message: dict[str, object]) -> None:
    """Append one UI message to the selected local conversation safely."""

    record = _active_conversation_record()
    messages = record.get("messages")
    if not isinstance(messages, list):
        messages = _initial_conversation_messages()
        record["messages"] = messages
    messages.append(message)

    if message.get("role") == "user":
        text = message.get("text")
        if isinstance(text, str) and str(record.get("title")) == "Nouvelle conversation":
            record["title"] = _message_title(text)
    record["updated_at"] = _now_label()
    _sync_legacy_conversation_state()


def _queue_message(message: str) -> None:
    """Queue a quick prompt or typed message for the next stable UI run."""

    normalized = message.strip()
    if normalized:
        st.session_state.pending_message = normalized


def _ensure_conversation() -> str:
    record = _active_conversation_record()
    conversation_id = record.get("conversation_id")
    if isinstance(conversation_id, str) and conversation_id:
        return conversation_id

    created = _api_request("POST", "/api/conversations")
    session_id = created.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        raise RuntimeError("Le backend a renvoyé une conversation invalide.")
    record["conversation_id"] = session_id
    record["updated_at"] = _now_label()
    _sync_legacy_conversation_state()
    return session_id


def _reset_conversation() -> None:
    conversation_id = st.session_state.conversation_id
    if isinstance(conversation_id, str) and conversation_id:
        try:
            _api_request("DELETE", f"/api/conversations/{conversation_id}")
        except RuntimeError:
            # The local API may have restarted. The local Streamlit state can
            # still be safely reset because it contains no backend credential.
            pass
    st.session_state.conversation_id = None
    st.session_state.messages = [
        {
            "role": "assistant",
            "text": "Nouvelle conversation prête. Comment puis-je vous aider ?",
        }
    ]


def _analysis_card(analysis: dict[str, object]) -> None:
    """Render a safe, server-supplied feedback analysis summary."""

    functionality = analysis.get("primary_functionality")
    functionality_name = (
        functionality.get("name")
        if isinstance(functionality, dict) and isinstance(functionality.get("name"), str)
        else "Fonctionnalité non déterminée"
    )
    problem_category = analysis.get("problem_category") or "À qualifier"
    if isinstance(problem_category, str):
        problem_category = problem_category.replace("_", " ")
    sentiment = analysis.get("sentiment", "non déterminé")
    summary = analysis.get("feedback_summary", "")

    st.markdown(
        "<div class=\"result-card\">"
        "<div class=\"result-title\">LECTURE RAPIDE DU SIGNAL</div>"
        "<div class=\"result-row\">"
        f"<span class=\"tag tag-primary\">{escape(str(sentiment))}</span>"
        f"<span class=\"tag tag-neutral\">{escape(str(problem_category))}</span>"
        f"<span class=\"tag tag-neutral\">{escape(functionality_name)}</span>"
        "</div>"
        f"<div class=\"result-summary\">{escape(str(summary))}</div>"
        "</div>",
        unsafe_allow_html=True,
    )


def _insights_card(insights: dict[str, object]) -> None:
    total = insights.get("total_feedbacks", 0)
    clustered = insights.get("clustered_feedbacks", 0)
    clusters = insights.get("clusters", [])
    cluster_count = len(clusters) if isinstance(clusters, list) else 0
    st.markdown(
        "<div class=\"result-card\">"
        "<div class=\"result-title\">RÉSULTAT DE L'ANALYSE HISTORIQUE</div>"
        "<div class=\"result-row\">"
        f"<span class=\"tag tag-primary\">{escape(str(total))} feedbacks</span>"
        f"<span class=\"tag tag-neutral\">{escape(str(clustered))} regroupés</span>"
        f"<span class=\"tag tag-neutral\">{escape(str(cluster_count))} clusters</span>"
        "</div>"
        "</div>",
        unsafe_allow_html=True,
    )


_VISUALIZATION_MARKER = re.compile(r"\[\[visual:([A-Za-z0-9_-]{1,80})\]\]")


def _visualization_specs(bundle: dict[str, object]) -> list[dict[str, object]]:
    specifications = bundle.get("visualizations")
    if not isinstance(specifications, list):
        return []
    return [item for item in specifications if isinstance(item, dict)]


def _visualization_legend(specification: dict[str, object]) -> str | None:
    """Return a compact, text-only legend from the safe backend contract."""

    legend = specification.get("legend")
    if isinstance(legend, str) and legend.strip():
        return legend.strip()
    if isinstance(legend, list):
        values: list[str] = []
        for item in legend:
            if isinstance(item, dict):
                label = item.get("label")
                description = item.get("description")
                if not isinstance(label, str) or not label.strip():
                    continue
                if isinstance(description, str) and description.strip():
                    values.append(f"{label.strip()} — {description.strip()}")
                else:
                    values.append(label.strip())
            elif isinstance(item, str) and item.strip():
                values.append(item.strip())
        if values:
            return " · ".join(values)
    if isinstance(legend, dict):
        values = [
            f"{key} : {value}"
            for key, value in legend.items()
            if str(key).strip() and str(value).strip()
        ]
        if values:
            return " · ".join(values)
    value_label = specification.get("value_label")
    return value_label.strip() if isinstance(value_label, str) and value_label.strip() else None


def _render_visualization_spec(specification: dict[str, object]) -> bool:
    """Render bounded backend data with a consistent light presentation."""

    kind = specification.get("kind")
    if kind not in {"kpi", "bar", "donut", "line", "table"}:
        return False
    title = str(specification.get("title") or "Visualisation")
    caption = specification.get("caption")
    with st.container(key=f"visual_{next(_BLOCK_IDS)}"):
        if kind == "kpi":
            value = display_value(specification.get("value"), specification.get("value_format"))
            # Keep the denominator/qualification visible, avoid two paragraphs
            # repeating the same metric description below every number.
            note = specification.get("subtitle") or caption or ""
            st.markdown(
                f'<div class="kpi-card"><div class="kpi-label">{escape(title)}</div>'
                f'<div class="kpi-value">{escape(value)}</div>'
                f'<div class="kpi-note">{escape(str(note))}</div></div>',
                unsafe_allow_html=True,
            )
            return True

        st.markdown(f'<div class="visual-title">{escape(title)}</div>', unsafe_allow_html=True)
        if isinstance(caption, str) and caption:
            st.markdown(f'<p class="visualization-caption">{escape(caption)}</p>', unsafe_allow_html=True)

        if kind == "table":
            st.markdown(render_table_html(specification), unsafe_allow_html=True)
        else:
            data = specification.get("data")
            rows = [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []
            nonzero_rows = [row for row in rows if isinstance(row.get("value"), (int, float)) and row["value"] > 0]
            if kind == "donut" and not nonzero_rows:
                st.caption("Aucun sentiment renseigné pour cette période.")
                return True
            visible_rows = nonzero_rows if kind == "donut" else rows
            if kind in {"bar", "donut"} and len(visible_rows) == 1:
                row = visible_rows[0]
                value = display_value(row.get("value"))
                label = display_label(row.get("label"))
                if kind == "donut":
                    value = "100 %"
                    note = f"{display_value(row.get('value'), 'count')} feedback(s) parmi les sentiments renseignés."
                else:
                    note = str(specification.get("value_label") or "")
                st.markdown(
                    f'<div class="single-datum"><div class="single-value">{escape(value)}</div>'
                    f'<div><div class="single-label">{escape(label)}</div>'
                    f'<div class="single-note">{escape(note)}</div></div></div>',
                    unsafe_allow_html=True,
                )
                return True
            chart = build_chart_spec(specification)
            if chart is None:
                st.caption("Aucune donnée à représenter.")
                return True
            st.vega_lite_chart(
                spec=chart, theme=None, width="stretch",
                height="content", key=f"chart_{next(_BLOCK_IDS)}",
            )

        # Donut legends are already integrated in the chart; do not repeat the
        # entire distribution below it. Tables retain score explanations.
        if kind != "donut":
            legend = _visualization_legend(specification)
            if legend:
                st.markdown(
                    f'<p class="visualization-legend">{escape(legend)}</p>',
                    unsafe_allow_html=True,
                )
    return True


def _render_visualizations(
    bundle: dict[str, object],
    *,
    exclude_ids: set[str] | None = None,
    show_heading: bool = True,
) -> set[str]:
    """Lay out remaining KPIs and small charts without duplicating inline ones."""

    excluded = exclude_ids or set()
    specifications = [
        item for item in _visualization_specs(bundle)
        if isinstance(item.get("id"), str) and item["id"] not in excluded
    ]
    if not specifications:
        return set()
    if show_heading:
        st.markdown('<div class="visualization-heading">Repères chiffrés</div>', unsafe_allow_html=True)
    rendered_ids: set[str] = set()

    def render(item: dict[str, object]) -> None:
        if _render_visualization_spec(item):
            rendered_ids.add(str(item["id"]))

    kpis = [item for item in specifications if item.get("kind") == "kpi"]
    for offset in range(0, len(kpis), 4):
        group = kpis[offset:offset + 4]
        for column, item in zip(st.columns(len(group), gap="small"), group):
            with column:
                render(item)

    remaining = [item for item in specifications if item.get("kind") != "kpi"]
    index = 0
    while index < len(remaining):
        item = remaining[index]
        next_item = remaining[index + 1] if index + 1 < len(remaining) else None
        if item.get("kind") in {"bar", "donut"} and next_item and next_item.get("kind") in {"bar", "donut"}:
            for column, entry in zip(st.columns(2, gap="small"), [item, next_item]):
                with column:
                    render(entry)
            index += 2
        else:
            render(item)
            index += 1
    return rendered_ids


def _render_assistant_text_with_visualizations(
    text: str,
    bundle: dict[str, object] | None,
) -> set[str]:
    """Place safe charts after model-produced markers, with a bounded fallback."""

    specs_by_id = {
        str(specification["id"]): specification
        for specification in _visualization_specs(bundle or {})
        if isinstance(specification.get("id"), str)
    }
    placed: set[str] = set()
    cursor = 0
    for match in _VISUALIZATION_MARKER.finditer(text):
        paragraph = text[cursor:match.start()].strip()
        if paragraph:
            _assistant_text_block(paragraph)
        visual_id = match.group(1)
        specification = specs_by_id.get(visual_id)
        if (
            visual_id not in placed
            and specification
            and _render_visualization_spec(specification)
        ):
            placed.add(visual_id)
        cursor = match.end()

    remaining_text = text[cursor:].strip()
    if remaining_text:
        _assistant_text_block(remaining_text)
    elif not text.strip() and not placed:
        _assistant_text_block("La réponse de l’assistant est vide.")
    return placed


def _assistant_text_block(text: str) -> None:
    # Native Markdown renders headings, lists and emphasis. Model HTML stays
    # disabled, unlike our fixed and escaped UI templates.
    with st.container(key=f"response_{next(_BLOCK_IDS)}"):
        st.markdown(text, unsafe_allow_html=False)


def _readable_date(value: object, *, include_time: bool = False) -> str:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return "Date indisponible"
    if include_time and parsed.tzinfo:
        return parsed.astimezone(timezone.utc).strftime("%d/%m/%Y à %H:%M UTC")
    return parsed.strftime("%d/%m/%Y")


def _dashboard_view() -> None:
    """Read and display the latest snapshot without re-running clustering."""

    st.markdown(
        """
        <div class="topbar">
          <div>
            <div class="eyebrow">Agiltym · Customer intelligence</div>
            <h1>Dashboard insights</h1>
            <div class="topbar-title">Vue en lecture seule du dernier rapport historique enregistré.</div>
          </div>
          <div class="status-pill"><span class="status-dot"></span> Dernière analyse enregistrée</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    try:
        payload = _api_request(
            "GET",
            "/api/dashboard/latest",
            not_found_message=(
                "Aucune analyse historique enregistrée n'est disponible. "
                "Demandez d'abord un rapport dans l'assistant."
            ),
        )
    except RuntimeError as error:
        st.info(str(error))
        st.caption(
            "Le dashboard ne relance pas le clustering : il affichera le dernier "
            "snapshot lorsque la table Dataverse des analyses sera configurée."
        )
        return

    snapshot = payload.get("snapshot")
    visualizations = payload.get("visualizations")
    if not isinstance(snapshot, dict) or not isinstance(visualizations, dict):
        st.error("Le backend a renvoyé un dashboard invalide.")
        return
    report = snapshot.get("audience_report")
    if not isinstance(report, dict):
        st.error("Le snapshot ne contient pas le rapport attendu.")
        return
    scope = report.get("scope") if isinstance(report.get("scope"), dict) else {}
    insights = snapshot.get("insights")
    request = insights.get("request", {}) if isinstance(insights, dict) else {}
    period = (
        f"{_readable_date(request['start_date'])} → {_readable_date(request['end_date'])} (fin exclue)"
        if isinstance(request, dict) and request.get("start_date") and request.get("end_date")
        else str(scope.get("period", "Non définie")).replace(" to ", " → ")
    )
    source_labels = {"conversation": "Conversation", "manual": "Analyse manuelle", "scheduled": "Analyse planifiée"}
    software_labels = {"targetym_ai": "Targetym AI", "bleom_vie": "Bleom Vie", "dealym_crm": "Dealym CRM", "ohady_ai": "Ohady AI"}
    st.caption(
        f"Généré le {_readable_date(snapshot.get('generated_at'), include_time=True)} · "
        f"{source_labels.get(snapshot.get('source'), 'Source non précisée')} · "
        f"Profil {display_label(report.get('profile'))}"
    )
    st.caption(
        f"Période : {period} · "
        f"{software_labels.get(scope.get('software_id'), scope.get('software_id') or 'Toutes les solutions')}"
    )
    focus = report.get("executive_focus")
    if isinstance(focus, str) and focus:
        st.subheader("Lecture adaptée au profil")
        st.write(focus)
    _render_visualizations(visualizations)
    limitations = visualizations.get("limitations")
    if isinstance(limitations, list) and limitations:
        with st.expander("Limites et qualité des données"):
            for limitation in limitations:
                st.write(f"- {limitation}")


def _live_assistant_message(message: dict[str, object]) -> None:
    text = str(message.get("text", ""))
    with st.chat_message("assistant", avatar="✨"):
        visualizations = message.get("visualizations")
        placed_visualization_ids = _render_assistant_text_with_visualizations(
            text,
            visualizations if isinstance(visualizations, dict) else None,
        )
        analysis = message.get("analysis")
        if isinstance(analysis, dict):
            _analysis_card(analysis)
        insights = message.get("insights")
        if isinstance(insights, dict) and not isinstance(visualizations, dict):
            _insights_card(insights)
        if isinstance(visualizations, dict):
            _render_visualizations(
                visualizations,
                exclude_ids=placed_visualization_ids,
                show_heading=not placed_visualization_ids,
            )


def _live_user_message(message: dict[str, object]) -> None:
    with st.chat_message("user", avatar="👤"):
        st.markdown(
            f'<div class="user-response">{escape(str(message.get("text", "")))}</div>',
            unsafe_allow_html=True,
        )


def live_main() -> None:
    """Run the connected POC while preserving the existing visual design."""

    _ensure_conversation_history()
    _sync_conversation_selector_before_widgets()
    inject_styles(False)

    _primary_navigation()

    if st.session_state.active_view == "dashboard":
        _dashboard_view()
        return

    st.markdown(
        """
        <div class="topbar">
          <div>
            <div class="eyebrow">Agiltym · Customer intelligence</div>
            <h1>Bonjour, comment puis-je vous aider&nbsp;?</h1>
            <div class="topbar-title">Interrogez les retours clients et transformez-les en décisions utiles.</div>
          </div>
          <div class="status-pill"><span class="status-dot"></span> Assistant</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.container(key="conversation_content"):
        st.markdown(
            """
            <div class="hero">
              <h2>Votre copilote pour comprendre la <span class="hero-mark">voix de vos clients</span>.</h2>
              <p>Analysez un retour, explorez un signal récurrent ou préparez une synthèse adaptée à votre équipe.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="section-label">Essayez une question</div>',
            unsafe_allow_html=True,
        )

        prompts = [
            "Analyser un retour client",
            "Identifier les insatisfactions",
            "Préparer une synthèse Marketing",
        ]
        for index, (column, prompt) in enumerate(zip(st.columns(3, gap="small"), prompts)):
            with column:
                if st.button(prompt, key=f"live_prompt_{prompt}", width="stretch"):
                    _queue_message(QUICK_MESSAGE_PAYLOADS[index])

        st.markdown('<div class="section-label">Conversation</div>', unsafe_allow_html=True)
        active_messages = _active_conversation_record().get("messages")
        if not isinstance(active_messages, list):
            active_messages = []
        for saved_message in active_messages:
            if not isinstance(saved_message, dict):
                continue
            if saved_message.get("role") == "user":
                _live_user_message(saved_message)
            else:
                _live_assistant_message(saved_message)

        queued_message = st.session_state.get("pending_message")
        if not isinstance(queued_message, str) or not queued_message.strip():
            queued_message = None
        if queued_message:
            _live_user_message({"role": "user", "text": queued_message})

        # Reserve the progress area before the chat input. Streamlit can then
        # keep the composer at the bottom instead of placing it over a spinner.
        progress_placeholder = st.empty()
        typed_message = st.chat_input("Posez une question sur vos feedbacks clients…")
        if typed_message and not queued_message:
            _queue_message(typed_message)
            st.rerun()

        outgoing_message = queued_message
        if outgoing_message:
            # Clear before invoking the API so a rerun after a failure never
            # sends the same feedback twice.
            st.session_state.pending_message = None
            _append_active_message({"role": "user", "text": outgoing_message})
            try:
                with progress_placeholder.container():
                    st.markdown(
                        '<div class="analysis-progress"><span class="analysis-progress-dot"></span>Analyse en cours…</div>',
                        unsafe_allow_html=True,
                    )
                    with st.spinner("L’assistant analyse votre demande…"):
                        session_id = _ensure_conversation()
                        turn = _api_request(
                            "POST",
                            f"/api/conversations/{session_id}/messages",
                            payload={"message": outgoing_message},
                        )
                _append_active_message(
                    {
                        "role": "assistant",
                        "text": str(turn.get("reply", "")),
                        "analysis": turn.get("analysis"),
                        "insights": turn.get("insights"),
                        "visualizations": turn.get("visualizations"),
                    }
                )
            except RuntimeError as error:
                _append_active_message(
                    {
                        "role": "assistant",
                        "text": f"Je ne peux pas traiter cette demande pour le moment. {error}",
                    }
                )
            st.rerun()

if __name__ == "__main__":
    live_main()
