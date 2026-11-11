
from pathlib import Path

import streamlit as st


def main():
    """Start the Streamlit server or render the current dashboard page."""
    if not st.runtime.exists():
        # A normal PyCharm Run needs to start the Streamlit server first.
        from run_dashboard import main as launch_dashboard

        raise SystemExit(launch_dashboard())

    # Import cached UI helpers only after the Streamlit runtime is available.
    from dashboard import configure_style, show_kpis, sidebar_context
    from pipeline import DataValidationError

    ROOT = Path(__file__).resolve().parent
    st.set_page_config(
        page_title="Campus Energy and EV Operations",
        page_icon="⚡", layout="wide",
    )
    configure_style()

    ev_filter_keys = (
        "start_hour_range", "min_energy", "chargers", "temperature_threshold",
    )
    sales_filter_keys = ("sales_date_range", "sales_hubs", "sales_categories",
                         "sales_customers")

    navigation = st.navigation(
        [
            st.Page(ROOT / "views/overview.py",
                    title="Overview", icon="📊", default=True),
            st.Page(ROOT / "views/analytics.py",
                    title="Energy analytics", icon="📈"),
            st.Page(ROOT / "views/alerts.py", title="Alert centre", icon="🌡️"),
            st.Page(ROOT / "views/data_view.py",
                    title="Data & quality", icon="📋"),
            st.Page(ROOT / "views/sales_view.py", title="Sales performance",
                    icon="🛍️", url_path="sales"),
        ]
    )
    # Preserve only inactive widgets; active widgets keep their own values.
    inactive_keys = (ev_filter_keys if navigation.url_path == "sales"
                     else sales_filter_keys)
    for key in inactive_keys:
        if key in st.session_state:
            st.session_state[key] = st.session_state[key]
    # Retail sales have their own dates, filters and financial totals.
    if navigation.url_path == "sales":
        navigation.run()
        return

    try:
        ctx = sidebar_context()
    except (DataValidationError, OSError, ValueError) as error:
        # Operators receive a useful error instead of an unhandled stack trace.
        st.error(f"Unable to load the campus dataset: {error}")
        st.info("Check the CSV files in the project's data folder and retry.")
        st.stop()  # Stop page execution when source validation fails.

    st.title("Campus Energy & EV Operations")
    st.caption(
        "Taylor’s Smart Campus · Charging, revenue and operational alerts"
    )
    show_kpis(ctx)  # Recalculate metrics for the shared filtered selection.

    navigation.run()


if __name__ == "__main__":
    main()
