"""Installation monitoring - PPC's operations and maintenance view.

Every installation, every open alert and what each problem costs per day, plus
the string-level detail that says where to send the technician. This is the
answer to "faults found after the damage": the loss is priced while it is still
running.
"""

import pandas as pd
import streamlit as st

from components import strings as array_ui
from components.alerts import alert_list
from components.auth import require_user
from components.charts import inverter_power_chart, pv_vs_expected_chart
from components.errors import error_card, error_log_expander, section as guard
from components.kpi_cards import fleet_kpis
from components.theme import hero, kpi_row, section, setup_page
from config import SEVERITY_ORDER
from services import api_client, ml_source, plant

setup_page("Installation monitoring")
user = require_user()

hero("Maintenance",
     "Every installation and every open problem in one place, priced in lei per day. "
     "This is the operations & maintenance (O&M) view - the team that keeps the panels running.",
     eyebrow="Operations & maintenance (O&M)",
     meta=[f"Signed in as {user.get('name') or user.get('email')}",
           "O&M operator" if user.get("role") == "operator" else "Read-only view"])

use_ml = ml_source.available()

# --- ML pipeline version: alerts with the loss in lei ------------------------
if use_ml:
    sites, alerts, telemetry_age = pd.DataFrame(), pd.DataFrame(), None
    with guard("The fleet"):
        sites = ml_source.get_sites()
        alerts = ml_source.get_alerts()

    if sites.empty:
        error_card("No installations in the dataset",
                   "The ML pipeline produced no sites.csv.",
                   "Run <code>python run_demo.py</code> in <code>ml_pipeline/</code>.")
        st.stop()

    active = alerts[alerts["ongoing"].astype(bool)] if not alerts.empty else pd.DataFrame()

    daily_loss = float(active["lost_lei"].sum()) / max(1, 7) if not active.empty else 0.0
    kpi_row([
        {"label": "Installations", "value": len(sites), "color": "consumption"},
        {"label": "Active alerts", "value": len(active), "color": "solar",
         "sub": f"{int((active['severity'] == 'critical').sum()) if not active.empty else 0} critical"},
        {"label": "Lei at stake", "value": f"{active['lost_lei'].sum():.0f}" if not active.empty else "0",
         "unit": "lei", "sub": "already lost on open faults", "color": "price"},
        {"label": "Bleeding per day", "value": f"{daily_loss:.0f}", "unit": "lei/day",
         "sub": "if nothing is fixed", "color": "peak"},
    ])

    section("What needs a technician", "most expensive first")

    @st.fragment
    def alert_block() -> None:
        with guard("The alert list"):
            alert_list(active if not active.empty else alerts, limit=6, in_fragment=True)

    alert_block()

    with guard("The impact figures"):
        impact = ml_source.get_impact()
        if not impact.empty:
            section("What this monitoring was worth",
                    "our detection time against the weekly check it replaces")
            faster = int(impact["faster_than_today"].astype(str).str.lower().eq("true").sum()) \
                if impact["faster_than_today"].dtype == object \
                else int(impact["faster_than_today"].sum())
            sooner = (impact["detected_after_h_today"] - impact["detected_after_h_ours"]) \
                .clip(lower=0).median()
            kpi_row([
                {"label": "Faults caught earlier", "value": f"{faster} of {len(impact)}",
                 "color": "battery"},
                {"label": "Found sooner by", "value": f"{sooner:.0f}", "unit": "h",
                 "sub": "median, against a weekly check", "color": "forecast"},
                {"label": "Energy not lost", "value": f"{impact['saved_kwh'].sum():.0f}",
                 "unit": "kWh", "color": "export"},
                {"label": "Money not lost", "value": f"{impact['saved_lei'].sum():.0f}",
                 "unit": "lei", "color": "price"},
            ])
            with st.expander("Fault by fault"):
                st.dataframe(
                    impact[["site_id", "type", "detected_after_h_ours",
                            "detected_after_h_today", "lost_kwh_ours", "lost_kwh_today",
                            "saved_lei"]],
                    column_config={
                        "site_id": "Site", "type": "Fault",
                        "detected_after_h_ours": st.column_config.NumberColumn(
                            "We found it after (h)", format="%.1f"),
                        "detected_after_h_today": st.column_config.NumberColumn(
                            "A weekly check would (h)", format="%.0f"),
                        "lost_kwh_ours": st.column_config.NumberColumn("Lost with us (kWh)",
                                                                      format="%.0f"),
                        "lost_kwh_today": st.column_config.NumberColumn("Lost without (kWh)",
                                                                       format="%.0f"),
                        "saved_lei": st.column_config.NumberColumn("Saved (lei)", format="%.0f"),
                    },
                    hide_index=True, width="stretch")

    section("One installation, in detail")
    options = dict(zip(sites["name"], sites["site_id"]))
    name = st.selectbox("Installation", list(options))
    site_id = options[name]
    site = sites[sites["site_id"] == site_id].iloc[0].to_dict()
    site_alerts = alerts[(alerts["site_id"] == site_id) & (alerts["ongoing"].astype(bool))] \
        if not alerts.empty else pd.DataFrame()
    fault_type = site_alerts.iloc[0]["type"] if not site_alerts.empty else None

    with guard("The installation's production"):
        ts = ml_source.get_timeseries(site_id, days=7)
        st.caption("The last 7 days. A dip below the grey line is a fault or missing data.")
        st.plotly_chart(pv_vs_expected_chart(ts), width="stretch", theme=None)

        last = ts.iloc[-1]
        rows = plant.live_strings(site, last["pv_kw"], last.get("expected_kw"), fault_type)
        summary = plant.array_summary(rows)
        section("Strings", f"{summary['working']} of {summary['total']} producing - {summary['text']}")
        array_ui.panel_array(rows)
        st.caption("Per-string figures are derived from the inverter total and the "
                   "weather-expected production, so a technician knows where to start.")

    error_log_expander()
    st.stop()

# --- Backend / mock version --------------------------------------------------
sites = pd.DataFrame()
alerts = pd.DataFrame()
with guard("The fleet"):
    sites = api_client.get_sites()
    alerts = api_client.get_alerts()

if sites.empty:
    error_card("No sites", "The backend returned nothing and there is no demo data.",
               "Start the backend and run <code>python ../frontend/tools/seed_db.py</code>.")
    st.stop()

fleet_kpis(sites, alerts)

section("Active alerts")
if alerts.empty:
    st.success("No active alerts.")
else:
    df = alerts.merge(sites[["site_id", "name"]], on="site_id", how="left")
    df["_ord"] = df["severity"].map(SEVERITY_ORDER).fillna(9)
    df = df.sort_values(["_ord", "estimated_loss_kwh"], ascending=[True, False])
    st.dataframe(
        df[["severity", "name", "message", "estimated_loss_kwh"]],
        column_config={
            "severity": "Severity", "name": "Site", "message": "Problem",
            "estimated_loss_kwh": st.column_config.NumberColumn("Estimated loss (kWh)",
                                                                format="%.1f"),
        },
        hide_index=True, width="stretch")

section("Sites")
view = sites.copy()
view["delta_kw"] = (view["total_current_power_kw"] - view["total_expected_power_kw"]).round(2)
st.dataframe(
    view[["site_id", "name", "status", "sla_availability_pct",
          "total_current_power_kw", "total_expected_power_kw", "delta_kw"]],
    column_config={
        "site_id": "ID", "name": "Name", "status": "Status",
        "sla_availability_pct": st.column_config.NumberColumn("SLA (%)", format="%.1f"),
        "total_current_power_kw": "Now (kW)",
        "total_expected_power_kw": "Expected (kW)",
        "delta_kw": "Difference (kW)",
    },
    hide_index=True, width="stretch")

section("Inverters of one site")
options = dict(zip(sites["name"], sites["site_id"]))
name = st.selectbox("Site", list(options))
inverters = api_client.get_inverters(options[name])
if inverters.empty:
    st.info("This site has no registered inverters.")
else:
    left, right = st.columns([2, 3])
    with left:
        st.dataframe(
            inverters[["name", "brand", "status", "battery_soc_pct", "gsm_signal_dbm"]],
            column_config={
                "name": "Inverter", "brand": "Brand", "status": "Status",
                "battery_soc_pct": st.column_config.NumberColumn("Battery (%)", format="%.0f"),
                "gsm_signal_dbm": "GSM signal (dBm)",
            },
            hide_index=True, width="stretch")
    with right:
        st.plotly_chart(inverter_power_chart(inverters), width="stretch", theme=None)

with st.expander("Context sent to the AI service (ai-context)"):
    st.json(api_client.get_ai_context(options[name]))

error_log_expander()
