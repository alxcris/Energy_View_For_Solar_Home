"""Onboarding questionnaire (max 5 steps, everything is a tap, anything can be skipped).

The answers belong to the signed-in user: services/store.py keeps them in the
database, so they are still there on the next visit and on another device.
Right after the last step a first estimate is shown, so the user sees what the
questions were for.
"""

import streamlit as st

from config import PRICE_BUY_LEI_KWH, PRICE_SELL_LEI_KWH
from services import store

APPLIANCES = {
    "ev": "Electric car",
    "pool": "Heated pool",
    "jacuzzi": "Hot tub / jacuzzi",
    "sauna": "Sauna",
    "heatpump": "Heat pump / AC",
    "underfloor": "Electric underfloor heating",
    "boiler": "Electric water heater",
    "washer": "Washing machine",
    "dishwasher": "Dishwasher",
    "dryer": "Tumble dryer",
    "oven": "Electric hob / oven",
    "irrigation": "Garden irrigation pump",
    "server": "Home server / NAS",
    # the high-end list - big, fun, and great for showing the savings off
    "snowmelt": "Heated driveway (snow melt)",
    "greenhouse": "Heated greenhouse",
    "wine_cellar": "Wine cellar / cooler",
    "aquarium": "Large aquarium / koi pond",
    "ev2": "Second electric car",
    "cinema": "Home cinema room",
    "patio": "Terrace / patio heaters",
    "elevator": "Home lift",
}

# What each one typically costs in energy, and how much of that can realistically
# be moved into the solar window. Rules of thumb for a Romanian household, used
# by the first estimate and by the recommendations, so both tell the same story.
#   kwh   - a typical run (a day, for the always-on ones)
#   shift - the share of it that can move to midday
#   runs  - how many times a month it typically happens
APPLIANCE_PROFILE = {
    "ev":         {"kwh": 10.0, "shift": 0.90, "runs": 20},
    "pool":       {"kwh": 12.0, "shift": 0.85, "runs": 30},
    "jacuzzi":    {"kwh": 6.0,  "shift": 0.70, "runs": 20},
    "sauna":      {"kwh": 5.0,  "shift": 0.60, "runs": 8},
    "heatpump":   {"kwh": 9.0,  "shift": 0.35, "runs": 30},
    "underfloor": {"kwh": 8.0,  "shift": 0.50, "runs": 30},
    "boiler":     {"kwh": 4.0,  "shift": 0.80, "runs": 30},
    "washer":     {"kwh": 1.1,  "shift": 1.00, "runs": 12},
    "dishwasher": {"kwh": 1.3,  "shift": 1.00, "runs": 20},
    "dryer":      {"kwh": 2.5,  "shift": 1.00, "runs": 10},
    "oven":       {"kwh": 1.5,  "shift": 0.20, "runs": 15},
    "irrigation": {"kwh": 1.0,  "shift": 1.00, "runs": 20},
    "server":     {"kwh": 2.4,  "shift": 0.00, "runs": 30},
    "snowmelt":   {"kwh": 25.0, "shift": 0.30, "runs": 8},
    "greenhouse": {"kwh": 7.0,  "shift": 0.50, "runs": 30},
    "wine_cellar":{"kwh": 2.0,  "shift": 0.55, "runs": 30},
    "aquarium":   {"kwh": 3.0,  "shift": 0.40, "runs": 30},
    "ev2":        {"kwh": 10.0, "shift": 0.90, "runs": 18},
    "cinema":     {"kwh": 2.5,  "shift": 0.10, "runs": 14},
    "patio":      {"kwh": 4.0,  "shift": 0.15, "runs": 12},
    "elevator":   {"kwh": 1.5,  "shift": 0.15, "runs": 30},
}

# Which months each load is actually used. Heating a pool makes sense in summer,
# not in a Romanian November; underfloor heating is the opposite; irrigation is a
# warm-season thing. Everything else runs all year. The estimate and the tips use
# this so they never promise summer savings in winter.
MONTHS_ALL = set(range(1, 13))
SUMMER = {5, 6, 7, 8, 9}          # May - September
HIGH_SUMMER = {6, 7, 8}           # June - August
WARM = {4, 5, 6, 7, 8, 9}         # April - September (garden)
WINTER = {10, 11, 12, 1, 2, 3}    # October - March

MONTH_NAMES = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
               7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"}


def active_months(key: str, profile: dict) -> set[int]:
    """The months this appliance is actually used by this household."""
    if key == "pool":
        ans = profile.get("pool_season")
        if ans == "May to September":
            return SUMMER
        if ans == "Only in high summer":
            return HIGH_SUMMER
        return MONTHS_ALL
    if key == "irrigation":
        return WARM
    if key in ("underfloor", "snowmelt", "greenhouse"):
        return WINTER
    if key == "patio":
        return {3, 4, 10, 11}   # spring and autumn evenings
    return MONTHS_ALL


def season_label(key: str, profile: dict) -> str:
    """A short "when" tag for the estimate, empty for year-round appliances."""
    months = active_months(key, profile)
    if months == MONTHS_ALL:
        return ""
    if key == "pool":
        return "high summer only" if months == HIGH_SUMMER else "summer only"
    if key == "irrigation":
        return "warm months"
    if key in ("underfloor", "snowmelt", "greenhouse"):
        return "winter only"
    if key == "patio":
        return "spring and autumn"
    return ""


def in_season(key: str, profile: dict, month: int) -> bool:
    return month in active_months(key, profile)


# The time-of-use question only makes sense for loads that can actually be moved
SHIFTABLE = [k for k, v in APPLIANCE_PROFILE.items() if v["shift"] >= 0.3]

POOL_HOURS = ["2 h", "4 h", "6 h", "8 h or more"]
POOL_SEASON = ["All year", "May to September", "Only in high summer"]
EV_KM = ["under 20", "20-50", "50-100", "over 100", "Not sure"]
EV_NOON = ["Usually yes", "Only at weekends", "Rarely"]
# Infrastructure (not a "consumer" on its own; shown only in step 1).
INFRASTRUCTURE = ["Solar panels", "Battery", "Charging station (wallbox)",
                  "Smart meter", "Smart plugs"]

# Household items shown on step 2 even when nothing was ticked in step 1,
# because most homes have them.
STANDARD_HOUSEHOLD = ["washer", "dishwasher", "dryer", "oven"]

# How many of each big consumer the home has (ev, washer, dishwasher, dryer,
# heat pump / AC, electric water heater). Count defaults to 1.
COUNTABLE = {"ev", "washer", "dishwasher", "dryer", "heatpump", "boiler"}

# Appliances offered in step 2's pills, in a sensible order. Drops "ev2" since
# the "Second electric car" use case is now a count on "ev".
_APPLIANCE_ORDER = [k for k in APPLIANCES if k != "ev2"]

# Step 1's list = infrastructure + the same appliance labels used in step 2.
# One source of truth, so step 1 and step 2 cannot disagree on a label.
EQUIPMENT = INFRASTRUCTURE + [APPLIANCES[k] for k in _APPLIANCE_ORDER]

# Reverse lookup: appliance label (as shown in step 1 and step 2) -> internal key.
_LABEL_TO_KEY = {v: k for k, v in APPLIANCES.items()}


def appliance_kwh(key: str, profile: dict) -> float:
    """A run's energy, adjusted by the follow-up answers the user gave."""
    base = APPLIANCE_PROFILE.get(key, {}).get("kwh", 0.0)
    if key == "pool":
        hours = {"2 h": 2, "4 h": 4, "6 h": 6, "8 h or more": 9}.get(profile.get("pool_hours"), 8)
        base = hours * 1.5  # a pool heat pump draws roughly 1.5 kW
    if key == "ev":
        base = {"under 20": 4.0, "20-50": 8.0, "50-100": 15.0,
                "over 100": 22.0}.get(profile.get("ev_km"), base)
    return base


def appliance_count(key: str, profile: dict) -> int:
    """How many of this appliance the home has. Default 1."""
    try:
        return max(1, int(profile.get("appliance_counts", {}).get(key, 1)))
    except (TypeError, ValueError):
        return 1


def monthly_saving(key: str, profile: dict, price_gap: float) -> float:
    """Lei saved in a month the appliance is in use, running it on your own energy.

    Two electric cars or two washing machines save twice as much, so the stored
    count multiplies the headline figure here.
    """
    spec = APPLIANCE_PROFILE.get(key)
    if not spec or spec["shift"] <= 0:
        return 0.0
    cnt = appliance_count(key, profile)
    return appliance_kwh(key, profile) * spec["shift"] * spec["runs"] * price_gap * cnt


def annual_saving(key: str, profile: dict, price_gap: float) -> float:
    """Over a whole year, counting only the months the appliance is actually used."""
    return monthly_saving(key, profile, price_gap) * len(active_months(key, profile))

INTERVALS = ["Morning", "Midday", "Evening", "Night", "It varies"]
SCHEDULE = ["Usually home during the day", "Away during the day", "Irregular schedule"]
ENGAGEMENT = [
    "Just a monthly summary",
    "Weekly tips",
    "Notifications at the right moment",
    "Automatic, with connected devices",
]

TOTAL_STEPS = 5


def _seed(key: str, value) -> None:
    """Puts a widget's starting value in session state, before the widget exists.

    Every widget here is keyed and never gets a `default=` on later runs: a
    default that changes between runs gives the widget a new identity and
    Streamlit then throws away what the user just picked, which is why a pill
    used to need two clicks to stay selected. Within a step the widget keeps its
    own state; the seeding only happens when the step is opened (_enter_step),
    because Streamlit drops the state of widgets that are not on screen.
    """
    if key not in st.session_state and value is not None:
        st.session_state[key] = value


def _enter_step(step: int) -> None:
    """Coming back to a step re-seeds its widgets from the saved answers."""
    if st.session_state.get("_wizard_step_shown") == step:
        return
    for key in [k for k in st.session_state if str(k).startswith("w_")]:
        del st.session_state[key]
    st.session_state["_wizard_step_shown"] = step


def _profile() -> dict:
    p = store.profile()
    p.setdefault("step", 1)
    return p


def wizard_done() -> bool:
    return store.profile_done()


def reset_wizard() -> None:
    for key in [k for k in st.session_state if str(k).startswith("w_")]:
        del st.session_state[key]
    st.session_state.pop("_wizard_step_shown", None)
    store.reset_profile()
    store.log("onboarding_reset")


def _nav(back: bool = True) -> None:
    p = _profile()
    left, right = st.columns(2)
    if back and p["step"] > 1 and left.button("Back", width="stretch"):
        p["step"] -= 1
        store.save_profile(p)
        st.rerun()
    label = "Continue" if p["step"] < TOTAL_STEPS else "Done"
    if right.button(label, type="primary", width="stretch"):
        if p["step"] < TOTAL_STEPS:
            p["step"] += 1
        else:
            p["done"] = True
            store.log("onboarding_completed", f"{len(p.get('appliances', []))} appliances")
        store.save_profile(p)  # every step is saved, so a reload loses nothing
        st.rerun()


def run_wizard() -> None:
    p = _profile()
    _enter_step(p["step"])
    st.progress(p["step"] / TOTAL_STEPS, text=f"Step {p['step']} of {TOTAL_STEPS}")
    if not store.persistent():
        st.caption("You are looking around without an account, so these answers are kept "
                   "only until you close the tab.")

    if p["step"] == 1:
        st.subheader("What do you have installed?")
        st.caption("So we know what energy you produce and what we can optimise. "
                   "PPC already has the technical details, you just confirm.")
        _seed("w_equipment", p.get("equipment") or [])
        p["equipment"] = st.pills("Pick everything you have:", EQUIPMENT,
                                  selection_mode="multi", key="w_equipment")

    elif p["step"] == 2:
        st.subheader("What are the big consumers in your home?")
        st.caption("Only the ones you ticked on the previous step, plus the household "
                   "basics everyone has. If several of the same, pick a number.")

        # Only offer the appliances the user said they have on step 1, plus the
        # household basics - no mismatch between the two pages, and no "pool"
        # offered here if nothing was ticked there.
        have_keys = [_LABEL_TO_KEY[label] for label in p.get("equipment") or []
                     if label in _LABEL_TO_KEY]
        offered_keys = list(dict.fromkeys(have_keys + STANDARD_HOUSEHOLD))
        if not offered_keys:
            st.info("Pick what you have on the previous step first, then come back.")
            _nav()
            return
        offered_labels = [APPLIANCES[k] for k in offered_keys]

        _seed("w_appliances", [APPLIANCES[k] for k in p.get("appliances", [])
                               if k in APPLIANCES and APPLIANCES[k] in offered_labels])
        chosen = st.pills("Pick everything that applies:", offered_labels,
                          selection_mode="multi", key="w_appliances") or []
        p["appliances"] = [k for k, v in APPLIANCES.items() if v in chosen]

        # One stepper per countable appliance (cars, washers, dishwashers, etc.),
        # so a home with two cars or two washing machines is modelled right.
        counts = p.setdefault("appliance_counts", {})
        countable_here = [k for k in p["appliances"] if k in COUNTABLE]
        if countable_here:
            st.caption("How many of each?")
            cols = st.columns(min(len(countable_here), 3))
            for i, k in enumerate(countable_here):
                _seed(f"w_cnt_{k}", int(counts.get(k, 1)))
                counts[k] = int(cols[i % len(cols)].number_input(
                    APPLIANCES[k], min_value=1, max_value=10, step=1,
                    key=f"w_cnt_{k}"))
        # Drop counts for appliances no longer selected.
        for k in list(counts):
            if k not in p["appliances"]:
                counts.pop(k, None)

    elif p["step"] == 3:
        shiftable = [a for a in p.get("appliances", []) if a in SHIFTABLE]
        st.subheader("When do you usually use them?")
        st.caption("A rough answer is enough. You can skip anything. Seasonal things are "
                   "counted only in their season - a heated pool in summer, underfloor "
                   "heating in winter - so we never suggest one out of season.")
        if not shiftable:
            st.write("You did not pick any appliances that can be scheduled. Just continue.")
        usage = p.setdefault("usage", {})
        for a in shiftable:
            _seed(f"w_use_{a}", usage.get(a))
            usage[a] = st.segmented_control(APPLIANCES[a], INTERVALS, key=f"w_use_{a}")
        if "pool" in shiftable:
            st.divider()
            st.caption("The pool is usually the largest load in the house, so it is worth "
                       "two more taps.")
            _seed("w_pool_hours", p.get("pool_hours", "6 h"))
            p["pool_hours"] = st.segmented_control(
                "How long does the pool heating or pump run on a normal day?",
                POOL_HOURS, key="w_pool_hours")
            _seed("w_pool_season", p.get("pool_season", "May to September"))
            p["pool_season"] = st.segmented_control(
                "When do you keep it warm?", POOL_SEASON, key="w_pool_season")
        if "ev" in shiftable:
            st.divider()
            _seed("w_ev_km", p.get("ev_km", "20-50"))
            p["ev_km"] = st.select_slider("Roughly how many km do you drive a day?",
                                          EV_KM, key="w_ev_km")
            _seed("w_ev_noon", p.get("ev_home_noon"))
            p["ev_home_noon"] = st.segmented_control("Is the car at home around midday?",
                                                     EV_NOON, key="w_ev_noon")

    elif p["step"] == 4:
        st.subheader("What does a typical day look like for you?")
        st.caption("So we don't suggest things for when you are not home.")
        _seed("w_schedule", p.get("schedule"))
        p["schedule"] = st.segmented_control("Your schedule:", SCHEDULE, key="w_schedule")

    elif p["step"] == 5:
        st.subheader("How involved do you want to be?")
        st.caption("You can change this any time in the settings.")
        _seed("w_engagement", p.get("engagement") if p.get("engagement") in ENGAGEMENT
              else ENGAGEMENT[2])
        p["engagement"] = st.radio("Choose a level:", ENGAGEMENT, key="w_engagement")
        st.divider()
        st.caption("Separate from how involved you are: which data you share with us. "
                   "The app works without it, the estimates are just less precise.")
        _seed("w_data_meter", bool(p.get("data_meter", True)))
        p["data_meter"] = st.toggle("Load curve from the smart meter", key="w_data_meter")
        _seed("w_data_devices", bool(p.get("data_devices", False)))
        p["data_devices"] = st.toggle("Connected devices (smart plugs, charger)",
                                      key="w_data_devices")

    _nav()


def first_estimate() -> None:
    """The first result, shown right after the questionnaire.

    Year-round appliances make up the headline; seasonal ones (a summer pool,
    winter underfloor heating) are listed with their season and whether they
    count right now, so the number is never a summer promise read in November.
    """
    import datetime

    profile = store.profile()
    gap = PRICE_BUY_LEI_KWH - PRICE_SELL_LEI_KWH
    month = datetime.date.today().month

    rows = []
    for k in profile.get("appliances", []):
        m = monthly_saving(k, profile, gap)
        if m >= 1.0:
            rows.append((k, m, season_label(k, profile), in_season(k, profile, month)))
    if not rows:
        st.info("Profile saved. Recommendations will appear as we collect data about "
                "your consumption.")
        return

    year_round = sorted([r for r in rows if not r[2]], key=lambda r: -r[1])
    seasonal = sorted([r for r in rows if r[2]], key=lambda r: -r[1])
    base = sum(m for _, m, _, _ in year_round)

    if year_round:
        named = "; ".join(f"{APPLIANCES.get(k, k).lower()} run during the day "
                          f"(~{m:.0f} lei/month)" for k, m, _, _ in year_round[:3])
        head = f"Based on your profile, you could save about **{base:.0f} lei/month " \
               f"all year** by running these in the middle of the day: {named}."
    else:
        head = "Based on your profile, most of your savings are seasonal:"

    extra = []
    for k, m, label, now in seasonal:
        when = "in season now" if now else "off-season right now"
        extra.append(f"the {APPLIANCES.get(k, k).lower()} adds about **{m:.0f} lei/month "
                     f"while it is in use** ({label}, {when})")
    tail = ""
    if extra:
        joined = "; ".join(extra)
        tail = " " + joined[0].upper() + joined[1:] + "."

    st.success(head + tail + " A rough estimate, refined as your real data comes in.")
