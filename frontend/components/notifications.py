"""The customer's recommendations: a short inbox, not a feed.

Design rules, straight from the challenge brief: only a few, only when there is
something to gain (a minimum in lei), each one solved with a single tap, and
"don't suggest this again" is actually remembered - in the database, per user,
so it holds on the next visit too.

The cards are built from the real hourly profile plus the questionnaire
answers; the ML pipeline adds its own on top (services/ml_source.py).
"""

import html

import pandas as pd
import streamlit as st

from components.wizard import (APPLIANCE_PROFILE, APPLIANCES, SHIFTABLE,
                                appliance_kwh, in_season)
from config import PRICE_BUY_LEI_KWH, PRICE_SELL_LEI_KWH, SOLAR_WINDOW
from services import store

MIN_SAVING_LEI = 2.0  # below this threshold we don't bother the customer
MAX_CARDS = 4         # "only a few": the four best, never a feed

# One line per appliance, so a pool does not get the same sentence as a kettle.
# {solar} is the solar window, {peak} the hour the home is busiest.
BODIES = {
    "pool": "The pool is the biggest thing you can move. Heat it between {solar} and the "
            "same warm water costs you the feed-in price instead of the retail one - and "
            "the cover keeps it warm into the evening.",
    "jacuzzi": "Heat the tub while the sun is up. With the lid on it will still be warm "
               "tonight, and none of it came off your bill.",
    "sauna": "An afternoon session runs almost entirely on your own energy. The same "
             "session at 20:00 runs on the grid.",
    "underfloor": "Let the floor warm up between {solar} and then coast. The screed holds "
                  "the heat for hours, so the expensive evening passes with the heating off.",
    "heatpump": "Pre-heat (or pre-cool) the house between {solar} and let it drift "
                "afterwards. The building keeps the temperature while energy is dearest.",
    "irrigation": "Water the garden at midday instead of in the evening: the pump then "
                  "runs on your panels, and the tank is full for the night.",
    "boiler": "Heat the water between {solar}. It stays hot until the evening, and you "
              "paid for none of it.",
    "snowmelt": "Run the driveway heating cables between {solar} on the days it's needed: "
                "the same clear path costs you the feed-in price instead of peak-hour retail.",
    "greenhouse": "Warm the greenhouse between {solar} and let it coast - the glass holds "
                  "the heat into the evening, so the expensive hours pass with it off.",
    "wine_cellar": "Let the cellar pull its temperature down between {solar}, on your own "
                   "power, and simply hold it through the evening.",
    "aquarium": "Run the tank's heater and pumps hardest between {solar}, gentler in the "
                "evening - the water keeps its warmth for hours.",
    "ev2": "Charge the second car between {solar} as well. Two cars on night-grid power is "
           "the single biggest thing you can move onto your own panels.",
}
DEFAULT_BODY = ("It usually runs in the evening, when your home is already at its peak "
                "(around {peak}:00). Between {solar} it would run on your panels' energy.")


def build_notifications(hourly: pd.DataFrame, profile: dict) -> list[dict]:
    """Builds the notifications from the data, not from a fixed list.

    Seasonal appliances only produce a tip when they are actually in use - we
    don't tell someone to heat the pool at midday in November.
    """
    import datetime
    month = datetime.date.today().month
    notifs = []
    if hourly is None or hourly.empty:
        return notifs
    solar = f"{SOLAR_WINDOW[0]}:00-{SOLAR_WINDOW[1]}:00"
    peak_hour = int(hourly.loc[hourly["avg_power_kw"].idxmax(), "hour"])
    night = hourly[hourly["hour"].between(2, 5)]["avg_power_kw"].mean()
    diff = PRICE_BUY_LEI_KWH - PRICE_SELL_LEI_KWH

    if "ev" in profile.get("appliances", []) and in_season("ev", profile, month):
        away = profile.get("ev_home_noon") == "Rarely"
        if away:
            notifs.append({
                "id": "ev_partial",
                "title": "Charge the car tonight only as much as you need",
                "body": "The car is not home at midday, so tonight charge it only to ~60%, "
                        "enough for tomorrow's trips. Top up the rest at the weekend, from the sun.",
                "saving": round(5 * diff, 1),
            })
        else:
            ev_kwh = appliance_kwh("ev", profile)
            notifs.append({
                "id": "ev_solar",
                "title": f"Charge the car between {solar}",
                "body": "In this window your panels produce the most and energy costs you the "
                        f"least. Moving a ~{ev_kwh:.0f} kWh charge from the night to midday "
                        "shows up straight on your bill.",
                "saving": round(ev_kwh * APPLIANCE_PROFILE["ev"]["shift"] * diff, 1),
            })
    for a in SHIFTABLE:
        if a == "ev" or a not in profile.get("appliances", []):
            continue
        if not in_season(a, profile, month):      # out of season: nothing to suggest
            continue
        if profile.get("usage", {}).get(a) not in ("Evening", "Night", "It varies", None):
            continue
        spec = APPLIANCE_PROFILE[a]
        per_run = appliance_kwh(a, profile) * spec["shift"] * diff
        notifs.append({
            "id": f"shift_{a}",
            "title": f"{APPLIANCES[a]}: run it between {solar}",
            "body": BODIES.get(a, DEFAULT_BODY).format(solar=solar, peak=peak_hour),
            "saving": round(per_run, 1),
        })
    if night and night > 0.3:
        notifs.append({
            "id": "baseload",
            "title": "Something keeps running while you sleep",
            "body": f"Between 02:00 and 05:00 your home draws {night:.2f} kW on average. "
                    "Check what stays on overnight (water heater, devices on standby).",
            "saving": round(night * 6 * PRICE_BUY_LEI_KWH, 1),
        })

    notifs = [n for n in notifs if n["saving"] >= MIN_SAVING_LEI / 7 or n["id"] == "baseload"]
    hidden = store.hidden()
    notifs = [n for n in notifs if n["id"] not in hidden]
    # the money first, and only a handful - a long list is a feed, not a nudge
    notifs.sort(key=lambda n: -n["saving"])
    return notifs[:MAX_CARDS]


def notification_inbox(notifs: list[dict], in_fragment: bool = False) -> None:
    """in_fragment: accepting a tip then reruns only this part, not the whole page."""
    def refresh() -> None:
        st.rerun(scope="fragment") if in_fragment else st.rerun()

    decisions = store.decisions()
    pending = [n for n in notifs if decisions.get(n["id"], {}).get("state") != "accepted"]

    if not pending:
        st.success("Nothing new. We only get in touch when you really have something to gain.")
    for n in pending:
        snoozed = decisions.get(n["id"], {}).get("state") == "snoozed"
        with st.container(border=True):
            st.markdown(
                f'<div class="ev-rec-title">{html.escape(n["title"])}</div>'
                f'<div class="ev-rec-body">{html.escape(n["body"])}</div>'
                f'<span class="ev-pill">~{n["saving"]:.0f} lei saved on each day you do it</span>'
                + ('<span class="ev-badge mute" style="margin-left:8px">Snoozed</span>'
                   if snoozed else ""),
                unsafe_allow_html=True)
            c1, c2, c3 = st.columns(3)
            if c1.button("Accept", key=f"acc_{n['id']}", type="primary", width="stretch",
                         icon=":material/check:"):
                store.set_decision(n["id"], "accepted", n["title"], n["saving"])
                refresh()
            if c2.button("Not today", key=f"later_{n['id']}", width="stretch"):
                store.set_decision(n["id"], "snoozed", n["title"], n["saving"])
                st.toast("Fine - we will bring it up again tomorrow.")
                refresh()
            if c3.button("Don't suggest again", key=f"dis_{n['id']}", width="stretch"):
                store.set_decision(n["id"], "dismissed", n["title"], n["saving"])
                refresh()


def accepted_plan(in_fragment: bool = False) -> None:
    accepted = store.accepted()
    if not accepted:
        return
    st.subheader("Your plan")
    total = sum(float(n.get("saving") or 0) for n in accepted.values())
    items = "".join(f"<li>{html.escape(str(n.get('title') or n.get('notif_id')))}</li>"
                    for n in accepted.values())
    st.markdown(
        f'<div class="ev-plan"><div class="ev-kpi-sub">Estimated savings if you stick to it</div>'
        f'<div class="ev-plan-big">~{total * 20:.0f} lei/month</div><ul>{items}</ul></div>',
        unsafe_allow_html=True)
    st.caption("Saved to your account." if store.persistent()
               else "Kept for this session only - create an account to keep it.")
    with st.popover("Change the plan", width="stretch"):
        for notif_id, item in list(accepted.items()):
            if st.button(f"Remove: {item.get('title') or notif_id}", key=f"undo_{notif_id}",
                         width="stretch"):
                store.undo_decision(notif_id)
                st.rerun(scope="fragment") if in_fragment else st.rerun()
