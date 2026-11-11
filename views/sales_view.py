"""Show retail sales metrics, dated charts and transaction downloads."""

from io import BytesIO
from pathlib import Path

import matplotlib.pyplot as plt
import streamlit as st

from dashboard import download_sessions
from pipeline import DataValidationError
from sales import (
    build_sales_chart, filter_sales, prepare_sales, sales_metrics,
)

ROOT = Path(__file__).resolve().parents[1]


@st.cache_data(show_spinner=False)
def load_sales(raw_bytes):
    """Invalidate cached preparation whenever the local sales CSV changes."""
    return prepare_sales(BytesIO(raw_bytes))


try:
    sales, quality = load_sales((ROOT / "data/sales_data.csv").read_bytes())
except (DataValidationError, OSError, ValueError) as error:
    st.error(f"Unable to load sales transactions: {error}")
    st.stop()

with st.sidebar:
    st.header("Sales controls")
    st.caption("Filter sales transactions")
    first = sales["Transaction_Date"].min().date()
    last = sales["Transaction_Date"].max().date()
    dates = st.date_input(
        "Transaction date range", value=(first, last), min_value=first,
        max_value=last, format="YYYY-MM-DD", key="sales_date_range")
    if len(dates) != 2:
        st.caption("Choose both the first and last transaction date.")
        st.stop()
    hubs = sorted(sales["Hub_Location"].unique().tolist())
    categories = sorted(sales["Category"].unique().tolist())
    customers = sorted(sales["Customer_Type"].unique().tolist())
    selected_hubs = st.multiselect(
        "Hub location", hubs, default=hubs, key="sales_hubs")
    selected_categories = st.multiselect(
        "Sales category", categories, default=categories,
        key="sales_categories")
    selected_customers = st.multiselect(
        "Customer type", customers, default=customers, key="sales_customers")
    if st.button("Reset sales filters", width="stretch"):
        for key in ("sales_date_range", "sales_hubs", "sales_categories",
                    "sales_customers"):
            st.session_state.pop(key, None)
        st.rerun()

# Every sales chart, metric and export uses this same filtered DataFrame.
visible = filter_sales(sales, dates, selected_hubs, selected_categories,
                       selected_customers)
st.title("Campus Sales Performance")
st.caption("Sales revenue, product demand and campus hub performance")
st.caption(
    f"{len(visible):,} of {len(sales):,} transactions · "
    f"{dates[0]:%d %b %Y}–{dates[1]:%d %b %Y}. "
    "Deltas compare this selection with all loaded sales transactions.")
current, baseline = sales_metrics(visible), sales_metrics(sales)
fields = [("Sales revenue", "revenue", "MYR"), ("Units sold", "units", ""),
          ("Transactions", "transactions", ""),
          ("Average transaction", "average", "MYR")]
for column, (label, key, unit) in zip(st.columns(4), fields):
    value = current[key]
    difference = round(value - baseline[key], 2)
    display = f"{value:,.2f} {unit}" if unit else f"{value:,}"
    delta = f"{difference:+,.2f} {unit}" if unit else f"{difference:+,}"
    column.metric(label, display, delta=delta, delta_color="off")
estimated = int(visible["Units_Imputed"].sum())
if estimated:
    st.caption(f"{estimated} selected transaction uses an estimated quantity; "
               "its revenue is calculated from that quantity and unit price.")

if visible.empty:
    st.info("No sales transactions match. Change the sales filters.")
else:
    for kind, heading in [("daily", "Sales over time"),
                          ("hub", "Campus hub performance"),
                          ("category", "Product and service sales")]:
        st.subheader(heading)
        fig = build_sales_chart(kind, visible, dates)
        try:
            st.pyplot(fig, width="stretch")
        finally:
            plt.close(fig)  # Release figures between interactive reruns.

st.subheader("Filtered sales transactions")
display_rows = visible.sort_values(
    ["Transaction_Date", "Transaction_ID"], ascending=[False, True])
download_sessions(display_rows, "Download filtered sales",
                  "filtered_sales.csv")
st.dataframe(display_rows, hide_index=True, width="stretch", height=400)
with st.expander("Sales data preparation"):
    st.write(
        f"Source: data/sales_data.csv · {quality['input_rows']} transactions. "
        f"{quality['units_recovered']} missing quantities were recovered from "
        "the same transaction's revenue and unit price. "
        f"{quality['units_estimated']} quantity was filled with the source "
        f"median ({quality['median_units']:g} units). "
        f"{quality['revenue_reconstructed']} missing revenues were calculated "
        "as quantity × unit price.")
    st.caption(
        "Units_Recovered, Units_Imputed and Revenue_Reconstructed identify "
        "the affected rows in the table and downloaded CSV.")
