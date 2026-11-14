"""Pagina principala: ecranul clientului (prosumatorului).

Prima data ruleaza chestionarul de intrare; dupa aceea arata starea de acum,
recomandarile si planul acceptat. Daca exista rezultatele pipeline-ului ML
(ml_pipeline/out/), ecranul foloseste imaginea completa: solar + casa +
baterie + retea si recomandarile personalizate. Altfel cade pe backend / mock.

Rulare: streamlit run app.py
"""

import streamlit as st

from components.charts import one_view_chart
from components.kpi_cards import site_kpis
from components.notifications import accepted_plan, build_notifications, notification_inbox
from components.wizard import first_estimate, reset_wizard, run_wizard, wizard_done
from services import api_client, ml_source

st.set_page_config(page_title="One Energy View", layout="wide")

api_client.api_status_banner()

# --- Chestionarul de intrare, pana e completat -------------------------------
if not wizard_done():
    st.title("Bine ai venit")
    st.caption("Cateva intrebari scurte, ca sfaturile sa se potriveasca cu casa ta. "
               "Poti sari peste oricare.")
    run_wizard()
    st.stop()

use_ml = ml_source.available()

# --- Alegerea instalatiei ----------------------------------------------------
sites = ml_source.get_sites() if use_ml else api_client.get_sites()
if sites.empty:
    st.error("Nu exista site-uri. Porneste backend-ul, ruleaza seed-ul sau "
             "genereaza datele ML cu `python run_demo.py`.")
    st.stop()

with st.sidebar:
    options = dict(zip(sites["name"], sites["site_id"]))
    name = st.selectbox("Instalatia mea", list(options))
    site_id = options[name]
    if st.button("Reia chestionarul"):
        reset_wizard()
        st.rerun()

st.title(f"Buna! Uite cum sta {name}")
first_estimate()
profile = st.session_state.get("profil", {})

if use_ml:
    # --- Varianta cu pipeline-ul ML: imaginea completa a energiei ------------
    ts = ml_source.get_timeseries(site_id, days=3)
    last = ts.iloc[-1]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Solar acum", f"{last['pv_kw']:.1f} kW")
    c2.metric("Casa consuma", f"{last['load_kw']:.1f} kW")
    c3.metric("Baterie", "fara" if last.isna()["battery_soc"] else f"{last['battery_soc']:.0f}%")
    c4.metric("Retea", f"{'cumperi' if last['grid_kw'] > 0 else 'vinzi'} {abs(last['grid_kw']):.1f} kW")

    st.subheader("Produs, consumat si stocat - ultimele 3 zile")
    st.plotly_chart(one_view_chart(ts), width="stretch")

left, right = st.columns([3, 2])

with left:
    st.subheader("Recomandari pentru tine")
    st.caption("Putine si doar cand merita. Fiecare se rezolva dintr-o apasare.")
    if use_ml:
        hourly = ml_source.get_hourly_profile(site_id)
        cards = ml_source.nudges_as_notifications(site_id)
        # regulile locale completeaza ce nu acopera ML-ul (din chestionar)
        ml_ids = {c["id"] for c in cards}
        cards += [c for c in build_notifications(hourly, profile) if c["id"] not in ml_ids]
        notification_inbox(cards)

        info = ml_source.get_customer(site_id)
        bench = info.get("benchmark", {})
        if bench.get("flag") and bench.get("text"):
            st.warning(bench["text"])
        if info.get("tips"):
            with st.expander("Ferestre bune in zilele urmatoare"):
                for tip in info["tips"]:
                    st.markdown(f"- {tip}")
    else:
        hourly = api_client.get_hourly_profile(site_id)
        notification_inbox(build_notifications(hourly, profile))
        ai_recs = api_client.get_ai_recommendations(site_id)
        if ai_recs:
            with st.expander("Recomandarile serviciului AI"):
                for r in ai_recs:
                    st.markdown(f"- {r}")

with right:
    accepted_plan()
    if use_ml:
        info = ml_source.get_customer(site_id)
        if info.get("dispatch_texts"):
            st.subheader("Bateria, pe maine")
            st.caption(f"Castig fata de 'injecteaza mereu': "
                       f"~{info.get('dispatch_uplift_lei', 0):.1f} lei/zi")
            for line in info["dispatch_texts"]:
                st.markdown(f"- {line}")
    else:
        telemetry = api_client.get_telemetry(site_id, limit=96)
        site_kpis(telemetry, api_client.get_hourly_profile(site_id))
    st.subheader("Vrei sa vezi de ce?")
    st.page_link("pages/1_Analiza_consum.py", label="Analiza consumului tau, pe ore si pe zile")
