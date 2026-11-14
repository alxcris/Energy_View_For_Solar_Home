"""One energy view - demo dashboard.

    python run_demo.py            # writes out/*.csv (about 5 s)
    python analyze_real_load.py   # optional: the PPC real-data tab
    streamlit run app.py

Reads only what the pipeline wrote to out/, so it never talks to the customer's equipment.
"""
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

from ml.impact import ASSUMED_BASELINE_DAYS, ASSUMED_CREW_HOURS, detection_impact, summary

OUT = Path("out")
TZ = "Europe/Bucharest"
st.set_page_config(page_title="One energy view", layout="wide")


@st.cache_data
def load():
    need = ["sites.csv", "telemetry.csv", "expected.csv", "alerts.csv"]
    if not all((OUT / f).exists() for f in need):
        return None
    d = {f.split(".")[0]: pd.read_csv(OUT / f) for f in need}
    for k in ("telemetry", "expected"):
        d[k]["timestamp"] = pd.to_datetime(d[k].timestamp, utc=True)
    for c in ("start", "end", "detected_at", "fault_start"):
        if c in d["alerts"]:
            d["alerts"][c] = pd.to_datetime(d["alerts"][c], utc=True)
    d["customer"] = json.loads((OUT / "customer.json").read_text()) if (OUT / "customer.json").exists() else {}
    d["dispatch"] = pd.read_csv(OUT / "dispatch_all.csv") if (OUT / "dispatch_all.csv").exists() else pd.DataFrame()
    d["pvgis"] = pd.read_csv(OUT / "pvgis_check.csv") if (OUT / "pvgis_check.csv").exists() else pd.DataFrame()
    return d


def local(ts):
    return ts.dt.tz_convert(TZ).dt.tz_localize(None)


st.title("One energy view")
st.caption("Production, consumption and storage in one place - for the customer and for PPC's O&M team.")

with st.sidebar:
    st.subheader("Data")
    if st.button("Recompute (run_demo.py)"):
        with st.spinner("Running the pipeline..."):
            subprocess.run([sys.executable, "run_demo.py"], check=False)
        st.cache_data.clear()
    st.caption("Simulated fleet of 8 installations with injected faults, 15-minute data. "
               "The last tab uses the real PPC load curve.")

data = load()
if data is None:
    st.warning("No pipeline output yet. Run `python run_demo.py` or use the button in the sidebar.")
    st.stop()

sites, tel, exp, alerts = data["sites"], data["telemetry"], data["expected"], data["alerts"]
names = dict(zip(sites.site_id, sites["name"]))
label = lambda sid: f"{sid} - {names.get(sid, '')}"

tab_om, tab_cust, tab_imp, tab_real, tab_data = st.tabs(
    ["O&M", "Customer", "Impact", "Real client (PPC data)", "Data & privacy"])

# ------------------------------------------------------------------ O&M
with tab_om:
    active = alerts[alerts.ongoing.astype(bool)]
    c = st.columns(4)
    c[0].metric("Installations", len(sites))
    c[1].metric("Active alerts", len(active))
    c[2].metric("Lei at stake (active)", f"{active.lost_lei.sum():.0f}")
    c[3].metric("Critical", int((alerts.severity == "critical").sum()))

    st.subheader("Alerts, most expensive first")
    show = alerts.sort_values("lost_lei", ascending=False).assign(
        detected=lambda a: local(a.detected_at).dt.strftime("%d %b %H:%M"))
    st.dataframe(show[["site_id", "site_name", "type", "severity", "detected", "ongoing",
                       "lost_kwh", "lost_lei", "message", "action"]],
                 hide_index=True, use_container_width=True)

    sid = st.selectbox("Installation", sites.site_id, format_func=label, key="om_site")
    t0 = tel.timestamp.max() - pd.Timedelta(days=7)
    a = tel[(tel.site_id == sid) & (tel.timestamp >= t0)][["timestamp", "pv_kw"]]
    e = exp[(exp.site_id == sid) & (exp.timestamp >= t0) & (exp.timestamp <= tel.timestamp.max())]
    m = e[["timestamp", "expected_kw"]].merge(a, on="timestamp", how="left")
    m["timestamp"] = local(m.timestamp)
    st.markdown("**Actual vs expected production, last 7 days** (a gap is a fault, a hole is lost data)")
    st.line_chart(m.set_index("timestamp").rename(
        columns={"pv_kw": "actual kW", "expected_kw": "expected from weather kW"}))
    if len(data["pvgis"]):
        st.markdown("**PVGIS monthly check** (actual kWh/day vs the PVGIS average for this month)")
        st.dataframe(data["pvgis"][data["pvgis"].site_id == sid], hide_index=True)

# ------------------------------------------------------------------ Customer
with tab_cust:
    sid = st.selectbox("Your installation", sites.site_id, format_func=label, key="cust_site")
    s = sites[sites.site_id == sid].iloc[0]
    t0 = tel.timestamp.max() - pd.Timedelta(days=3)
    v = tel[(tel.site_id == sid) & (tel.timestamp >= t0)].copy()
    v["timestamp"] = local(v.timestamp)
    last = v.iloc[-1] if len(v) else None
    c = st.columns(4)
    if last is not None:
        c[0].metric("Solar now", f"{last.pv_kw:.1f} kW")
        c[1].metric("Home uses", f"{last.load_kw:.1f} kW")
        c[2].metric("Battery", "none" if pd.isna(last.battery_soc) else f"{last.battery_soc:.0f}%")
        c[3].metric("Grid", f"{'buying' if last.grid_kw > 0 else 'selling'} {abs(last.grid_kw):.1f} kW")
    st.markdown("**Produced, used and stored - last 3 days**")
    st.line_chart(v.set_index("timestamp")[["pv_kw", "load_kw", "battery_kw", "grid_kw"]].rename(
        columns={"pv_kw": "solar", "load_kw": "home", "battery_kw": "battery (+charge)",
                 "grid_kw": "grid (+buy)"}))

    info = data["customer"].get(sid, {})
    left, right = st.columns(2)
    with left:
        st.subheader("What to do differently")
        for n in info.get("nudges", []):
            st.info(n["text"])
        for tip in info.get("tips", []):
            st.write("- " + tip)
        if not info.get("nudges") and not info.get("tips"):
            st.write("Nothing to change tomorrow.")
        b = info.get("benchmark", {})
        if b.get("consent") is False:
            st.caption("Comparison with similar homes is off: this customer did not consent.")
        elif b.get("evening_share") is not None:
            st.caption(f"Evening-peak share: {b['evening_share']:.0%} vs {b['fleet_median']:.0%} "
                       f"for {b['peers']} similar homes that agreed to compare.")
            if b.get("text"):
                st.warning(b["text"])
    with right:
        st.subheader("Battery and injection plan, next 24 h")
        dp = data["dispatch"]
        dp = dp[dp.site_id == sid] if len(dp) else dp
        if s.battery_kwh <= 0 or dp.empty:
            st.write("No battery at this installation.")
        else:
            st.metric("Gain vs always injecting", f"{info.get('dispatch_uplift_lei', 0):.2f} lei/day")
            for line in info.get("dispatch_texts", []):
                st.write("- " + line)
            dp = dp.assign(t=pd.to_datetime(dp.timestamp_local.str[:19]))
            st.line_chart(dp.set_index("t")[["price_lei_kwh", "battery_soc"]].rename(
                columns={"price_lei_kwh": "price lei/kWh", "battery_soc": "battery %"}))
            st.dataframe(dp.groupby("action").size().rename("15-min slots"))

# ------------------------------------------------------------------ Impact
with tab_imp:
    st.subheader("Time to spot a problem, and the energy it saves")
    st.caption("How late O&M finds out today and how long a fix takes come from the O&M "
               "interviews. Until then the defaults are assumptions.")
    c = st.columns(2)
    base = c[0].slider("Today: days until O&M finds out", 0.5, 30.0, ASSUMED_BASELINE_DAYS, 0.5)
    crew = c[1].slider("Hours from detection to fix on site", 1.0, 96.0, ASSUMED_CREW_HOURS, 1.0)
    true_alerts = alerts[alerts.get("matches_injected_fault", True).astype(bool)]
    imp = detection_impact(true_alerts, base, crew)
    for line in summary(imp, base, crew):
        st.markdown("- " + line)
    st.dataframe(imp, hide_index=True, use_container_width=True)
    fp = len(alerts) - len(true_alerts)
    st.caption(f"{fp} false alarm(s) on healthy installations are excluded from the totals.")

# ------------------------------------------------------------------ Real data
with tab_real:
    st.subheader("A real PPC consumer: one year at 15 minutes")
    if not (OUT / "real_heatmap.png").exists():
        st.info("Run `python analyze_real_load.py` to fill this tab.")
    else:
        c = st.columns([1, 1.6])
        c[0].image(str(OUT / "real_heatmap.png"))
        c[1].image(str(OUT / "real_daily_drops.png"))
        c[1].image(str(OUT / "real_forecast.png"))
        if (OUT / "real_drops.csv").exists():
            st.markdown("**Every drop, explained** (or flagged to ask the client)")
            st.dataframe(pd.read_csv(OUT / "real_drops.csv").drop(columns=["period"], errors="ignore"),
                         hide_index=True, use_container_width=True)
        if (OUT / "real_pv_what_if.csv").exists():
            st.markdown("**If this client had rooftop PV**")
            st.dataframe(pd.read_csv(OUT / "real_pv_what_if.csv"), hide_index=True)

# ------------------------------------------------------------------ Data & privacy
with tab_data:
    st.subheader("Works next to what the customer already has")
    st.markdown(
        "- **Maker clouds** (phase 1): read through each maker's API, mapped to one data contract "
        "(`ml/connectors.py`, `VendorCloudConnector`).\n"
        "- **On-site inverters** (phase 2): read-only over Modbus TCP with the public SunSpec "
        "register map - reactive and apparent power, temperature, fault state "
        "(`SunSpecModbus`). Sites with closed networks use a separate GSM modem.\n"
        "- **Distributor files**: the 15-minute load curve (`ExcelLoadCurve`).\n"
        "- Nothing writes to the customer's equipment.")
    st.subheader("Data protection")
    st.markdown(
        "- Energy readings can be personal data under GDPR: they show when people are home.\n"
        "- Stored: 15-minute energy values per installation, under a pseudonymous site ID. "
        "No names, addresses or meter IDs in the analytics.\n"
        "- Comparing a home with others needs its consent; only aggregates (a median of at least "
        "3 consenting peers) are ever shown.\n"
        f"- Consent in this demo: {int(sites.get('consent_benchmark', pd.Series(True)).sum())} of "
        f"{len(sites)} customers agreed.")
