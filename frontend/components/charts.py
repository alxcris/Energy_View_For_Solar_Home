"""Charts reused across the pages."""

import pandas as pd
import plotly.graph_objects as go

from config import COLORS, SOLAR_WINDOW


def _shade_solar_window(fig: go.Figure, df: pd.DataFrame) -> None:
    """Yellow background over the solar window, for every day in the range."""
    for day in sorted(df["timestamp"].dt.normalize().unique()):
        day = pd.Timestamp(day)
        fig.add_vrect(x0=day + pd.Timedelta(hours=SOLAR_WINDOW[0]),
                      x1=day + pd.Timedelta(hours=SOLAR_WINDOW[1]),
                      fillcolor=COLORS["solar_window"], line_width=0)


def consumption_chart(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    _shade_solar_window(fig, df)
    fig.add_scatter(x=df["timestamp"], y=df["consumption_kw"], name="Consumption",
                    line=dict(color=COLORS["consumption"], width=2), fill="tozeroy",
                    fillcolor="rgba(76, 141, 246, 0.15)")
    fig.update_layout(height=400, yaxis_title="kW", hovermode="x unified",
                      showlegend=False, margin=dict(t=30, b=10, l=10, r=10))
    return fig


def hourly_profile_chart(df: pd.DataFrame, peak_hours: list[int] | None = None) -> go.Figure:
    peak_hours = peak_hours or []
    colors = [COLORS["peak"] if h in peak_hours else COLORS["bar"] for h in df["hour"]]
    fig = go.Figure(go.Bar(x=df["hour"], y=df["avg_power_kw"], marker_color=colors, marker_cornerradius=6))
    fig.add_vrect(x0=SOLAR_WINDOW[0] - 0.5, x1=SOLAR_WINDOW[1] - 0.5,
                  fillcolor=COLORS["solar_window"], line_width=0)
    fig.update_layout(height=350, xaxis_title="Hour", yaxis_title="kW (average)",
                      xaxis=dict(dtick=2), margin=dict(t=30, b=10, l=10, r=10))
    return fig


def monthly_chart(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure(go.Bar(x=df["month"], y=df["total_mwh"], marker_color=COLORS["bar"], marker_cornerradius=6))
    fig.update_layout(height=350, yaxis_title="MWh / month", margin=dict(t=30, b=10, l=10, r=10))
    return fig


def one_view_chart(df: pd.DataFrame) -> go.Figure:
    """The heart of the challenge: production, consumption, battery and grid on one chart."""
    fig = go.Figure()
    _shade_solar_window(fig, df)
    fig.add_scatter(x=df["timestamp"], y=df["pv_kw"], name="Solar",
                    line=dict(color=COLORS["solar"], width=2.5), fill="tozeroy",
                    fillcolor="rgba(245, 165, 36, 0.22)")
    fig.add_scatter(x=df["timestamp"], y=df["load_kw"], name="Home",
                    line=dict(color=COLORS["consumption"], width=2.5))
    fig.add_scatter(x=df["timestamp"], y=df["grid_kw"], name="Grid (+ buying / - selling)",
                    line=dict(color=COLORS["grid"], dash="dot", width=2.2))
    fig.add_scatter(x=df["timestamp"], y=df["battery_soc"], name="Battery (%)",
                    line=dict(color=COLORS["battery"], width=2.5), yaxis="y2")
    fig.update_layout(height=440, yaxis_title="kW", hovermode="x unified",
                      yaxis2=dict(overlaying="y", side="right", range=[0, 105], autorange=False,
                                  tickmode="linear", tick0=0, dtick=25, ticksuffix="%",
                                  showgrid=False, zeroline=False),
                      margin=dict(t=30, b=10, l=10, r=20))
    return fig


def pv_vs_expected_chart(df: pd.DataFrame) -> go.Figure:
    """Actual vs. weather-expected production - this is where a fault shows up."""
    fig = go.Figure()
    fig.add_scatter(x=df["timestamp"], y=df["expected_kw"], name="Expected (from weather)",
                    line=dict(color=COLORS["expected"], dash="dash"))
    fig.add_scatter(x=df["timestamp"], y=df["pv_kw"], name="Actual",
                    line=dict(color=COLORS["solar"], width=2.5))
    fig.update_layout(height=380, yaxis_title="kW", hovermode="x unified",
                      margin=dict(t=30, b=10, l=10, r=10))
    return fig


def daily_energy_chart(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure(go.Bar(x=df["day"], y=df["kwh"], marker_color=COLORS["bar"], marker_cornerradius=6))
    fig.update_layout(height=350, yaxis_title="kWh / day", margin=dict(t=30, b=10, l=10, r=10))
    return fig


def inverter_power_chart(df: pd.DataFrame) -> go.Figure:
    """For O&M: current vs. expected power, per inverter."""
    fig = go.Figure()
    fig.add_bar(x=df["name"], y=df["expected_power_kw"], name="Expected",
                marker_color=COLORS["expected"], marker_cornerradius=5)
    fig.add_bar(x=df["name"], y=df["current_power_kw"], name="Now",
                marker_color=COLORS["bar"], marker_cornerradius=5)
    fig.update_layout(height=350, barmode="group", yaxis_title="kW", margin=dict(t=30, b=10, l=10, r=10))
    return fig


# Colours for the battery plan: what the inverter is told to do in each quarter hour.
ACTION_BANDS = {
    "charge": ("rgba(5, 150, 105, 0.16)", "Charging from the sun"),
    "discharge": ("rgba(124, 58, 237, 0.14)", "Running the house from the battery"),
    "inject": ("rgba(8, 145, 178, 0.16)", "Selling to the grid"),
    "import": ("rgba(91, 107, 127, 0.07)", "Buying from the grid"),
}


def battery_plan_chart(df: pd.DataFrame) -> go.Figure:
    """Tomorrow's battery plan: state of charge against the price, with the
    inverter's action shaded underneath. This is the ML dispatch, drawn."""
    fig = go.Figure()
    if df.empty:
        return fig
    df = df.sort_values("timestamp_local")

    # shade each run of identical actions instead of one band per 15 minutes
    runs = (df["action"] != df["action"].shift()).cumsum()
    for _, part in df.groupby(runs):
        colour = ACTION_BANDS.get(str(part["action"].iloc[0]), (None, ""))[0]
        if not colour:
            continue
        fig.add_vrect(x0=part["timestamp_local"].iloc[0],
                      x1=part["timestamp_local"].iloc[-1] + pd.Timedelta(minutes=15),
                      fillcolor=colour, line_width=0, layer="below")

    fig.add_scatter(x=df["timestamp_local"], y=df["battery_soc"], name="Battery charge",
                    line=dict(color=COLORS["battery"], width=2.5), fill="tozeroy",
                    fillcolor="rgba(5, 150, 105, 0.10)")
    if "price_lei_kwh" in df:
        fig.add_scatter(x=df["timestamp_local"], y=df["price_lei_kwh"], name="Price (lei/kWh)",
                        line=dict(color=COLORS["price"], width=2, dash="dot"), yaxis="y2")
    fig.update_layout(height=350, hovermode="x unified",
                      yaxis=dict(title="Battery (%)", range=[0, 105]),
                      yaxis2=dict(overlaying="y", side="right", showgrid=False,
                                  ticksuffix=" lei", zeroline=False),
                      margin=dict(t=30, b=10, l=10, r=10))
    return fig
