"""Dashboard-ul echipei O&M: toate site-urile, invertoarele si alertele,
cu pierderile estimate - problema "faults found after the damage"."""

import pandas as pd
import streamlit as st

from components.charts import inverter_power_chart
from components.kpi_cards import fleet_kpis
from config import SEVERITY_ORDER
from services import api_client

st.set_page_config(page_title="Echipa O&M", layout="wide")

st.title("Echipa O&M")
st.caption("Toate instalatiile si problemele lor, intr-un singur loc")
api_client.api_status_banner()

sites = api_client.get_sites()
alerts = api_client.get_alerts()

fleet_kpis(sites, alerts)

st.subheader("Alerte active")
if alerts.empty:
    st.success("Nicio alerta activa.")
else:
    df = alerts.merge(sites[["site_id", "name"]], on="site_id", how="left")
    df["_ord"] = df["severity"].map(SEVERITY_ORDER).fillna(9)
    df = df.sort_values(["_ord", "estimated_loss_kwh"], ascending=[True, False])
    st.dataframe(
        df[["severity", "name", "message", "estimated_loss_kwh"]],
        column_config={
            "severity": "Gravitate",
            "name": "Site",
            "message": "Problema",
            "estimated_loss_kwh": st.column_config.NumberColumn("Pierdere estimata (kWh)",
                                                                format="%.1f"),
        },
        hide_index=True, width="stretch",
    )

st.subheader("Site-uri")
view = sites.copy()
view["delta_kw"] = (view["total_current_power_kw"] - view["total_expected_power_kw"]).round(2)
st.dataframe(
    view[["site_id", "name", "status", "sla_availability_pct",
          "total_current_power_kw", "total_expected_power_kw", "delta_kw"]],
    column_config={
        "site_id": "ID", "name": "Nume", "status": "Status",
        "sla_availability_pct": st.column_config.NumberColumn("SLA (%)", format="%.1f"),
        "total_current_power_kw": "Acum (kW)",
        "total_expected_power_kw": "Asteptat (kW)",
        "delta_kw": "Diferenta (kW)",
    },
    hide_index=True, width="stretch",
)

st.subheader("Invertoarele unui site")
options = dict(zip(sites["name"], sites["site_id"]))
name = st.selectbox("Site", list(options))
inverters = api_client.get_inverters(options[name])
if inverters.empty:
    st.info("Site-ul nu are invertoare inregistrate.")
else:
    left, right = st.columns([2, 3])
    with left:
        st.dataframe(
            inverters[["name", "brand", "status", "battery_soc_pct", "gsm_signal_dbm"]],
            column_config={
                "name": "Invertor", "brand": "Marca", "status": "Status",
                "battery_soc_pct": st.column_config.NumberColumn("Baterie (%)", format="%.0f"),
                "gsm_signal_dbm": "Semnal GSM (dBm)",
            },
            hide_index=True, width="stretch",
        )
    with right:
        st.plotly_chart(inverter_power_chart(inverters), width="stretch")

with st.expander("Contextul trimis serviciului AI (ai-context)"):
    st.json(api_client.get_ai_context(options[name]))
