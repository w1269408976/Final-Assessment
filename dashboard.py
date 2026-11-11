

from io import BytesIO
from pathlib import Path

import matplotlib.pyplot as plt
import streamlit as st

from pipeline import (
    alert_mask, filter_sessions, prepare_sessions,
    summary_metrics,
)
from visuals import build_panel, load_telemetry

ROOT = Path(__file__).resolve().parent


@st.cache_data(show_spinner=False)
def load_sessions(raw_bytes, date_bytes=None):
    """Cache by file contents so replacing a CSV invalidates stale results."""
    return prepare_sessions(
        BytesIO(raw_bytes), BytesIO(
            date_bytes) if date_bytes is not None else None,
    )


@st.cache_data(show_spinner=False)
def read_telemetry(raw_bytes):
    """Validate a local hourly feed once for each unique file content."""
    return load_telemetry(BytesIO(raw_bytes))


def configure_style():
    """Use readable metrics and neutral cards in an executive layout."""
    st.markdown(
        """<style>
        .block-container {max-width: 1440px; padding-top: 2rem;}
        [data-testid="stMetric"] {
          background: #F3F7FA; border: 1px solid #DFE7ED;
          border-radius: 10px; padding: 14px 18px;}
        [data-testid="stMetricValue"] {font-size: 1.85rem;}
        [data-testid="stSidebar"] {background: #F5F8FA;}
        h1 {letter-spacing: -0.035em;}
        @media (max-width: 900px) {
          [data-testid="stHorizontalBlock"] {flex-wrap: wrap;}
          [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
            min-width: 240px; flex: 1 1 240px;
          }
        }
        </style>""", unsafe_allow_html=True,
    )


def sidebar_context():
    """Prepare one filtered population for all application pages."""
    with st.sidebar:
        st.header("Campus controls")
        st.caption("Shared across EV pages")
        # Read project files directly; browser upload controls are unnecessary.
        raw_bytes = (ROOT / "data/ev_campus_dataset.csv").read_bytes()
        date_path = ROOT / "data/session_dates.csv"
        grid_path = ROOT / "data/hourly_telemetry.csv"
        date_bytes = date_path.read_bytes() if date_path.is_file() else None
        # Optional local supplements retain validation without upload widgets.
        sessions, quality = load_sessions(raw_bytes, date_bytes)
        telemetry = read_telemetry(
            grid_path.read_bytes()) if grid_path.is_file() else None

        # Two handles select an inclusive range of recorded start hours.
        hour_range = st.slider(
            "Start_Hour range", min_value=0, max_value=23, value=(0, 23),
            step=1, format="%d:00", key="start_hour_range",
            help="Include sessions starting in either endpoint hour "
            "and every hour between them.",
        )
        st.caption(
            f"Session starts: {hour_range[0]:02d}:00"
            f"–{hour_range[1]:02d}:59")

        max_energy = max(1.0, float(sessions["Energy_kWh"].max()))
        if st.session_state.get("min_energy", 0.0) > max_energy:
            st.session_state["min_energy"] = 0.0
        minimum = st.slider(
            "Minimum energy (kWh)",
            0.0,
            max_energy,
            0.0,
            0.5,
            key="min_energy",
        )
        chargers = st.multiselect(
            "Charger type", ["AC", "DC"], default=["AC", "DC"], key="chargers",
        )
        threshold = st.slider(
            "Alert temperature (°C)", 20.0, 70.0, 40.0, 0.5,
            key="temperature_threshold",
            help="Overstay >20 minutes AND temperature above the threshold."
        )
        if st.button("Reset filters", width="stretch"):
            for key in (
                "min_energy",
                "chargers",
                "temperature_threshold",
                    "start_hour_range"):
                st.session_state.pop(key, None)
            st.rerun()

    # Filter once so charts, KPI cards, tables and downloads use identical
    # rows.
    visible = filter_sessions(
        sessions, chargers, minimum, hour_range=hour_range)
    if telemetry is not None:
        # A campus feed can share hour bounds but has no charger breakdown.
        hours = telemetry["Timestamp"].dt.hour
        telemetry = telemetry.loc[hours.between(*hour_range)].copy()
    context = {"all": sessions, "data": visible, "quality": quality,
               "telemetry": telemetry, "threshold": threshold,
               "hour_range": hour_range,
               "source_name": "ev_campus_dataset.csv", }
    # Pages reuse the same DataFrame; no page recomputes a conflicting filter.
    st.session_state["_campus_context"] = context
    return context


def context():
    """Return the context prepared by the entrypoint on every rerun."""
    return st.session_state["_campus_context"]


def show_kpis(ctx):
    """Show selection totals with honest deltas against all loaded sessions."""
    current = summary_metrics(ctx["data"], ctx["threshold"])
    baseline = summary_metrics(ctx["all"], ctx["threshold"])
    st.caption(
        f"{current['sessions']:,} of {baseline['sessions']:,} sessions · "
        "Deltas compare this selection with all loaded sessions "
        "at the same alert threshold."
    )
    fields = [
        ("Total energy", "energy_kwh", "kWh"),
        ("Carbon offset", "carbon_kg", "kg CO₂"),
        ("Total revenue", "revenue_myr", "MYR"),
        ("Active alerts", "alerts", ""),
    ]
    for column, (label, key, unit) in zip(st.columns(4), fields):
        value = current[key]
        difference = round(value - baseline[key], 2)
        display = f"{value:,}" if key == "alerts" else f"{value:,.2f} {unit}"
        delta = (
            f"{difference:+,}" if key == "alerts"
            else f"{difference:+,.2f} {unit}"
        )
        column.metric(
            label, display, delta=delta,
            delta_color="inverse" if key == "alerts" else "off",
        )


def show_chart(kind, ctx):
    """Close figures after rendering to release memory between reruns."""
    if ctx["data"].empty:
        st.info("No sessions match. Change the sidebar filters.")
        return
    # Use the same hour bounds for the plot axis and the underlying records.
    fig = build_panel(
        kind, ctx["data"], ctx["telemetry"], hour_range=ctx["hour_range"])
    try:
        st.pyplot(fig, width="stretch")
    finally:
        plt.close(fig)
    if kind == "grid" and ctx["telemetry"] is not None:
        if ctx["telemetry"].empty:
            st.warning(
                "No campus readings are available for these hours.")
        else:
            st.caption(
                "Campus measurements follow the selected hours. "
                "Charger and energy filters apply to EV sessions; "
                "the campus feed has no charger-level breakdown.")


def download_sessions(
        data, label="Download filtered sessions",
        filename="filtered_ev_sessions.csv"):
    """Export exactly the visible rows and columns, without an extra index."""
    # UTF-8 BOM preserves column names when users open the download in Excel.
    payload = data.to_csv(
        index=False, date_format="%Y-%m-%d").encode("utf-8-sig")
    st.download_button(label, payload, file_name=filename, mime="text/csv")


def show_alerts(ctx):
    """Display threshold alerts with a separate severity classification."""
    data, threshold = ctx["data"], ctx["threshold"]
    alerts = data.loc[alert_mask(data, threshold)].copy()
    st.caption(
        "Alert rule: overstay >20 minutes AND "
        f"battery temperature >{threshold:g}°C.")
    if alerts.empty:
        st.success(
            "No high-risk sessions at this threshold and selection.")
    else:
        # Severity is a documented UI policy; it does not change the alert
        # rule.
        critical = alerts["Battery_Temp_C"].gt(threshold + 5)
        warnings = len(alerts) - int(critical.sum())
        if critical.any():
            st.error(
                f"{int(critical.sum())} critical sessions exceed "
                f"{threshold + 5:g}°C with overstay >20 minutes.")
        if warnings:
            st.warning(
                f"{warnings} additional high-risk sessions need review.")
        alerts["Alert_Severity"] = critical.map(
            {True: "Critical", False: "Warning"})
    return alerts
