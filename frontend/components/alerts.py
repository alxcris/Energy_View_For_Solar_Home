"""Alert cards for the operations and maintenance team.

A table tells you there is a problem; a card tells you which installation,
what it is costing per day, and what to do about it - which is the difference
between "faults found after the damage" and a technician sent today.
"""

from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from components.theme import badge
from config import UI
from services import store

def _brand_badge(brand) -> str:
    """Small chip with the inverter brand (empty when unknown).

    Makes it obvious at a glance that the alert list mixes vendors
    (Huawei, Fronius, SMA) in one view - the whole point of the platform.
    """
    if brand is None or (isinstance(brand, float) and pd.isna(brand)) or str(brand).strip() in ("", "nan"):
        return ""
    return f'<span class="ev-brand">{html.escape(str(brand))}</span>'


SEVERITY = {
    "critical": (UI["danger"], "err", "Critical"),
    "warning": (UI["warn"], "warn", "Warning"),
    "info": (UI["info"], "info", "Info"),
}

TYPE_LABELS = {
    "battery_not_charging": "Battery not charging",
    "gradual_degradation": "Gradual degradation",
    "sudden_underperformance": "Sudden drop in production",
    "inverter_offline": "Inverter offline",
    "comms_loss": "No communication",
    "string_offline": "String offline",
}


def _row_html(row: pd.Series) -> str:
    sev = str(row.get("severity", "info")).lower()
    color, tone, label = SEVERITY.get(sev, SEVERITY["info"])
    kind = TYPE_LABELS.get(str(row.get("type")), str(row.get("type", "")).replace("_", " ").title())
    detected = pd.Timestamp(row["detected_at"]).strftime("%d %b, %H:%M") if row.get("detected_at") is not None else "-"
    state = badge(label, tone) + (badge("Active", "err") if row.get("ongoing") else badge("Closed", "mute"))
    return (
        f'<div class="ev-alert" style="--sev:{color}"><div style="flex:1">'
        f'<div class="ev-alert-h"><span class="ev-alert-t">{html.escape(str(row.get("site_name", "")))}'
        f'</span>{_brand_badge(row.get("brand"))}{state}<span class="ev-sec-c">{html.escape(kind)}</span></div>'
        f'<div class="ev-alert-b">{html.escape(str(row.get("message", "")))}</div>'
        f'<div class="ev-alert-m"><span>Detected <b>{detected}</b></span>'
        f'<span>Lost so far <b>{float(row.get("lost_kwh") or 0):.0f} kWh</b></span>'
        f'<span>That is <b>{float(row.get("lost_lei") or 0):.0f} lei</b></span></div>'
        f'<div class="ev-alert-m" style="margin-top:7px">'
        f'<span>Next step: <b>{html.escape(str(row.get("action", "")))}</b></span></div>'
        f'</div></div>'
    )


def alert_list(df: pd.DataFrame, limit: int = 6, actions: bool = True,
               in_fragment: bool = False) -> None:
    """The alerts worth a technician's time, most expensive first."""
    if df is None or df.empty:
        st.success("No alerts. Every installation is producing what the weather allows.")
        return
    df = df.sort_values("lost_lei", ascending=False).head(limit)
    handled = st.session_state.setdefault("alerts_handled", {})
    gap = '<div style="height:26px"></div>'   # breathing room before the next alert
    for _, row in df.iterrows():
        st.markdown(_row_html(row), unsafe_allow_html=True)
        st.markdown('<div style="height:10px"></div>', unsafe_allow_html=True)  # card -> buttons
        alert_id = str(row.get("alert_id", row.get("site_id", "")))
        done = handled.get(alert_id)
        if actions and not done:
            c1, c2, c3 = st.columns([1, 1, 4])
            if c1.button("Acknowledge", key=f"ack_{alert_id}", width="stretch"):
                handled[alert_id] = "Acknowledged"
                store.log("alert_acknowledged", f"{row.get('site_name')} - {row.get('type')}")
                st.rerun(scope="fragment") if in_fragment else st.rerun()
            if c2.button("Send a technician", key=f"wo_{alert_id}", width="stretch",
                         type="primary"):
                handled[alert_id] = "Work order created"
                store.log("work_order_created", f"{row.get('site_name')} - {row.get('action')}")
                st.toast(f"Work order created for {row.get('site_name')}.")
                st.rerun(scope="fragment") if in_fragment else st.rerun()
        elif actions and done:
            st.caption(f"{done} - logged in this session")
        st.markdown(gap, unsafe_allow_html=True)
