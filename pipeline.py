

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

LOGGER = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent
CATEGORIES = {
    "Charger_Type": ("AC", "DC"),
    "User_Type": ("Student", "Staff", "Visitor"),
    "Grid_Status_Label": ("Normal", "Grid_Surge", "Overheated"),
}
NUMERIC = (
    "Start_Hour", "Duration_Mins", "Energy_kWh", "Overstay_Mins",
    "Battery_Temp_C",
)
REQUIRED = ("Session_ID", *CATEGORIES, *NUMERIC)


class DataValidationError(ValueError):
    """Describe a source-data problem that an operator can correct."""


@dataclass(frozen=True)
class Tariff:
    """Reproduce tariff rules verified against the supplied CSV."""

    ac_hourly_rate: float = 6.0
    dc_hourly_rate: float = 15.0
    peak_start: int = 12
    peak_end: int = 18
    peak_multiplier: float = 0.25
    overstay_grace_minutes: int = 15
    overstay_rate_per_minute: float = 0.5
    carbon_factor: float = 0.475


def read_csv(source):
    """Read a UTF-8 CSV from a path or upload and report useful errors."""
    try:
        return pd.read_csv(source, encoding="utf-8-sig")
    except (OSError, UnicodeError, pd.errors.ParserError,
            pd.errors.EmptyDataError) as error:
        raise DataValidationError(f"Cannot read CSV: {error}") from error


def clean_sessions(raw):
    """Impute numeric medians, normalise known labels and validate constraints.

    Invalid text and infinity are rejected rather than silently imputed.
    A missing identifier or unrecognised category is never guessed.
    """
    missing = set(REQUIRED) - set(raw.columns)
    if missing:
        raise DataValidationError(
            "Missing session columns: " + ", ".join(sorted(missing)))
    if raw.empty:
        raise DataValidationError("The session CSV contains no records.")
    clean = raw.copy(deep=True)  # Keep the supplied source records unchanged.
    ids = clean["Session_ID"].astype("string").str.strip()
    if ids.isna().any() or ids.eq("").any() or ids.duplicated().any():
        raise DataValidationError("Session_ID must be non-empty and unique.")
    clean["Session_ID"] = ids
    report = {"input_rows": len(raw), "imputed": {}, "normalised_labels": {}}

    for column, allowed in CATEGORIES.items():
        # Canonicalise whitespace/case only; unknown categories are data
        # errors.
        lookup = {value.casefold(): value for value in allowed}
        labels = clean[column].astype("string").str.strip().str.casefold()
        canonical = labels.map(lookup)
        if canonical.isna().any():
            bad = clean.loc[canonical.isna(), column].astype(str).unique()[:5]
            raise DataValidationError(f"Invalid {column}: {', '.join(bad)}")
        report["normalised_labels"][column] = int(
            clean[column].astype("string").ne(canonical).fillna(True).sum()
        )
        clean[column] = canonical

    for column in NUMERIC:
        # Only genuinely missing values are imputed; malformed text is
        # rejected.
        try:
            values = pd.to_numeric(clean[column], errors="raise")
        except (ValueError, TypeError) as error:
            raise DataValidationError(
                f"{column} must contain numeric values.") from error
        present = values.dropna().to_numpy(dtype=float)
        if not np.isfinite(present).all():
            raise DataValidationError(f"{column} contains infinite values.")
        count = int(values.isna().sum())
        median = float(values.median()) if len(present) else float("nan")
        if not np.isfinite(median):
            raise DataValidationError(
                f"No valid median is available for {column}.")
        report["imputed"][column] = {"count": count, "median": median}
        # Retain rows with missing cells.
        clean[column] = values.fillna(median)

    hours = clean["Start_Hour"]
    if not (hours.between(0, 23) & hours.mod(1).eq(0)).all():
        raise DataValidationError(
            "Start_Hour must contain integer hours from 0 to 23.")
    clean["Start_Hour"] = hours.astype(int)
    if clean["Duration_Mins"].le(0).any():
        raise DataValidationError("Duration_Mins must be greater than zero.")
    if (clean[["Energy_kWh", "Overstay_Mins"]] < 0).any().any():
        raise DataValidationError(
            "Energy_kWh and Overstay_Mins cannot be negative.")
    if "Session_Date" in clean.columns:
        clean["Session_Date"] = parse_dates(
            clean["Session_Date"], "Session_Date")
    return clean, report


def parse_dates(values, name):
    """Accept ISO dates without creating dates for undated source records."""
    text = values.astype("string").str.strip()
    if not text.str.fullmatch(r"\d{4}-\d{2}-\d{2}").fillna(False).all():
        raise DataValidationError(
            f"{name} must contain ISO dates such as 2026-04-19.")
    parsed = pd.to_datetime(text, format="%Y-%m-%d", errors="coerce")
    if parsed.isna().any():
        raise DataValidationError(f"{name} contains missing or invalid dates.")
    return parsed.dt.normalize()


def attach_session_dates(sessions, dates):
    """Join an optional date supplement by ID, never by unrelated row order."""
    if not {"Session_ID", "Session_Date"}.issubset(dates.columns):
        raise DataValidationError(
            "Date supplement needs Session_ID and Session_Date.")
    dates = dates[["Session_ID", "Session_Date"]].copy()
    dates["Session_ID"] = dates["Session_ID"].astype("string").str.strip()
    if dates["Session_ID"].isna().any(
    ) or dates["Session_ID"].duplicated().any():
        raise DataValidationError(
            "Date supplement IDs must be present and unique.")
    if set(dates["Session_ID"]) != set(sessions["Session_ID"]):
        raise DataValidationError(
            "Date supplement must match all session IDs exactly.")
    dates["Session_Date"] = parse_dates(dates["Session_Date"], "Session_Date")
    # validate='one_to_one' prevents an accidental many-to-many revenue
    # expansion.
    return sessions.drop(columns="Session_Date", errors="ignore").merge(
        dates, on="Session_ID", how="left", validate="one_to_one", sort=False,
    )


def engineer_features(sessions, tariff=Tariff()):
    """Derive power, carbon and bills independently of reference answers."""
    clean = sessions.copy(deep=True)
    clean["Duration_Hours"] = clean["Duration_Mins"] / 60.0  # Convert units.
    # Average charging power uses each session's actual energy and duration.
    clean["Power_Rate_kW"] = clean["Energy_kWh"] / clean["Duration_Hours"]
    # Apply the exam's carbon factor and round each session to two decimals.
    clean["Carbon_Savings_kgCO2"] = (
        clean["Energy_kWh"] * tariff.carbon_factor
    ).round(2)
    clean["Base_Rate_MYR"] = clean["Charger_Type"].map(
        {"AC": tariff.ac_hourly_rate, "DC": tariff.dc_hourly_rate}
    )
    clean["Base_Fee_MYR"] = clean["Duration_Hours"] * clean["Base_Rate_MYR"]
    # The peak window is [12:00, 18:00); the start hour sets the session
    # tariff.
    peak = clean["Start_Hour"].between(tariff.peak_start, tariff.peak_end - 1)
    clean["Peak_Surge_MYR"] = np.where(
        peak, clean["Base_Fee_MYR"] * tariff.peak_multiplier, 0.0,
    )
    clean["Overstay_Fee_MYR"] = (
        clean["Overstay_Mins"] - tariff.overstay_grace_minutes
    ).clip(lower=0) * tariff.overstay_rate_per_minute
    # Preserve unrounded intermediate fees and round the final bill once.
    # This reproduces the supplied CSV's float/round-to-even billing
    # convention.
    clean["Net_Billable_MYR"] = clean[
        ["Base_Fee_MYR", "Peak_Surge_MYR", "Overstay_Fee_MYR"]
    ].sum(axis=1).round(2)
    # The separate 15% risk surcharge in Section A is not added a second time.
    return clean


def alert_mask(sessions, threshold=40.0):
    """Identify strict >20 minute AND >threshold temperature alert sessions."""
    return sessions["Overstay_Mins"].gt(
        20) & sessions["Battery_Temp_C"].gt(threshold)


def filter_sessions(
        sessions,
        charger_types,
        minimum_energy=0.0,
        date_range=None,
        hour_range=None):
    """Apply a single inclusive filter consistently to every dashboard view."""
    mask = sessions["Charger_Type"].isin(charger_types)
    mask &= sessions["Energy_kWh"].ge(minimum_energy)
    if hour_range is not None:
        start_hour, end_hour = hour_range
        # Validate programmatic calls as well as the integer slider values.
        if (any(isinstance(hour, bool)
                or not isinstance(hour, (int, np.integer))
                for hour in hour_range)
                or not 0 <= start_hour <= end_hour <= 23):
            raise DataValidationError(
                "Start-hour range needs integer endpoints from 0 to 23.")
        # Both endpoints are included: (6, 10) keeps hours 6 through 10.
        mask &= sessions["Start_Hour"].between(start_hour, end_hour)
    if date_range is not None:
        if "Session_Date" not in sessions.columns:
            raise DataValidationError(
                "Session dates are needed for date filtering.")
        start, end = date_range
        mask &= sessions["Session_Date"].between(
            pd.Timestamp(start), pd.Timestamp(end))
    return sessions.loc[mask].copy()  # Preserve the complete source dataset.


def summary_metrics(sessions, threshold=40.0):
    """Return selection totals, including zeros for an empty selection."""
    return {
        "sessions": len(sessions),
        "energy_kwh": round(float(sessions["Energy_kWh"].sum()), 2),
        "carbon_kg": round(float(sessions["Carbon_Savings_kgCO2"].sum()), 2),
        "revenue_myr": round(float(sessions["Net_Billable_MYR"].sum()), 2),
        "alerts": int(alert_mask(sessions, threshold).sum()),
    }


def prepare_sessions(source, dates_source=None):
    """Run the full transformation without mutating source files."""
    sessions, report = clean_sessions(read_csv(source))
    if dates_source is not None:
        sessions = attach_session_dates(sessions, read_csv(dates_source))
    return engineer_features(sessions), report


def write_outputs(clean, report, output_dir):
    """Export the required cleaned CSV, statistics and data-quality audit."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    # Write inside the output directory so the original supplied data stay
    # intact.
    clean.to_csv(output_dir / "cleaned_energy_sales_data.csv", index=False)
    clean.describe(include="all").to_csv(output_dir / "summary_statistics.csv")
    report = dict(report, metrics=summary_metrics(clean), python=sys.version)
    (output_dir / "data_quality_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8",
    )
    return report


def main():
    """Provide an executable pipeline for PyCharm and terminal evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT /
                        "data/ev_campus_dataset.csv")
    parser.add_argument("--dates", type=Path, default=None)
    parser.add_argument("--telemetry", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s: %(message)s")
    try:
        clean, report = prepare_sessions(args.input, args.dates)
        report = write_outputs(clean, report, args.output_dir)
        from visuals import export_charts, load_telemetry

        telemetry = load_telemetry(args.telemetry) if args.telemetry else None
        export_charts(clean, telemetry, args.output_dir)
        output = json.dumps(report, indent=2) + "\n\n" + \
            clean.describe().to_string()
        print(output)  # Show descriptive statistics in the PyCharm console.
        (args.output_dir / "execution_output.txt").write_text(
            output, encoding="utf-8"
        )
        LOGGER.info(
            "Exported cleaned sessions, statistics and charts to %s",
            args.output_dir)
    except (DataValidationError, OSError, ValueError) as error:
        LOGGER.error("Pipeline failed: %s", error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
