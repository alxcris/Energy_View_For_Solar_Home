"""Inbox-ul de notificari al clientului (simulat in prototip).

Reguli din design: putine si doar cand merita (prag minim in lei), rezolvabile
dintr-o apasare, iar "Nu-mi mai propune" chiar e tinut minte. Notificarile se
genereaza din profilul orar real + profilul din chestionar.
"""

import pandas as pd
import streamlit as st

from components.wizard import APPLIANCES
from config import PRICE_BUY_LEI_KWH, PRICE_SELL_LEI_KWH, SOLAR_WINDOW

MIN_SAVING_LEI = 2.0  # sub pragul asta nu deranjam omul


def build_notifications(hourly: pd.DataFrame, profile: dict) -> list[dict]:
    """Construieste notificarile din date, nu dintr-o lista fixa."""
    notifs = []
    solar = f"{SOLAR_WINDOW[0]}:00-{SOLAR_WINDOW[1]}:00"
    peak_hour = int(hourly.loc[hourly["avg_power_kw"].idxmax(), "hour"])
    night = hourly[hourly["hour"].between(2, 5)]["avg_power_kw"].mean()
    diff = PRICE_BUY_LEI_KWH - PRICE_SELL_LEI_KWH

    if "ev" in profile.get("appliances", []):
        away = profile.get("ev_home_noon") == "Rar"
        if away:
            notifs.append({
                "id": "ev_partial",
                "title": "Incarca masina la noapte doar cat iti trebuie",
                "body": "Masina nu e acasa la pranz, deci la noapte incarc-o doar pana la ~60%, "
                        "cat ajunge pentru drumurile de maine. Restul il iei in weekend, din soare.",
                "saving": round(5 * diff, 1),
            })
        else:
            notifs.append({
                "id": "ev_solar",
                "title": f"Muta masina la incarcat intre {solar}",
                "body": "In fereastra asta panourile produc din plin si energia te costa cel mai putin. "
                        "O incarcare de ~10 kWh mutata din noapte la pranz se simte direct in factura.",
                "saving": round(10 * diff, 1),
            })
    for a in ("washer", "dishwasher", "boiler", "dryer"):
        if a in profile.get("appliances", []) and profile.get("usage", {}).get(a) in ("Seara", "Noaptea", None):
            notifs.append({
                "id": f"shift_{a}",
                "title": f"{APPLIANCES[a]}: porneste-o la pranz",
                "body": f"Acum ruleaza de obicei spre seara, cand consumul casei e deja la varf "
                        f"(in jur de ora {peak_hour}:00). Intre {solar} ar merge pe energia panourilor.",
                "saving": round(1.5 * diff, 1),
            })
    if night and night > 0.3:
        notifs.append({
            "id": "baseload",
            "title": "Ceva consuma si cand dormi",
            "body": f"Intre 02:00 si 05:00 casa trage in medie {night:.2f} kW. "
                    "Verifica ce ramane pornit peste noapte (boiler, echipamente in standby).",
            "saving": round(night * 6 * PRICE_BUY_LEI_KWH, 1),
        })

    notifs = [n for n in notifs if n["saving"] >= MIN_SAVING_LEI / 7 or n["id"] == "baseload"]
    dismissed = st.session_state.setdefault("notif_dismissed", set())
    return [n for n in notifs if n["id"] not in dismissed]


def notification_inbox(notifs: list[dict]) -> None:
    accepted = st.session_state.setdefault("notif_accepted", {})
    dismissed = st.session_state.setdefault("notif_dismissed", set())
    pending = [n for n in notifs if n["id"] not in accepted]

    if not pending:
        st.success("Nimic nou. Te anuntam doar cand chiar ai ceva de castigat.")
    for n in pending:
        with st.container(border=True):
            st.markdown(f"**{n['title']}**")
            st.write(n["body"])
            st.caption(f"Economie estimata: ~{n['saving']:.0f} lei/zi in zilele in care o aplici")
            c1, c2, c3 = st.columns(3)
            if c1.button("Accepta", key=f"acc_{n['id']}", type="primary", width="stretch"):
                accepted[n["id"]] = n
                st.rerun()
            if c2.button("Nu azi", key=f"later_{n['id']}", width="stretch"):
                st.toast("Bine, revenim alta data.")
            if c3.button("Nu-mi mai propune", key=f"dis_{n['id']}", width="stretch"):
                dismissed.add(n["id"])
                st.rerun()


def accepted_plan() -> None:
    accepted = st.session_state.get("notif_accepted", {})
    if not accepted:
        return
    st.subheader("Planul tau")
    total = sum(n["saving"] for n in accepted.values())
    st.caption(f"Economie estimata daca le respecti: ~{total * 20:.0f} lei/luna")
    for n in accepted.values():
        st.markdown(f"- {n['title']}")
