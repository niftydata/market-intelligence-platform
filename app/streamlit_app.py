from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv
from plotly.subplots import make_subplots

from market_intelligence.assistant.foundry import (
    FoundryAssistant,
    FoundrySettings,
)
from market_intelligence.config import Settings
from market_intelligence.dashboard.auth import verify_credentials
from market_intelligence.dashboard.data import (
    DashboardMetadata,
    load_dashboard_frame,
    load_dashboard_metadata,
)
from market_intelligence.database import (
    RefreshAlreadyRunningError,
    create_database_engine,
)
from market_intelligence.pipeline import run_full_refresh

SYDNEY_TIMEZONE = ZoneInfo("Australia/Sydney")
NAVY = "#050505"
TEAL = "#3563FF"
ORANGE = "#606060"
GREEN = "#167A5A"
AMBER = "#B66A00"
RED = "#B42318"
MUTED = "#5E5E5E"
GRID = "#E2E2E2"
LOGGER = logging.getLogger(__name__)

load_dotenv()


st.set_page_config(
    page_title="Australian Market Pulse | NiftyData",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_resource
def database_engine():
    settings = Settings.from_environment()
    return create_database_engine(settings.database_url)


@st.cache_data(ttl=300)
def dashboard_metadata() -> DashboardMetadata:
    return load_dashboard_metadata(database_engine())


@st.cache_data(ttl=300)
def dashboard_frame(analysis_end_date: date) -> pd.DataFrame:
    return load_dashboard_frame(
        database_engine(),
        analysis_end_date=analysis_end_date,
        window_days=90,
    )


@st.cache_resource
def foundry_assistant() -> FoundryAssistant:
    return FoundryAssistant.create(
        database_engine(),
        FoundrySettings.from_environment(),
    )


def format_percent(value: float, *, decimals: int = 1) -> str:
    return f"{value:+.{decimals}f}%"


def signal_content(status: str) -> tuple[str, str, str]:
    content = {
        "green": (
            "GREEN",
            "No elevated volatility signal",
            GREEN,
        ),
        "amber": (
            "AMBER",
            "Volatility is elevated — monitor closely",
            AMBER,
        ),
        "red": (
            "RED",
            "Volatility is unusually high",
            RED,
        ),
    }
    return content.get(
        status,
        ("PENDING", "Insufficient history for a signal", MUTED),
    )


def market_chart(frame: pd.DataFrame) -> go.Figure:
    figure = make_subplots(specs=[[{"secondary_y": True}]])
    figure.add_trace(
        go.Scatter(
            x=frame["trading_date"],
            y=frame["close_value"],
            name="ASX 200 close",
            mode="lines",
            line={"color": TEAL, "width": 2.8},
            hovertemplate="%{x|%d %b %Y}<br>Close %{y:,.1f}<extra></extra>",
        ),
        secondary_y=False,
    )
    figure.add_trace(
        go.Scatter(
            x=frame["trading_date"],
            y=frame["rolling_average_20d"],
            name="20-day average",
            mode="lines",
            line={"color": NAVY, "width": 2.2, "dash": "dash"},
            hovertemplate="%{x|%d %b %Y}<br>20D avg %{y:,.1f}<extra></extra>",
        ),
        secondary_y=False,
    )
    figure.add_trace(
        go.Scatter(
            x=frame["trading_date"],
            y=frame["rba_cash_rate_percent"],
            name="RBA cash rate",
            mode="lines",
            line={"color": ORANGE, "width": 2, "dash": "dot"},
            hovertemplate="%{x|%d %b %Y}<br>Cash rate %{y:.2f}%<extra></extra>",
        ),
        secondary_y=True,
    )
    figure.update_yaxes(
        title_text="S&P/ASX 200 index",
        tickformat=",",
        gridcolor=GRID,
        secondary_y=False,
    )
    figure.update_yaxes(
        title_text="RBA cash rate",
        ticksuffix="%",
        showgrid=False,
        secondary_y=True,
    )
    figure.update_layout(
        height=430,
        margin={"l": 8, "r": 8, "t": 35, "b": 8},
        paper_bgcolor="white",
        plot_bgcolor="white",
        hovermode="x unified",
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "left",
            "x": 0,
        },
        font={"family": "Noto Sans, Arial, sans-serif", "color": NAVY},
    )
    return figure


def volatility_chart(frame: pd.DataFrame) -> go.Figure:
    latest = frame.iloc[-1]
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=frame["trading_date"],
            y=frame["realized_volatility_14d_percent"],
            name="14-day annualised volatility",
            mode="lines",
            fill="tozeroy",
            fillcolor="rgba(5, 5, 5, 0.06)",
            line={"color": NAVY, "width": 2.4},
            hovertemplate="%{x|%d %b %Y}<br>Volatility %{y:.1f}%<extra></extra>",
        )
    )
    figure.add_hline(
        y=float(latest["volatility_p75_threshold"]),
        line_color=AMBER,
        line_dash="dash",
        annotation_text="Amber threshold",
        annotation_position="top left",
    )
    figure.add_hline(
        y=float(latest["volatility_p90_threshold"]),
        line_color=RED,
        line_dash="dash",
        annotation_text="Red threshold",
        annotation_position="top left",
    )
    figure.update_layout(
        height=315,
        margin={"l": 8, "r": 8, "t": 20, "b": 8},
        paper_bgcolor="white",
        plot_bgcolor="white",
        showlegend=False,
        hovermode="x unified",
        yaxis={
            "title": "Annualised volatility",
            "ticksuffix": "%",
            "gridcolor": GRID,
            "rangemode": "tozero",
        },
        font={"family": "Noto Sans, Arial, sans-serif", "color": NAVY},
    )
    return figure


def management_story(frame: pd.DataFrame) -> tuple[str, str]:
    latest = frame.iloc[-1]
    first = frame.iloc[0]
    return_20d = float(latest["return_20d_percent"])
    close = float(latest["close_value"])
    average = float(latest["rolling_average_20d"])
    cash_rate_change = float(
        latest["rba_cash_rate_percent"] - first["rba_cash_rate_percent"]
    )

    trend = (
        f"The index is {abs((close / average - 1) * 100):.1f}% "
        f"{'above' if close >= average else 'below'} its 20-day average "
        f"and has returned {return_20d:+.1f}% over 20 trading days."
    )
    if abs(cash_rate_change) < 0.005:
        macro = (
            "The cash rate was unchanged over the visible period, so the recent "
            "market move has occurred without a concurrent policy-rate change."
        )
    else:
        macro = (
            f"The cash rate changed by {cash_rate_change:+.2f} percentage points "
            "over the visible period, providing monetary-policy context for the "
            "market move."
        )
    return trend, macro


def environment_flag(name: str, *, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def data_refresh_control() -> None:
    st.markdown("### Data refresh")
    st.caption(
        "Refresh Yahoo Finance and RBA source data, validate it, "
        "then rebuild the curated analytics."
    )
    if st.button(
        "Refresh Yahoo + RBA",
        type="primary",
        use_container_width=True,
    ):
        reference_id = uuid.uuid4().hex[:8].upper()
        try:
            with st.spinner("Refreshing sources and validating the analytics..."):
                refresh_result = run_full_refresh(
                    Settings.from_environment(),
                    as_of_date=datetime.now(SYDNEY_TIMEZONE).date(),
                )
            st.session_state.data_refresh_summary = {
                "succeeded": refresh_result.succeeded,
                "reference_id": reference_id,
                "completed_at": datetime.now(SYDNEY_TIMEZONE).strftime(
                    "%d/%m/%Y %H:%M"
                ),
                "rows": [
                    {
                        "Stage": stage.stage,
                        "Status": stage.status.title(),
                        "Received": stage.records_received,
                        "Accepted": stage.records_accepted,
                        "Rejected": stage.records_rejected,
                    }
                    for stage in refresh_result.stages
                ],
                "failure_summary": next(
                    (
                        stage.failure_summary
                        for stage in refresh_result.stages
                        if stage.status == "failed" and stage.failure_summary
                    ),
                    None,
                ),
            }
            dashboard_metadata.clear()
            dashboard_frame.clear()
            if refresh_result.succeeded:
                st.session_state.refresh_select_latest = True
            st.rerun()
        except RefreshAlreadyRunningError:
            st.info(
                "A data refresh is already running. "
                "Please wait for it to finish."
            )
        except Exception:
            LOGGER.exception(
                "Full data refresh failed reference_id=%s",
                reference_id,
            )
            st.error(
                "The refresh could not start. Existing dashboard data "
                f"remains available. Reference: {reference_id}"
            )

    refresh_summary = st.session_state.get("data_refresh_summary")
    if refresh_summary:
        if refresh_summary["succeeded"]:
            st.success(
                "Refresh completed successfully at "
                f"{refresh_summary['completed_at']}."
            )
        else:
            st.warning(
                "One or more refresh stages failed. The last validated "
                "dashboard remains available. "
                f"Reference: {refresh_summary['reference_id']}"
            )
            if refresh_summary.get("failure_summary"):
                st.error(refresh_summary["failure_summary"])
        st.dataframe(
            pd.DataFrame(refresh_summary["rows"]),
            hide_index=True,
            use_container_width=True,
        )


def ai_assistant_sidebar(analysis_end_date: date) -> None:
    enabled = environment_flag("ENABLE_AI_ASSISTANT")
    configured_username = os.getenv("AI_DEMO_USERNAME", "")
    configured_password_hash = os.getenv("AI_DEMO_PASSWORD_HASH", "")
    max_attempts = max(1, int(os.getenv("AI_MAX_LOGIN_ATTEMPTS", "5")))

    with st.sidebar:
        st.markdown("## AI + Refresh")
        st.caption("Refresh the data or ask questions about markets and macro.")

        if not enabled:
            st.info("The AI assistant is not enabled.")
            return

        if not st.session_state.get("ai_panel_open", False):
            if st.button("Ask AI", type="primary", use_container_width=True):
                st.session_state.ai_panel_open = True
                st.rerun()
            return

        if st.session_state.get("ai_authenticated", False):
            st.success(f"Signed in as {configured_username}")
            action_columns = st.columns(2)
            if action_columns[0].button("Clear", use_container_width=True):
                st.session_state.ai_messages = []
                st.session_state.ai_question_count = 0
                st.rerun()
            if action_columns[1].button("Log out", use_container_width=True):
                st.session_state.ai_authenticated = False
                st.session_state.ai_panel_open = False
                st.session_state.ai_messages = []
                st.rerun()

            data_refresh_control()

            try:
                FoundrySettings.from_environment()
            except ValueError:
                st.info(
                    "Login is ready. Add the Foundry client secret in Render "
                    "to activate questions."
                )
                return

            messages = st.session_state.setdefault("ai_messages", [])
            if not messages:
                messages.append(
                    {
                        "role": "assistant",
                        "content": (
                            "Ask me about ASX 200 performance, volatility, "
                            "RBA rates, historical comparisons, or the current signal."
                        ),
                    }
                )
            for message in messages:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])

            max_questions = max(
                1,
                int(os.getenv("AI_MAX_QUESTIONS_PER_SESSION", "20")),
            )
            question_count = int(st.session_state.get("ai_question_count", 0))
            if question_count >= max_questions:
                st.warning(
                    "This demo session has reached its question limit. "
                    "Clear the conversation to start again."
                )
                return

            prompt = st.chat_input(
                "Ask about the market data",
                max_chars=500,
            )
            if not prompt:
                return

            prior_conversation = list(messages)
            messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            try:
                with st.spinner("Analysing the validated data..."):
                    answer = foundry_assistant().answer(
                        prompt,
                        analysis_end_date=analysis_end_date,
                        conversation=prior_conversation,
                    )
            except Exception:
                reference_id = uuid.uuid4().hex[:8].upper()
                LOGGER.exception(
                    "Foundry assistant request failed reference_id=%s",
                    reference_id,
                )
                answer = (
                    "The AI assistant is temporarily unavailable. "
                    "The dashboard data has not been affected. "
                    f"Reference: {reference_id}"
                )

            messages.append({"role": "assistant", "content": answer})
            st.session_state.ai_question_count = question_count + 1
            with st.chat_message("assistant"):
                st.markdown(answer)
            return

        locked_until = float(st.session_state.get("ai_locked_until", 0.0))
        if locked_until > time.time():
            remaining_seconds = max(1, int(locked_until - time.time()))
            st.error(
                "Too many unsuccessful attempts. "
                f"Please wait {remaining_seconds} seconds."
            )
            return

        with st.form("ai_demo_login", clear_on_submit=True):
            submitted_username = st.text_input(
                "Username",
                autocomplete="username",
            )
            submitted_password = st.text_input(
                "Password",
                type="password",
                autocomplete="current-password",
            )
            submitted = st.form_submit_button(
                "Sign in to Ask AI",
                type="primary",
                use_container_width=True,
            )

        if not submitted:
            return

        if not configured_username or not configured_password_hash:
            st.error("The AI demo login has not been configured.")
            return

        if verify_credentials(
            submitted_username,
            submitted_password,
            configured_username=configured_username,
            configured_password_hash=configured_password_hash,
        ):
            st.session_state.ai_authenticated = True
            st.session_state.ai_login_attempts = 0
            st.rerun()

        attempts = int(st.session_state.get("ai_login_attempts", 0)) + 1
        st.session_state.ai_login_attempts = attempts
        if attempts >= max_attempts:
            st.session_state.ai_locked_until = time.time() + 60
            st.session_state.ai_login_attempts = 0
            st.error("Too many unsuccessful attempts. Login is locked for 60 seconds.")
        else:
            st.error("Incorrect username or password.")


st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Noto+Sans:wght@400;500;600;700;800&display=swap');

    #MainMenu, footer, header {visibility: hidden;}
    html, body, [class*="st-"], .stApp, button, input, textarea, select {
        font-family: "Noto Sans", Arial, sans-serif !important;
    }
    .stApp {
        background: #F5F5F3;
        color: #050505;
    }
    .block-container {
        max-width: 1240px;
        padding-top: 1.6rem;
        padding-bottom: 2rem;
    }
    .brand {
        color: #050505;
        font-size: 0.76rem;
        font-weight: 800;
        letter-spacing: 0.18em;
        text-transform: uppercase;
        margin-bottom: 0.35rem;
    }
    .st-key-market-pulse-hero {
        background: #050505;
        border: 1px solid #050505;
        border-radius: 0;
        padding: 1.35rem 1.8rem 1.15rem;
        margin-bottom: 1rem;
        box-shadow: none;
    }
    .st-key-market-pulse-hero h1 {
        color: white;
        font-size: 1.8rem;
        font-weight: 800;
        line-height: 1.15;
        margin: 0 0 0.4rem;
        letter-spacing: -0.035em;
        text-transform: uppercase;
    }
    .st-key-market-pulse-hero .pulse-subtitle {
        color: #F0F0F0;
        margin: 0;
        font-size: 0.98rem;
    }
    .st-key-market-pulse-hero [data-testid="stDateInput"] label p {
        color: white !important;
        font-size: 1rem !important;
        font-weight: 800 !important;
        letter-spacing: 0.06em;
        text-transform: uppercase;
    }
    .st-key-market-pulse-hero [data-testid="stDateInput"] input {
        color: #050505;
        background: #FFFFFF;
        border-radius: 0;
        font-size: 1.05rem;
        font-weight: 750;
        min-height: 2.8rem;
    }
    section[data-testid="stSidebar"] {
        background: #FFFFFF;
        border-right: 1px solid #050505;
    }
    section[data-testid="stSidebar"] h2 {
        color: #050505;
        letter-spacing: -0.02em;
    }
    section[data-testid="stSidebar"] div[data-testid="stChatInput"] {
        position: sticky;
        bottom: 0.75rem;
        z-index: 20;
        background: #FFFFFF;
        border-radius: 12px;
        box-shadow: 0 -10px 22px rgba(255, 255, 255, 0.96);
    }
    .stButton button,
    .stFormSubmitButton button {
        border: 1px solid #050505;
        border-radius: 0;
        font-weight: 700;
    }
    .stButton button[kind="primary"],
    .stFormSubmitButton button[kind="primary"] {
        background: #050505;
        border-color: #050505;
        color: #FFFFFF;
    }
    .stButton button[kind="primary"]:hover,
    .stFormSubmitButton button[kind="primary"]:hover {
        background: #2B2B2B;
        border-color: #2B2B2B;
        color: #FFFFFF;
    }
    div[data-testid="stMetric"] {
        background: #FFFFFF;
        border: 1px solid #050505;
        border-radius: 0;
        padding: 1rem 1.05rem;
        box-shadow: none;
    }
    div[data-testid="stMetricLabel"] {
        color: #303030;
        font-size: 0.72rem;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
    }
    div[data-testid="stMetricValue"] {color: #050505; font-weight: 800;}
    div[data-testid="stMetricDelta"] {color: #3563FF;}
    .section-title {
        color: #050505;
        font-size: 1.1rem;
        font-weight: 800;
        letter-spacing: -0.02em;
        text-transform: uppercase;
        margin: 1.1rem 0 0.15rem;
    }
    .section-subtitle {
        color: #5E5E5E;
        font-size: 0.88rem;
        margin-bottom: 0.55rem;
    }
    .signal-card {
        background: #FFFFFF;
        border: 1px solid #050505;
        border-radius: 0;
        padding: 1.1rem 1.2rem;
        min-height: 122px;
        box-shadow: none;
    }
    .signal-label {
        display: inline-block;
        color: white;
        font-size: 0.74rem;
        font-weight: 800;
        letter-spacing: 0.09em;
        border-radius: 999px;
        padding: 0.25rem 0.65rem;
        margin-bottom: 0.65rem;
    }
    .signal-title {color: #050505; font-weight: 800; font-size: 1.08rem;}
    .signal-detail {color: #5E5E5E; font-size: 0.84rem; margin-top: 0.35rem;}
    .story-card {
        background: #FFFFFF;
        border: 1px solid #050505;
        border-left: 4px solid #050505;
        border-radius: 0;
        padding: 1rem 1.1rem;
        color: #303030;
        margin-top: 0.7rem;
    }
    .story-card strong {color: #050505;}
    div[data-testid="stPlotlyChart"] {
        background: #FFFFFF;
        border: 1px solid #050505;
        padding: 0.45rem;
    }
    div[data-testid="stDataFrame"] {
        border: 1px solid #050505;
        border-radius: 0;
    }
    .freshness {
        color: #5E5E5E;
        font-size: 0.78rem;
        text-align: right;
        margin: 0.4rem 0 0.8rem;
    }
    .disclaimer {
        border-top: 1px solid #050505;
        color: #5E5E5E;
        font-size: 0.74rem;
        margin-top: 1.5rem;
        padding-top: 0.9rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

try:
    metadata = dashboard_metadata()
except Exception:
    st.error(
        "Market data is temporarily unavailable. The latest validated dataset "
        "has not been changed; please try again shortly."
    )
    st.stop()

if (
    st.session_state.pop("refresh_select_latest", False)
    or "analysis_end_date" not in st.session_state
):
    st.session_state.analysis_end_date = metadata.latest_curated_date

logo_path = Path(__file__).resolve().parent / "assets" / "niftydata-logo.png"
logo_left, logo_column, logo_right = st.columns([0.325, 0.35, 0.325])
with logo_column:
    st.image(str(logo_path), use_container_width=True)

with st.container(key="market-pulse-hero"):
    pulse_column, date_column = st.columns(
        [0.68, 0.32],
        vertical_alignment="center",
    )
    with date_column:
        selected_end_date = st.date_input(
            "Analysis Ending",
            min_value=metadata.first_curated_date,
            max_value=metadata.latest_curated_date,
            format="DD/MM/YYYY",
            key="analysis_end_date",
            help="Select the end date for the trailing 90-calendar-day analysis.",
        )

try:
    data = dashboard_frame(selected_end_date)
except Exception:
    st.error(
        "No validated market observations are available on or before the "
        "selected analysis date."
    )
    st.stop()

latest = data.iloc[-1]
effective_end_date = pd.Timestamp(latest["trading_date"]).date()
signal_label, signal_title, signal_color = signal_content(str(latest["rag_status"]))
trend_story, macro_story = management_story(data)
calculated_at = pd.Timestamp(metadata.latest_calculated_at).tz_convert(
    SYDNEY_TIMEZONE
)

ai_assistant_sidebar(effective_end_date)

with pulse_column:
    st.markdown(
        f"""
        <h1>Australian Market Pulse</h1>
        <p class="pulse-subtitle">S&amp;P/ASX 200 activity, volatility and
        monetary context — 90 days ending {effective_end_date:%d/%m/%Y}</p>
        """,
        unsafe_allow_html=True,
    )
st.markdown(
    (
        '<div class="freshness">'
        f"Analysis through {effective_end_date:%d %b %Y} · "
        f"Latest market source {metadata.latest_market_date:%d %b %Y} · "
        f"RBA source through {metadata.latest_rba_date:%d %b %Y} · "
        f"Refreshed {calculated_at:%d %b %Y, %H:%M} AEST/AEDT"
        "</div>"
    ),
    unsafe_allow_html=True,
)

metric_columns = st.columns(4)
metric_columns[0].metric(
    "ASX 200 close",
    f"{float(latest['close_value']):,.1f}",
    (
        f"{(float(latest['close_value']) / float(latest['rolling_average_20d']) - 1) * 100:+.1f}% "
        "vs 20D avg"
    ),
)
metric_columns[1].metric(
    "20-day return",
    format_percent(float(latest["return_20d_percent"])),
    "vs 20 trading days ago",
    delta_color="off",
)
metric_columns[2].metric(
    "14-day volatility",
    f"{float(latest['realized_volatility_14d_percent']):.1f}%",
    f"Amber at {float(latest['volatility_p75_threshold']):.1f}%",
    delta_color="off",
)
metric_columns[3].metric(
    "RBA cash rate",
    f"{float(latest['rba_cash_rate_percent']):.2f}%",
    f"Observed {latest['rba_observation_date']:%d %b}",
    delta_color="off",
)

st.markdown('<div class="section-title">Management signal</div>', unsafe_allow_html=True)
signal_column, story_column = st.columns([0.34, 0.66])
with signal_column:
    st.markdown(
        (
            '<div class="signal-card">'
            f'<span class="signal-label" style="background:{signal_color};">'
            f"{signal_label}</span>"
            f'<div class="signal-title">{signal_title}</div>'
            '<div class="signal-detail">Based on the five-year distribution of '
            "14-day realised volatility.</div></div>"
        ),
        unsafe_allow_html=True,
    )
with story_column:
    st.markdown(
        (
            '<div class="story-card"><strong>What changed:</strong> '
            f"{trend_story}<br><br><strong>Macro context:</strong> "
            f"{macro_story}</div>"
        ),
        unsafe_allow_html=True,
    )

st.markdown('<div class="section-title">90-day market trend</div>', unsafe_allow_html=True)
st.markdown(
    (
        '<div class="section-subtitle">Index level and rolling trend with the '
        "RBA cash rate on the secondary axis.</div>"
    ),
    unsafe_allow_html=True,
)
st.plotly_chart(
    market_chart(data),
    use_container_width=True,
    config={"displayModeBar": False, "responsive": True},
)

st.markdown('<div class="section-title">What to watch</div>', unsafe_allow_html=True)
st.markdown(
    (
        '<div class="section-subtitle">Volatility is monitored against dynamically '
        "calibrated five-year percentile thresholds.</div>"
    ),
    unsafe_allow_html=True,
)
st.plotly_chart(
    volatility_chart(data),
    use_container_width=True,
    config={"displayModeBar": False, "responsive": True},
)

st.markdown(
    (
        '<div class="disclaimer">'
        "Publicly available Yahoo Finance and Reserve Bank of Australia data. "
        "This dashboard is descriptive, not investment advice. RAG thresholds "
        "are monitoring indicators rather than formal risk limits."
        "</div>"
    ),
    unsafe_allow_html=True,
)
