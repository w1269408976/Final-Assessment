"""Summarise the filtered charging population and priority actions."""

import streamlit as st

from dashboard import context, show_alerts, show_chart

ctx = context()  # Reuse the same filtered population as every other page.
st.header("Operations overview")
st.caption("All session charts use the shared sidebar filters.")
show_chart("grid", ctx)
left, right = st.columns([1.4, 1])
with left:
    st.subheader("Charging cost distribution")
    show_chart("cost", ctx)
with right:
    st.subheader("Priority review")
    alerts = show_alerts(ctx)
    if not alerts.empty:
        # Show the hottest eight alerts first to support priority review.
        columns = ["Session_ID", "Battery_Temp_C",
                   "Overstay_Mins", "Alert_Severity"]
        st.dataframe(
            alerts.sort_values("Battery_Temp_C", ascending=False)[
                columns].head(8),
            hide_index=True, width="stretch",
        )
