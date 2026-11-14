"""Cardurile cu cifre mari din capul paginilor."""

import pandas as pd
import streamlit as st


def site_kpis(telemetry: pd.DataFrame, hourly: pd.DataFrame) -> None:
    """KPI-urile unui site, din telemetrie si profilul orar."""
    now_kw = telemetry["consumption_kw"].iloc[-1]
    today = telemetry[telemetry["timestamp"].dt.date == telemetry["timestamp"].iloc[-1].date()]
    today_kwh = today["energy_kwh"].sum()
    peak = hourly.loc[hourly["avg_power_kw"].idxmax()]
    night = hourly[hourly["hour"].between(2, 5)]["avg_power_kw"].mean()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Consum acum", f"{now_kw:.2f} kW")
    c2.metric("Azi", f"{today_kwh:.1f} kWh")
    c3.metric("Ora de varf", f"{int(peak['hour'])}:00", delta=f"{peak['avg_power_kw']:.1f} kW",
              delta_color="off")
    c4.metric("Consum de noapte (2-5)", f"{night:.2f} kW")


def fleet_kpis(sites: pd.DataFrame, alerts: pd.DataFrame) -> None:
    """KPI-urile intregii flote, pe pagina O&M."""
    critical = int((alerts["severity"] == "CRITICAL").sum()) if not alerts.empty else 0
    loss = alerts["estimated_loss_kwh"].sum() if not alerts.empty else 0.0
    under_sla = int((sites["sla_availability_pct"] < 96).sum())

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Site-uri", len(sites))
    c2.metric("Alerte critice", critical)
    c3.metric("Pierderi estimate", f"{loss:.0f} kWh")
    c4.metric("Sub SLA 96%", under_sla)
