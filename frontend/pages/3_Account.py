"""The user's own page: what we know, what we saved, and how to undo it.

Everything on this page comes from the per-user database - the onboarding
answers, the recommendations accepted or dismissed, the activity log - so a
customer can see exactly what the app stores about them and remove it.
"""

import pandas as pd
import streamlit as st

from components.auth import logout, require_user
from components.errors import error_card, status_strip, store_warnings
from components.theme import badge, hero, kpi_row, section, setup_page
from components.wizard import APPLIANCES, reset_wizard
from services import db, store

setup_page("Account")
user = require_user()

hero(user.get("name") or user.get("email"),
     "What this app knows about you, and what it has saved on your behalf.",
     eyebrow="Your account",
     meta=["O&M operator" if user.get("role") == "operator" else "Prosumer",
           user.get("email", ""),
           "Saved to the database" if store.persistent() else "This session only"])

health = db.health()
status_strip([
    {"label": "Database", "state": "ok" if health.get("ok") else "err",
     "note": f"{health.get('users', 0)} accounts" if health.get("ok") else health.get("error", "")},
    {"label": "Your data", "state": "ok" if store.persistent() else "warn",
     "note": "saved for next time" if store.persistent() else "kept only in this tab"},
])
store_warnings()

if not health.get("ok"):
    error_card("The database is not available", health.get("error", ""),
               "Your answers still work in this session, but nothing is being saved.")

profile = store.profile()
decisions = store.decisions()
accepted = store.accepted()

kpi_row([
    {"label": "Questionnaire", "value": "complete" if profile.get("done") else "unfinished",
     "color": "battery" if profile.get("done") else "peak"},
    {"label": "Accepted tips", "value": len(accepted), "color": "export",
     "sub": "they make up your plan"},
    {"label": "Turned down", "value": sum(1 for d in decisions.values()
                                          if d.get("state") == "dismissed"),
     "color": "grid", "sub": "we will not suggest them again"},
    {"label": "Planned saving", "value": f"{sum(float(d.get('saving') or 0) for d in accepted.values()) * 20:.0f}",
     "unit": "lei/month", "color": "price"},
])

left, right = st.columns(2)

with left:
    section("Your answers", "from the onboarding questionnaire")
    if not profile.get("done"):
        st.info("You have not finished the questionnaire yet.")
    rows = [
        ("Equipment", ", ".join(profile.get("equipment") or []) or "-"),
        ("Big consumers", ", ".join(APPLIANCES.get(a, a) for a in profile.get("appliances") or []) or "-"),
        ("Daily schedule", profile.get("schedule") or "-"),
        ("How involved", profile.get("engagement") or "-"),
        ("Smart meter data", "shared" if profile.get("data_meter") else "not shared"),
        ("Connected devices", "shared" if profile.get("data_devices") else "not shared"),
    ]
    st.dataframe(pd.DataFrame(rows, columns=["What we asked", "Your answer"]),
                 hide_index=True, width="stretch")
    if st.button("Redo the questionnaire", icon=":material/restart_alt:"):
        reset_wizard()
        st.switch_page("views/home.py")

with right:
    section("What you decided", "every recommendation you answered")
    if not decisions:
        st.caption("Nothing yet. Accept or turn down a tip on the home page.")
    else:
        tone = {"accepted": "ok", "dismissed": "mute", "snoozed": "warn"}
        for notif_id, d in decisions.items():
            st.markdown(
                f'<div class="ev-item" style="margin:0 0 8px">'
                f'{badge(str(d.get("state", "")).title(), tone.get(d.get("state"), "mute"))}'
                f'&nbsp;{d.get("title") or notif_id}<em>&middot; ~{float(d.get("saving") or 0):.1f} '
                f'lei/run</em></div>', unsafe_allow_html=True)
        if st.button("Clear all my decisions", icon=":material/delete_sweep:"):
            for notif_id in list(decisions):
                store.undo_decision(notif_id)
            store.log("decisions_cleared")
            st.rerun()

section("Activity", "what the app did for you, newest first")
events = store.events(15)
if not events:
    st.caption("Nothing logged yet.")
else:
    nice = {"login": "Signed in", "account_created": "Account created",
            "onboarding_completed": "Finished the questionnaire",
            "onboarding_reset": "Restarted the questionnaire",
            "recommendation_accepted": "Accepted a recommendation",
            "recommendation_dismissed": "Turned down a recommendation",
            "recommendation_snoozed": "Postponed a recommendation",
            "decisions_cleared": "Cleared the saved decisions",
            "alert_acknowledged": "Acknowledged an alert",
            "work_order_created": "Created a work order"}
    table = pd.DataFrame([{
        "When": (pd.Timestamp(e["ts"]).strftime("%d %b, %H:%M") if e.get("ts") else "this session"),
        "What": nice.get(e["kind"], e["kind"].replace("_", " ").capitalize()),
        "Detail": e.get("detail") or "",
    } for e in events])
    st.dataframe(table, hide_index=True, width="stretch")

section("Sign out")
c1, c2 = st.columns([1, 3])
if c1.button("Sign out", type="primary", icon=":material/logout:", width="stretch"):
    logout()
c2.caption("Your answers and your plan stay in the database and are waiting for you next time."
           if store.persistent() else
           "You are looking around without an account, so nothing is kept once you leave.")
