"""Validate retail transactions and build sales analysis for Python 3.10."""

import json
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

from pipeline import DataValidationError, parse_dates, read_csv

ROOT = Path(__file__).resolve().parent
SALES_CATEGORIES = {
    "Hub_Location": ("Lakeside_Hub", "Subang_Hub", "KL_Campus_Hub",
                     "Taylor_Tower_Hub"),
    "Category": ("Charging_Service", "EV_Accessory", "Energy_Credit",
                 "Fleet_Pass"),
    "Customer_Type": ("Student", "Staff", "Public_Fleet"),
    "Payment_Method": ("TouchNGo", "Credit_Card", "Campus_Wallet"),
}
SALES_NUMERIC = ("Units_Sold", "Unit_Price_MYR", "Total_Revenue_MYR")
SALES_REQUIRED = ("Transaction_ID", *SALES_CATEGORIES, *SALES_NUMERIC,
                  "Transaction_Date")


def prepare_sales(source):
    """Recover transaction arithmetic before a labelled median estimate."""
    raw = read_csv(source)
    missing = set(SALES_REQUIRED) - set(raw.columns)
    if missing or raw.empty:
        raise DataValidationError(
            "Sales CSV is empty or missing columns: "
            + ", ".join(sorted(missing)))
    data = raw.copy(deep=True)  # Leave the supplied CSV unchanged.
    ids = data["Transaction_ID"].astype("string").str.strip()
    if ids.isna().any() or ids.eq("").any() or ids.duplicated().any():
        raise DataValidationError("Transaction_ID must be present and unique.")
    data["Transaction_ID"] = ids
    for column, allowed in SALES_CATEGORIES.items():
        lookup = {label.casefold(): label for label in allowed}
        labels = data[column].astype("string").str.strip().str.casefold()
        data[column] = labels.map(lookup)
        if data[column].isna().any():
            raise DataValidationError(f"Unknown sales category in {column}.")
    data["Transaction_Date"] = parse_dates(
        data["Transaction_Date"], "Transaction_Date")
    for column in SALES_NUMERIC:
        try:
            values = pd.to_numeric(data[column], errors="raise")
        except (TypeError, ValueError) as error:
            raise DataValidationError(f"{column} must be numeric.") from error
        if (not np.isfinite(values.dropna()).all()
                or values.dropna().lt(0).any()):
            raise DataValidationError(f"Invalid negative/infinite {column}.")
        data[column] = values
    if data["Unit_Price_MYR"].isna().any():
        raise DataValidationError("A unit price is required for each sale.")

    missing_units = data["Units_Sold"].isna()
    missing_revenue = data["Total_Revenue_MYR"].isna()
    median_units = float(data["Units_Sold"].median())
    recovered = (missing_units & ~missing_revenue
                 & data["Unit_Price_MYR"].gt(0))
    # Existing revenue and price recover missing quantity without guessing.
    data.loc[recovered, "Units_Sold"] = (
        data.loc[recovered, "Total_Revenue_MYR"]
        / data.loc[recovered, "Unit_Price_MYR"]
    )
    estimated = data["Units_Sold"].isna()
    if estimated.any():
        if not np.isfinite(median_units):
            raise DataValidationError("No median quantity is available.")
        data.loc[estimated, "Units_Sold"] = median_units
    if data["Units_Sold"].mod(1).ne(0).any():
        raise DataValidationError("Sales quantities must be whole units.")
    data["Units_Sold"] = data["Units_Sold"].astype(int)
    expected = (data["Units_Sold"] * data["Unit_Price_MYR"]).round(2)
    # Restore missing revenue using the quantity and price of the same row.
    data.loc[missing_revenue, "Total_Revenue_MYR"] = expected[missing_revenue]
    if not np.isclose(data["Total_Revenue_MYR"], expected, atol=0.005,
                      rtol=0).all():
        raise DataValidationError(
            "Sales revenue conflicts with quantity × price.")
    # Preserve row-level evidence of recovered and estimated values in exports.
    data["Units_Recovered"] = recovered
    data["Units_Imputed"] = estimated
    data["Revenue_Reconstructed"] = missing_revenue
    quality = {
        "input_rows": len(raw), "missing_units": int(missing_units.sum()),
        "missing_revenue": int(missing_revenue.sum()),
        "units_recovered": int(recovered.sum()),
        "units_estimated": int(estimated.sum()), "median_units": median_units,
        "revenue_reconstructed": int(missing_revenue.sum()),
    }
    return data, quality


def filter_sales(data, date_range, hubs, categories, customers):
    """Apply inclusive transaction dates and all selected retail categories."""
    start, end = map(pd.Timestamp, date_range)
    mask = data["Transaction_Date"].between(start, end)
    mask &= data["Hub_Location"].isin(hubs)
    mask &= data["Category"].isin(categories)
    mask &= data["Customer_Type"].isin(customers)
    # Reuse these exact rows for every sales view.
    return data.loc[mask].copy()


def sales_metrics(data):
    """Return sales-only totals, with zero values for empty filter results."""
    count = len(data)
    revenue = float(data["Total_Revenue_MYR"].sum())
    return {
        "revenue": round(revenue, 2), "units": int(data["Units_Sold"].sum()),
        "transactions": count,
        "average": round(revenue / count, 2) if count else 0.0,
    }


def build_sales_chart(kind, data, date_range):
    """Plot daily revenue or a ranked sales breakdown in a fresh figure."""
    fig, ax = plt.subplots(figsize=(10, 4.6), layout="constrained")
    if data.empty:
        ax.text(0.5, 0.5, "No transactions match the selected filters.",
                ha="center", va="center", transform=ax.transAxes)
        ax.axis("off")
        return fig
    if kind == "daily":
        # Include selected dates with zero sales in the daily revenue line.
        days = pd.date_range(*date_range, freq="D")
        totals = data.groupby("Transaction_Date")["Total_Revenue_MYR"].sum()
        totals = totals.reindex(days, fill_value=0)
        ax.plot(totals.index, totals.values, color="#2475A8",
                marker="o", markersize=4, linewidth=2)
        ax.set(title="Daily sales revenue", xlabel="Transaction date")
        ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=3,
                                                          maxticks=7))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    elif kind in {"hub", "category"}:
        column = "Hub_Location" if kind == "hub" else "Category"
        totals = data.groupby(column)["Total_Revenue_MYR"].sum()
        totals = totals.sort_values(
            ascending=False).rename("Revenue").reset_index()
        totals[column] = totals[column].str.replace("_", " ", regex=False)
        sns.barplot(data=totals, x="Revenue", y=column, color="#2475A8",
                    errorbar=None, ax=ax)
        title = "Revenue by hub" if kind == "hub" else "Revenue by category"
        ax.set(title=title,
               xlabel="Revenue (MYR)", ylabel="")
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="x", alpha=0.22)
        ax.set_axisbelow(True)
        return fig
    else:
        plt.close(fig)
        raise ValueError(f"Unknown sales chart: {kind}")
    ax.set(ylabel="Revenue (MYR)", ylim=(0, None))
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.22)
    ax.set_axisbelow(True)
    return fig


def main():
    """Export validated sales records and a reproducible quality summary."""
    data, quality = prepare_sales(ROOT / "data/sales_data.csv")
    output = ROOT / "outputs"
    output.mkdir(exist_ok=True)
    data.to_csv(output / "cleaned_sales_data.csv", index=False,
                date_format="%Y-%m-%d")
    summary = dict(quality, metrics=sales_metrics(data))
    (output / "sales_quality_report.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(data.describe().to_string())


if __name__ == "__main__":
    main()
