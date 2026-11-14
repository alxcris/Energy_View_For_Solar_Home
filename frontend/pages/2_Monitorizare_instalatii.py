"""Monitorizarea instalatiilor (echipa de operare si mentenanta a PPC):
toate site-urile, alertele si cat costa fiecare problema - raspunsul la
"faults found after the damage"."""

import pandas as pd
import streamlit as st

from components.charts import inverter_power_chart, pv_vs_expected_chart
from components.kpi_cards import fleet_kpis
from config import SEVERITY_ORDER
from services import api_client, ml_source

st.set_page_config(page_title="Monitorizare instalatii", layout="wide")

st.title("Monitorizare instalatii")
st.caption("Toate instalatiile si problemele lor, intr-un singur loc - "
           "pentru echipa de operare si mentenanta")
api_client.api_status_banner()

# --- Varianta cu pipeline-ul ML: alerte cu pierderea in lei ------------------
if ml_source.available():
    sites = ml_source.get_sites()
    alerts = ml_source.get_alerts()
    active = alerts[alerts["ongoing"].astype(bool)]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Instalatii", len(sites))
    c2.metric("Alerte active", len(active))
    c3.metric("Lei in joc (active)", f"{active['lost_lei'].sum():.0f}")
    c4.metric("Critice", int((alerts["severity"] == "critical").sum()))

    st.subheader("Alerte, cele mai scumpe primele")
    show = alerts.sort_values("lost_lei", ascending=False)
    st.dataframe(
        show[["site_name", "type", "severity", "detected_at", "ongoing",
              "lost_kwh", "lost_lei", "action"]],
        column_config={
            "site_name": "Instalatie", "type": "Tip", "severity": "Gravitate",
            "detected_at": st.column_config.DatetimeColumn("Detectata", format="DD.MM HH:mm"),
            "ongoing": "Activa",
            "lost_kwh": st.column_config.NumberColumn("Pierdut (kWh)", format="%.0f"),
            "lost_lei": st.column_config.NumberColumn("Pierdut (lei)", format="%.0f"),
            "action": "Actiune recomandata",
        },
        hide_index=True, width="stretch",
    )

    st.subheader("Productia unei instalatii: asteptat vs. real")
    options = dict(zip(sites["name"], sites["site_id"]))
    name = st.selectbox("Instalatie", list(options))
    ts = ml_source.get_timeseries(options[name], days=7)
    st.caption("Ultimele 7 zile. O 'groapa' fata de linia gri inseamna un defect "
               "sau date pierdute.")
    st.plotly_chart(pv_vs_expected_chart(ts), width="stretch")
    st.stop()

# --- Varianta pe backend / mock ----------------------------------------------
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
