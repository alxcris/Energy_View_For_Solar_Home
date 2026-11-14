"""The customer's screen: one live view of the whole installation.

Top to bottom: who is signed in and how healthy the data is, the onboarding
questionnaire (once), then the live energy flow - panels, inverter, home,
battery, grid - with the clock that can replay a whole day. Under it, the
array string by string, where the consumption goes, the three-day picture and
the recommendations the customer can accept with one tap.

Routed from app.py (top navigation).
"""

import pandas as pd
import streamlit as st

from components import strings as array_ui
from components.auth import require_user
from components.charts import battery_plan_chart, one_view_chart
from components.errors import (empty_state, error_card, error_log_expander,
                               section as guard, store_warnings)
from components.flow_live import live_panel
from components.kpi_cards import site_kpis
from components.notifications import accepted_plan, build_notifications, notification_inbox
from components.theme import hero, section, setup_page
from components.wizard import first_estimate, reset_wizard, run_wizard, wizard_done
from config import PRICE_BUY_LEI_KWH, PRICE_SELL_LEI_KWH
from components import geo
from components.story import why_one_view
from services import api_client, ml_source, plant, store

setup_page("Home")
user = require_user()
use_ml = ml_source.available()

# --- where the numbers come from, and whether we are saving anything ---------
sites = pd.DataFrame()
with guard("The list of installations"):
    sites = ml_source.get_sites() if use_ml else api_client.get_sites()

if sites.empty:
    error_card(
        "No installation found",
        "Neither the ML pipeline results nor the backend returned any site.",
        "Run <code>python run_demo.py</code> in <code>ml_pipeline/</code>, or start the "
        "backend and seed it with <code>python ../frontend/tools/seed_db.py</code>.")
    st.stop()

# --- onboarding questionnaire, until it is completed --------------------------
if not wizard_done():
    hero("Welcome!",
         "A few short questions so the tips fit your home. You can skip any of them.",
         meta=[f"Signed in as {user.get('name') or user.get('email')}"])
    run_wizard()
    st.stop()

# --- which installation ------------------------------------------------------
options = dict(zip(sites["name"], sites["site_id"]))
saved_site = st.session_state.get("site_id") or user.get("site_id")
names = list(options)
default_idx = next((i for i, n in enumerate(names) if options[n] == saved_site), 0)

if st.session_state.get("w_site") not in names:          # keyed, never a moving default
    st.session_state["w_site"] = names[default_idx]
c_site, c_loc, c_redo = st.columns([4, 1.5, 1.4], vertical_alignment="bottom")
name = c_site.selectbox("My installation", names, key="w_site")
def _pick(installation: str) -> None:
    st.session_state["w_site"] = installation
with c_loc:
    geo.use_my_location(sites, _pick)
if c_redo.button("Redo setup", icon=":material/restart_alt:", width="stretch"):
    reset_wizard()
    st.rerun()
name = st.session_state.get("w_site", name)
site_id = options.get(name, options[names[0]])
st.session_state["site_id"] = site_id

site = sites[sites["site_id"] == site_id].iloc[0].to_dict()

# --- data for this installation ----------------------------------------------
ts = pd.DataFrame()
alerts = pd.DataFrame()
if use_ml:
    with guard("The telemetry"):
        ts = ml_source.get_timeseries(site_id, days=3)
    with guard("The alerts"):
        alerts = ml_source.get_alerts()
else:
    with guard("The telemetry"):
        ts = api_client.get_telemetry(site_id, limit=288)

site_alerts = pd.DataFrame()
if not alerts.empty:
    site_alerts = alerts[(alerts["site_id"] == site_id) & (alerts["ongoing"].astype(bool))]
fault_type = site_alerts.iloc[0]["type"] if not site_alerts.empty else None
fault_note = site_alerts.iloc[0]["message"] if not site_alerts.empty else ""

store_warnings()

battery_kwh = float(site.get("battery_kwh") or 0)
hero(name,
     "Everything you produce, use and store in one place, plus what you can do today to pay less.",
     eyebrow="Your installation",
     meta=[f"{float(site.get('kwp') or 0):.1f} kWp of panels",
           f"{battery_kwh:.0f} kWh battery" if battery_kwh else "no battery",
           f"{len(site_alerts)} open alert" + ("s" if len(site_alerts) != 1 else "")])
first_estimate()
profile = store.profile()

# --- the live view ------------------------------------------------------------
# Drawn once and then driven in the browser (components/flow_live.py): the
# scrubber, the diagram, the cards and the strings all update on the spot,
# without a rerun, so dragging the day is instant.
if use_ml and not ts.empty:
    section("Right now", "where your energy is going this very moment")
    with guard("The live view"):
        has_ev = "ev" in profile.get("appliances", []) or "ev2" in profile.get("appliances", [])
        live_panel(ts, site, plant.string_layout(site, fault_type),
                   fault_note=str(fault_note)[:90] if fault_note else "", has_ev=has_ev)
else:
    empty_state(
        "The live energy flow needs the ML pipeline",
        "It brings production, battery and grid together. Run <code>python run_demo.py</code> "
        "in <code>ml_pipeline/</code> and reload this page.")

hourly = pd.DataFrame()
with guard("The hourly profile"):
    hourly = ml_source.get_hourly_profile(site_id) if use_ml else api_client.get_hourly_profile(site_id)

section("Where your consumption goes")
with guard("The consumption breakdown"):
    customer = ml_source.get_customer(site_id) if use_ml else {}
    array_ui.consumption_bars(plant.consumption_split(hourly, customer))

# --- the three-day picture ----------------------------------------------------
if use_ml and not ts.empty:
    section("Produced, used and stored", "the last three days")
    with guard("The energy chart"):
        st.plotly_chart(one_view_chart(ts), width="stretch", theme=None)

# --- recommendations ----------------------------------------------------------
# In a fragment: accepting or dismissing a tip reruns only this block, so the
# flow diagram and the charts above are not rebuilt on every tap.
@st.fragment
def recommendations() -> None:
    # One vertical flow, each block full width: cards sit side by side inside
    # their own responsive grids, so there is never a tall column next to an
    # empty one.
    left, right = st.columns(2)
    with left:
        section("Recommendations for you", "only a few, and only when they are worth it")
        with guard("The recommendations"):
            if use_ml:
                cards = ml_source.nudges_as_notifications(site_id)
                ml_ids = {c["id"] for c in cards}
                cards += [c for c in build_notifications(hourly, profile)
                          if c["id"] not in ml_ids]
                cards = [c for c in cards if c["id"] not in store.hidden()]
                cards.sort(key=lambda c: -float(c.get("saving") or 0))
                notification_inbox(cards[:5], in_fragment=True)
                info = ml_source.get_customer(site_id)
                bench = info.get("benchmark", {})
                if bench.get("flag") and bench.get("text"):
                    st.warning(bench["text"])
                if info.get("tips"):
                    with st.expander("Good time windows in the next few days"):
                        for tip in info["tips"]:
                            st.markdown(f"- {tip}")
            else:
                notification_inbox(build_notifications(hourly, profile), in_fragment=True)
                ai_recs = api_client.get_ai_recommendations(site_id)
                if ai_recs:
                    with st.expander("Recommendations from the AI service"):
                        for r in ai_recs:
                            st.markdown(f"- {r}")
    with right:
        accepted_plan(in_fragment=True)
        if not use_ml and not ts.empty:
            with guard("Site KPIs"):
                site_kpis(ts, hourly)

    # Appliance schedule: full width, cards side by side.
    with guard("Your appliance plan"):
        devices = ml_source.get_devices(site_id) if use_ml else []
        if devices:
            section("Your appliances, scheduled", "the next good window for each one")
            array_ui.device_plan(devices)

    why_one_view()

    # Battery plan: text beside the wide chart, both full width.
    if use_ml:
        with guard("Your battery plan"):
            info = ml_source.get_customer(site_id)
            plan = ml_source.get_dispatch(site_id)
            if info.get("dispatch_texts") or not plan.empty:
                section("Your battery, tomorrow",
                        f"~{info.get('dispatch_uplift_lei', 0):.1f} lei/day better than "
                        f"always exporting")
                tcol, ccol = st.columns([2, 3])
                with tcol:
                    for line in info.get("dispatch_texts", []):
                        st.markdown(f"- {line}")
                    ics = ml_source.schedule_ics(site_id)
                    if ics:
                        st.download_button("Add the good hours to my calendar", ics,
                                           file_name=f"one-energy-view-{site_id}.ics",
                                           mime="text/calendar", width="stretch",
                                           icon=":material/calendar_add_on:",
                                           on_click=lambda: store.log("calendar_downloaded", site_id))
                with ccol:
                    if not plan.empty:
                        st.plotly_chart(battery_plan_chart(plan), width="stretch", theme=None)
                        st.caption("Green: charging from the sun. Violet: the battery running "
                                   "the house. Amber: selling. The dotted line is the price.")

    section("Want to see why?")
    try:
        st.page_link("pages/1_Consumption_analysis.py",
                     label="Your consumption, by hour and by day",
                     icon=":material/monitoring:")
    except Exception:  # the page was renamed, or this file is running on its own
        st.caption("Open **Consumption** in the top navigation.")


recommendations()

error_log_expander()
