"""Review and download high-risk sessions at a user-controlled threshold."""

import streamlit as st

from dashboard import context, download_sessions, show_alerts

ctx = context()
st.header("High-risk overstay & alert centre")
st.write("Adjust Alert temperature to update banners, the KPI and records.")
alerts = show_alerts(ctx)  # Apply the current temperature threshold.
st.dataframe(
    alerts.sort_values("Battery_Temp_C", ascending=False),
    hide_index=True, width="stretch",
    column_order=[
        "Session_ID", "Alert_Severity", "Battery_Temp_C", "Overstay_Mins",
        "Charger_Type", "User_Type", "Net_Billable_MYR",
    ],
)
# Export exactly the alert rows shown in the table above.
download_sessions(alerts, "Download alert sessions", "high_risk_sessions.csv")
st.caption(
    "Critical = an alert session above the selected threshold +5°C. "
    "This severity policy is used for display only; bills are unchanged."
)
