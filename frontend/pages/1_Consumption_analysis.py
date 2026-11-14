"""Consumption analysis for one installation: the 15-minute curve, the hourly
profile and the history. This is the page that answers "why am I getting this
recommendation?" - every tip on the home page can be traced back to a shape in
one of these charts."""

import pandas as pd
import streamlit as st

from components.auth import require_user
from components.charts import (consumption_chart, daily_energy_chart, hourly_profile_chart,
                               monthly_chart, pv_vs_expected_chart)
from components.errors import error_card, error_log_expander, section as guard
from components.kpi_cards import site_kpis
from components.theme import hero, section, setup_page
from config import SOLAR_WINDOW
from services import api_client, ml_source, plant

setup_page("Consumption analysis")
require_user()

use_ml = ml_source.available()

sites = pd.DataFrame()
with guard("The list of installations"):
    sites = ml_source.get_sites() if use_ml else api_client.get_sites()
if sites.empty:
    error_card("No installation found", "Neither the pipeline nor the backend returned a site.",
               "Run <code>python run_demo.py</code> in <code>ml_pipeline/</code>.")
    st.stop()

options = dict(zip(sites["name"], sites["site_id"]))
names = list(options)
saved = st.session_state.get("site_id")
default_idx = next((i for i, n in enumerate(names) if options[n] == saved), 0)

col1, col2 = st.columns([3, 1])
if st.session_state.get("w_site") not in names:
    st.session_state["w_site"] = names[default_idx]
name = col1.selectbox("Installation", names, key="w_site")
days = col2.selectbox("Range", [1, 2, 3, 7],
                      format_func=lambda d: "Last day" if d == 1 else f"Last {d} days")
site_id = options[name]
st.session_state["site_id"] = site_id

telemetry, hourly = pd.DataFrame(), pd.DataFrame()
with guard("The telemetry"):
    if use_ml:
        telemetry = ml_source.get_timeseries(site_id, days=days)
        hourly = ml_source.get_hourly_profile(site_id)
    else:
        telemetry = api_client.get_telemetry(site_id, limit=days * 96)
        hourly = api_client.get_hourly_profile(site_id)

hero(name, "Where the recommendations come from: your consumption by hour, by day "
           "and against the sun.", eyebrow="Consumption analysis")

if telemetry.empty:
    error_card("No readings for this installation", "", "Pick another installation above.")
    st.stop()

site_kpis(telemetry, hourly)

section("Consumption every 15 minutes",
        f"the yellow band is the solar window ({SOLAR_WINDOW[0]}:00-{SOLAR_WINDOW[1]}:00)")
with guard("The consumption chart"):
    st.plotly_chart(consumption_chart(telemetry), width="stretch", theme=None)

if use_ml:
    section("Production: expected from the weather vs. actual",
            "when the actual line drops below the expected one, something is wrong")
    with guard("The production chart"):
        st.plotly_chart(pv_vs_expected_chart(telemetry), width="stretch", theme=None)

left, right = st.columns(2)
with left:
    section("Average hourly profile", "coral = the three peak hours")
    with guard("The hourly profile"):
        peaks = hourly.nlargest(3, "avg_power_kw")["hour"].tolist()
        st.plotly_chart(hourly_profile_chart(hourly, peaks), width="stretch", theme=None)
with right:
    if use_ml:
        section("Energy per day", "the last 14 days")
        with guard("The daily energy chart"):
            st.plotly_chart(daily_energy_chart(ml_source.get_daily_energy(site_id)),
                            width="stretch", theme=None)
    else:
        section("Monthly history", "seasonal consumption from the PPC load curve")
        with guard("The monthly chart"):
            st.plotly_chart(monthly_chart(api_client.get_monthly_summary(site_id)),
                            width="stretch", theme=None)

section("Where a typical day goes", "the always-on base, the habits we recognised, the rest")
with guard("The consumption breakdown"):
    from components.strings import consumption_bars
    consumption_bars(plant.consumption_split(hourly, ml_source.get_customer(site_id) if use_ml else {}))

error_log_expander()
