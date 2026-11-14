"""Chestionarul de intrare (max 5 pasi, totul pe apasari, orice se poate sari).

Raspunsurile stau in st.session_state["profil"]. Dupa ultimul pas se arata
imediat o prima estimare, ca utilizatorul sa vada la ce au folosit intrebarile.
"""

import streamlit as st

from config import PRICE_BUY_LEI_KWH, PRICE_SELL_LEI_KWH

APPLIANCES = {
    "ev": "Masina electrica",
    "heatpump": "Pompa de caldura / AC",
    "boiler": "Boiler electric",
    "washer": "Masina de spalat rufe",
    "dishwasher": "Masina de spalat vase",
    "dryer": "Uscator",
    "oven": "Plita / cuptor electric",
}

# Doar pentru consumatorii care chiar se pot muta in timp are sens intrebarea de interval
SHIFTABLE = ["ev", "boiler", "washer", "dishwasher", "dryer"]

INTERVALS = ["Dimineata", "La pranz", "Seara", "Noaptea", "Variabil"]
SCHEDULE = ["De obicei acasa in timpul zilei", "Plecat(a) in timpul zilei", "Program variabil"]
ENGAGEMENT = [
    "Doar un rezumat lunar",
    "Sfaturi saptamanale",
    "Notificari la momentul potrivit",
    "Automat, cu dispozitive conectate",
]

TOTAL_STEPS = 5


def _profile() -> dict:
    return st.session_state.setdefault("profil", {"step": 1})


def wizard_done() -> bool:
    return st.session_state.get("profil", {}).get("done", False)


def reset_wizard() -> None:
    st.session_state["profil"] = {"step": 1}


def _nav(back: bool = True) -> None:
    p = _profile()
    left, right = st.columns(2)
    if back and p["step"] > 1 and left.button("Inapoi", width="stretch"):
        p["step"] -= 1
        st.rerun()
    label = "Continua" if p["step"] < TOTAL_STEPS else "Gata"
    if right.button(label, type="primary", width="stretch"):
        if p["step"] < TOTAL_STEPS:
            p["step"] += 1
        else:
            p["done"] = True
        st.rerun()


def run_wizard() -> None:
    p = _profile()
    st.progress(p["step"] / TOTAL_STEPS, text=f"Pasul {p['step']} din {TOTAL_STEPS}")

    if p["step"] == 1:
        st.subheader("Ce ai instalat?")
        st.caption("Ca sa stim ce energie produci si ce putem optimiza. "
                   "Datele tehnice le stie deja PPC, tu doar confirmi.")
        p["equipment"] = st.pills("Alege tot ce ai:",
                                  ["Panouri solare", "Baterie", "Masina electrica",
                                   "Statie de incarcare (wallbox)", "Pompa de caldura",
                                   "Boiler electric", "Contor inteligent", "Prize smart"],
                                  selection_mode="multi", default=p.get("equipment"))

    elif p["step"] == 2:
        st.subheader("Care sunt consumatorii mari din casa?")
        st.caption("Ca sa-ti spunem cand e cel mai ieftin sa-i folosesti.")
        labels = list(APPLIANCES.values())
        default = [APPLIANCES[k] for k in p.get("appliances", []) if k in APPLIANCES]
        chosen = st.pills("Alege tot ce se aplica:", labels,
                          selection_mode="multi", default=default or None)
        p["appliances"] = [k for k, v in APPLIANCES.items() if v in (chosen or [])]

    elif p["step"] == 3:
        shiftable = [a for a in p.get("appliances", []) if a in SHIFTABLE]
        st.subheader("Cand le folosesti de obicei?")
        st.caption("Aproximativ e suficient. Poti sari peste orice.")
        if not shiftable:
            st.write("Nu ai ales consumatori care se pot programa. Treci mai departe.")
        usage = p.setdefault("usage", {})
        for a in shiftable:
            usage[a] = st.segmented_control(APPLIANCES[a], INTERVALS, default=usage.get(a), key=f"use_{a}")
        if "ev" in shiftable:
            st.divider()
            p["ev_km"] = st.select_slider("Cam cati km conduci pe zi?",
                                          ["sub 20", "20-50", "50-100", "peste 100", "Nu stiu"],
                                          value=p.get("ev_km", "20-50"))
            p["ev_home_noon"] = st.segmented_control("Masina e acasa la pranz?",
                                                     ["De obicei da", "Doar in weekend", "Rar"],
                                                     default=p.get("ev_home_noon"))

    elif p["step"] == 4:
        st.subheader("Cum arata o zi obisnuita pentru tine?")
        st.caption("Ca sa nu-ti propunem lucruri cand nu esti acasa.")
        p["schedule"] = st.segmented_control("Programul tau:", SCHEDULE, default=p.get("schedule"))

    elif p["step"] == 5:
        st.subheader("Cat de implicat(a) vrei sa fii?")
        st.caption("Poti schimba oricand, din setari.")
        p["engagement"] = st.radio("Alege nivelul:", ENGAGEMENT,
                                   index=ENGAGEMENT.index(p["engagement"]) if p.get("engagement") in ENGAGEMENT else 2)
        st.divider()
        st.caption("Separat de nivelul de implicare: la ce date ne dai acces. "
                   "Aplicatia merge si fara ele, doar ca estimarile sunt mai putin precise.")
        p["data_meter"] = st.toggle("Curba de consum de la contorul inteligent",
                                    value=p.get("data_meter", True))
        p["data_devices"] = st.toggle("Dispozitive conectate (prize smart, incarcator)",
                                      value=p.get("data_devices", False))

    _nav()


def first_estimate() -> None:
    """Primul rezultat, aratat imediat dupa chestionar."""
    p = st.session_state.get("profil", {})
    saving = 0.0
    parts = []
    if "ev" in p.get("appliances", []):
        # ~10 kWh/zi incarcare mutata din noapte in fereastra solara, 20 de zile pe luna
        ev_saving = 10 * 20 * (PRICE_BUY_LEI_KWH - PRICE_SELL_LEI_KWH)
        saving += ev_saving
        parts.append(f"incarcarea masinii in orele cu soare (~{ev_saving:.0f} lei/luna)")
    for a in ("boiler", "washer", "dishwasher", "dryer"):
        if a in p.get("appliances", []):
            saving += 15
            parts.append(APPLIANCES[a].lower() + " mutat(a) la pranz (~15 lei/luna)")
    if not parts:
        st.info("Profil salvat. Pe masura ce strangem date despre consum, apar si recomandarile.")
        return
    st.success(f"Pe baza profilului tau, poti economisi aproximativ **{saving:.0f} lei/luna**: "
               + "; ".join(parts) + ". Estimare orientativa, se rafineaza din datele reale.")
