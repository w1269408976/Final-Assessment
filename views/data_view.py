"""Expose filtered rows, data-quality evidence and reproducible fee rules."""

import streamlit as st

from dashboard import context, download_sessions

ctx = context()
st.header("Filtered data & quality")
# Download precisely the currently visible rows.
download_sessions(ctx["data"])
st.dataframe(ctx["data"], hide_index=True, width="stretch", height=460)
st.subheader("Preparation summary")
st.write(
    f"Source: {ctx['source_name']} · {len(ctx['all']):,} validated sessions")
for column, result in ctx["quality"]["imputed"].items():
    if result["count"]:
        st.write(
            f"{column}: filled {result['count']} missing values "
            f"with median {result['median']:g}.")
st.caption(
    "Labels are normalised for case and whitespace; "
    "unknown categories are rejected.")
with st.expander("Billing and carbon definitions"):
    st.write(
        "Power = energy ÷ duration in hours. "
        "Carbon savings = energy ×0.475 kg CO₂/kWh. "
        "Carbon is rounded per session before totals are displayed.")
    st.write(
        "AC: RM6/hour; DC: RM15/hour. "
        "Sessions starting from 12:00 through 17:59 "
        "receive a 25% base-fee surcharge. Overstay beyond a 15-minute grace "
        "period costs RM0.50/minute. The final bill is rounded to cents once.")
    st.caption(
        "Tariff rules reproduce the supplied cleaned CSV; "
        "they are not a verified "
        "university tariff. The Section A 15% risk fee is kept separate.")
with st.expander("Missing source data and supplement formats"):
    st.write(
        "The supplied EV sessions have no dates, measured grid power "
        "or solar readings. No date or power curve has been invented. "
        "The unrelated sales transaction "
        "dates are not joined to charging sessions.")
    st.write(
        "The sidebar filters recorded Start_Hour values from 0 to 23, "
        "including both endpoints. For example, 6–10 includes sessions "
        "starting between 06:00 and 10:59 across the supplied dataset.")
    st.code(
        "Session_ID,Session_Date\n"
        "# Use YYYY-MM-DD dates for every matching session ID.",
        language="text")
    st.code(
        "Timestamp,Grid_Demand_kW,Solar_Generation_kW\n"
        "# Use unique hourly timestamps and actual non-negative kW.",
        language="text")
    st.caption(
        "Optional local files: data/session_dates.csv and "
        "data/hourly_telemetry.csv. Browser uploads are not required.")
