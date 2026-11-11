"""Present the three required chart panels and their interpretation limits."""

import streamlit as st

from dashboard import context, show_chart

ctx = context()  # All panels use the shared hour, energy and charger filters.
st.header("Energy analytics")
st.subheader(
    "Panel 1 · Hourly EV charging energy" if ctx["telemetry"] is None
    else "Panel 1 · Hourly campus demand and solar")
show_chart("grid", ctx)
st.subheader("Panel 2 · Session cost by user type")
show_chart("cost", ctx)
st.caption("Boxes show median and interquartile range; points show outliers.")
st.subheader("Panel 3 · Battery temperature and energy delivered")
show_chart("temperature", ctx)
st.caption(
    "Lines show descriptive linear trends within each charger type; "
    "they do not establish a causal temperature effect."
)
