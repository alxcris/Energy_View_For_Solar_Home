"""Analiza consumului unui site: curba la 15 min, profilul orar si istoricul.
Aici se vede DE CE primeste clientul recomandarile pe care le primeste."""

import streamlit as st

from components.charts import (consumption_chart, daily_energy_chart, hourly_profile_chart,
                               monthly_chart, pv_vs_expected_chart)
from components.kpi_cards import site_kpis
from config import SOLAR_WINDOW
from services import api_client, ml_source

st.set_page_config(page_title="Analiza consum", layout="wide")

use_ml = ml_source.available()
api_client.api_status_banner()

sites = ml_source.get_sites() if use_ml else api_client.get_sites()
if sites.empty:
    st.error("Nu exista site-uri. Porneste backend-ul sau ruleaza seed-ul.")
    st.stop()

options = dict(zip(sites["name"], sites["site_id"]))
col1, col2 = st.columns([3, 1])
name = col1.selectbox("Instalatie", list(options))
days = col2.selectbox("Interval", [1, 2, 3, 7], format_func=lambda d: f"Ultimele {d} zile")
site_id = options[name]

if use_ml:
    telemetry = ml_source.get_timeseries(site_id, days=days)
    hourly = ml_source.get_hourly_profile(site_id)
else:
    telemetry = api_client.get_telemetry(site_id, limit=days * 96)
    hourly = api_client.get_hourly_profile(site_id)

st.title(name)
site_kpis(telemetry, hourly)

st.subheader("Consumul la 15 minute")
st.caption(f"Fundalul galben e fereastra solara ({SOLAR_WINDOW[0]}:00-{SOLAR_WINDOW[1]}:00): "
           "acolo vrem sa mutam consumul flexibil.")
st.plotly_chart(consumption_chart(telemetry), width="stretch")

if use_ml:
    st.subheader("Productia: asteptata din vreme vs. reala")
    st.caption("Cand linia reala coboara sub cea asteptata, ceva e in neregula - "
               "de aici pornesc alertele echipei de monitorizare.")
    st.plotly_chart(pv_vs_expected_chart(telemetry), width="stretch")

left, right = st.columns(2)
with left:
    st.subheader("Profilul mediu orar")
    peaks = hourly.nlargest(3, "avg_power_kw")["hour"].tolist()
    st.caption("Rosu = cele 3 ore de varf. Galben = fereastra solara.")
    st.plotly_chart(hourly_profile_chart(hourly, peaks), width="stretch")
with right:
    if use_ml:
        st.subheader("Energia pe zile")
        st.caption("Ultimele 14 zile, din datele pipeline-ului ML.")
        st.plotly_chart(daily_energy_chart(ml_source.get_daily_energy(site_id)), width="stretch")
    else:
        st.subheader("Istoric lunar")
        st.caption("Sezonalitatea consumului, direct din curba de sarcina PPC.")
        st.plotly_chart(monthly_chart(api_client.get_monthly_summary(site_id)), width="stretch")
