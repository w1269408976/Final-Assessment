
from pipeline import DataValidationError, read_csv
import seaborn as sns
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path

import matplotlib

matplotlib.use("Agg")


BLUE = "#2475A8"
TEAL = "#158575"
ORANGE = "#D18B21"
USER_ORDER = ["Student", "Staff", "Visitor"]


def load_telemetry(source):
    """Validate an optional hourly campus feed with actual measured power.

    Columns: Timestamp, Grid_Demand_kW, Solar_Generation_kW.
    Timestamps must be unique, on the hour and use one consistent timezone.
    Missing measurements and temporal gaps are not filled with invented values.
    """
    data = read_csv(source)
    required = ["Timestamp", "Grid_Demand_kW", "Solar_Generation_kW"]
    if not set(required).issubset(data.columns) or data.empty:
        raise DataValidationError(
            "Telemetry needs Timestamp, Grid_Demand_kW "
            "and Solar_Generation_kW.")
    data = data[required].copy()
    try:
        timestamp = pd.to_datetime(data["Timestamp"], errors="raise")
        if not pd.api.types.is_datetime64_any_dtype(timestamp):
            raise ValueError("Use timestamps with a consistent timezone.")
        if timestamp.isna().any() or timestamp.duplicated().any():
            raise ValueError("Timestamps must be present and unique.")
        if not timestamp.eq(timestamp.dt.floor("h")).all():
            raise ValueError("Telemetry must contain readings on the hour.")
        data["Timestamp"] = timestamp
        for column in required[1:]:
            values = pd.to_numeric(data[column], errors="raise")
            if not np.isfinite(values).all() or values.lt(0).any():
                raise ValueError(
                    "Power values must be finite and non-negative.")
            data[column] = values
    except (ValueError, TypeError, AttributeError) as error:
        raise DataValidationError(f"Invalid telemetry: {error}") from error
    return data.sort_values("Timestamp").reset_index(drop=True)


def style_axes(ax):
    """Use clear labels and restrained grids for facility-manager reporting."""
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.22)
    ax.set_axisbelow(True)


def draw_grid_panel(ax, sessions, telemetry=None, hour_range=None):
    """Plot measured grid/solar curves, or identify the missing-source gap."""
    if telemetry is None or telemetry.empty:
        # A categorical grid status cannot be converted into measured kW.
        first, last = hour_range if hour_range is not None else (0, 23)
        # Show only selected hours, including zero-energy hours in that range.
        hourly = sessions.groupby("Start_Hour")[
            "Energy_kWh"].sum().reindex(range(first, last + 1), fill_value=0)
        ax.plot(hourly.index, hourly.values,
                color=BLUE, linewidth=2, marker=".")
        ax.set(
            title="Hourly EV charging energy",
            xlabel="Session start hour",
            ylabel="EV energy across sessions (kWh)",
            xticks=range(first, last + 1, 1 if last - first <= 12 else 2),
            xlim=(first - 0.5, last + 0.5),
            ylim=(
                0,
                None),
        )
        ax.text(
            0.01, 0.97,
            "Total delivered energy for sessions starting in each hour.",
            transform=ax.transAxes, va="top", fontsize=9,
        )
    else:
        # Reindex inserts gaps as NaN, avoiding misleading lines across missing
        # hours.
        readings = telemetry.set_index("Timestamp")
        timeline = pd.date_range(readings.index.min(),
                                 readings.index.max(), freq="h")
        if len(timeline) > 200_000:
            raise DataValidationError(
                "Telemetry range exceeds 200,000 hourly points.")
        readings = readings.reindex(timeline)
        ax.plot(readings.index, readings["Grid_Demand_kW"],
                color=BLUE, label="Grid demand", linewidth=2)
        ax.plot(readings.index, readings["Solar_Generation_kW"],
                color=ORANGE, label="Solar generation", linewidth=2)
        peak = telemetry.loc[telemetry["Grid_Demand_kW"].idxmax()]
        ax.annotate(
            f"Peak {peak.Grid_Demand_kW:,.1f} kW",
            xy=(peak.Timestamp, peak.Grid_Demand_kW), xytext=(8, -18),
            textcoords="offset points", fontsize=9,
        )
        ax.set(title="Hourly campus grid demand and solar generation",
               xlabel="Timestamp", ylabel="Power (kW)", ylim=(0, None))
        ax.legend(frameon=False)
        ax.tick_params(axis="x", rotation=20)
    style_axes(ax)


def draw_cost_panel(ax, sessions):
    """Compare complete session bills using a Seaborn categorical box plot."""
    # Fix category order so filtering never changes the meaning of positions.
    sns.boxplot(
        data=sessions, x="User_Type", y="Net_Billable_MYR", order=USER_ORDER,
        color=BLUE, width=0.55, fliersize=3, linewidth=1, ax=ax,
    )
    ax.set(title="Charging session cost by user type",
           xlabel="User type", ylabel="Session bill (MYR)", ylim=(0, None))
    style_axes(ax)


def draw_temperature_panel(ax, sessions):
    """Plot observed temperature/energy and descriptive linear trendlines."""
    for charger, colour in [("AC", BLUE), ("DC", ORANGE)]:
        group = sessions.loc[sessions["Charger_Type"].eq(charger)]
        if group.empty:
            continue  # Skip charger types removed by the shared filters.
        sns.scatterplot(
            data=group, x="Battery_Temp_C", y="Energy_kWh", color=colour,
            label=f"{charger} sessions", s=22, alpha=0.45, ax=ax,
        )
        # A trendline requires distinct x values; no bootstrap CI is implied.
        if len(group) >= 2 and group["Battery_Temp_C"].nunique() >= 2:
            sns.regplot(
                data=group, x="Battery_Temp_C", y="Energy_kWh", scatter=False,
                ci=None, color=colour, line_kws={"linewidth": 2}, ax=ax,
            )
    ax.set(
        title="Battery temperature and energy delivered",
        xlabel="Battery temperature (°C)",
        ylabel="Energy delivered (kWh)",
        ylim=(
            0,
            None))
    handles, _ = ax.get_legend_handles_labels()
    if handles:
        ax.legend(frameon=False)
    style_axes(ax)


def build_panel(kind, sessions, telemetry=None, hour_range=None):
    """Return one figure without retaining global plot state between reruns."""
    sns.set_theme(style="white", font_scale=0.95)
    # Constrained layout reserves space for axis labels and annotations.
    fig, ax = plt.subplots(figsize=(10, 4.6), layout="constrained")
    if sessions.empty and kind != "grid":
        ax.text(0.5, 0.5, "No sessions match the selected filters.",
                ha="center", va="center", transform=ax.transAxes)
        ax.axis("off")
    elif kind == "grid":
        draw_grid_panel(ax, sessions, telemetry, hour_range=hour_range)
    elif kind == "cost":
        draw_cost_panel(ax, sessions)
    elif kind == "temperature":
        draw_temperature_panel(ax, sessions)
    else:
        raise ValueError(f"Unknown panel: {kind}")
    return fig


def export_charts(sessions, telemetry, output_dir):
    """Save three individual panels and one labelled three-panel figure."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for kind in ("grid", "cost", "temperature"):
        fig = build_panel(kind, sessions, telemetry)
        fig.savefig(output_dir / f"panel_{kind}.png", dpi=220)
        plt.close(fig)
    fig, axes = plt.subplots(3, 1, figsize=(11, 14), layout="constrained")
    draw_grid_panel(axes[0], sessions, telemetry)
    draw_cost_panel(axes[1], sessions)
    draw_temperature_panel(axes[2], sessions)
    fig.suptitle("Smart Campus Energy and EV Operations",
                 fontsize=16, fontweight="bold")
    fig.savefig(output_dir / "three_panel_analysis.png", dpi=220)
    plt.close(fig)
