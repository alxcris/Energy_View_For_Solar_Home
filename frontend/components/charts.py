"""Graficele refolosite in pagini."""

import pandas as pd
import plotly.graph_objects as go

from config import COLORS, SOLAR_WINDOW


def _shade_solar_window(fig: go.Figure, df: pd.DataFrame) -> None:
    """Fundal galben pe fereastra solara, pentru fiecare zi din interval."""
    for day in sorted(df["timestamp"].dt.normalize().unique()):
        day = pd.Timestamp(day)
        fig.add_vrect(x0=day + pd.Timedelta(hours=SOLAR_WINDOW[0]),
                      x1=day + pd.Timedelta(hours=SOLAR_WINDOW[1]),
                      fillcolor=COLORS["solar_window"], line_width=0)


def consumption_chart(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    _shade_solar_window(fig, df)
    fig.add_scatter(x=df["timestamp"], y=df["consumption_kw"], name="Consum",
                    line_color=COLORS["consumption"], fill="tozeroy")
    fig.update_layout(height=340, yaxis_title="kW", hovermode="x unified",
                      showlegend=False, margin=dict(t=10, b=10))
    return fig


def hourly_profile_chart(df: pd.DataFrame, peak_hours: list[int] | None = None) -> go.Figure:
    peak_hours = peak_hours or []
    colors = [COLORS["peak"] if h in peak_hours else COLORS["bar"] for h in df["hour"]]
    fig = go.Figure(go.Bar(x=df["hour"], y=df["avg_power_kw"], marker_color=colors))
    fig.add_vrect(x0=SOLAR_WINDOW[0] - 0.5, x1=SOLAR_WINDOW[1] - 0.5,
                  fillcolor=COLORS["solar_window"], line_width=0)
    fig.update_layout(height=300, xaxis_title="Ora", yaxis_title="kW (medie)",
                      xaxis=dict(dtick=2), margin=dict(t=10, b=10))
    return fig


def monthly_chart(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure(go.Bar(x=df["month"], y=df["total_mwh"], marker_color=COLORS["bar"]))
    fig.update_layout(height=300, yaxis_title="MWh / luna", margin=dict(t=10, b=10))
    return fig


def one_view_chart(df: pd.DataFrame) -> go.Figure:
    """Miezul challenge-ului: productie, consum, baterie si retea pe un singur grafic."""
    fig = go.Figure()
    _shade_solar_window(fig, df)
    fig.add_scatter(x=df["timestamp"], y=df["pv_kw"], name="Solar",
                    line_color="#F5B700", fill="tozeroy")
    fig.add_scatter(x=df["timestamp"], y=df["load_kw"], name="Casa",
                    line_color=COLORS["consumption"])
    fig.add_scatter(x=df["timestamp"], y=df["grid_kw"], name="Retea (+ cumperi / - vinzi)",
                    line=dict(color=COLORS["peak"], dash="dot"))
    fig.add_scatter(x=df["timestamp"], y=df["battery_soc"], name="Baterie (%)",
                    line_color="#2EC4B6", yaxis="y2")
    fig.update_layout(height=380, yaxis_title="kW", hovermode="x unified",
                      yaxis2=dict(overlaying="y", side="right", range=[0, 100],
                                  title="Baterie (%)", showgrid=False),
                      margin=dict(t=10, b=10))
    return fig


def pv_vs_expected_chart(df: pd.DataFrame) -> go.Figure:
    """Productia reala vs. cea asteptata din vreme - aici se vede un defect."""
    fig = go.Figure()
    fig.add_scatter(x=df["timestamp"], y=df["expected_kw"], name="Asteptat (din vreme)",
                    line=dict(color=COLORS["expected"], dash="dash"))
    fig.add_scatter(x=df["timestamp"], y=df["pv_kw"], name="Real",
                    line_color="#F5B700")
    fig.update_layout(height=320, yaxis_title="kW", hovermode="x unified",
                      margin=dict(t=10, b=10))
    return fig


def daily_energy_chart(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure(go.Bar(x=df["day"], y=df["kwh"], marker_color=COLORS["bar"]))
    fig.update_layout(height=300, yaxis_title="kWh / zi", margin=dict(t=10, b=10))
    return fig


def inverter_power_chart(df: pd.DataFrame) -> go.Figure:
    """Pe O&M: puterea curenta vs. cea asteptata, per invertor."""
    fig = go.Figure()
    fig.add_bar(x=df["name"], y=df["expected_power_kw"], name="Asteptat",
                marker_color=COLORS["expected"])
    fig.add_bar(x=df["name"], y=df["current_power_kw"], name="Acum",
                marker_color=COLORS["bar"])
    fig.update_layout(height=300, barmode="group", yaxis_title="kW", margin=dict(t=10, b=10))
    return fig
