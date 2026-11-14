"""The file calculates the daily usage of a client and suggests
when to run heavy appliances to use their own solar power."""
import numpy as np
#for tables
import pandas as pd
#opens calender_ro.py
from .calendar_ro import is_holiday
#all prices come from tariffs.py
from .tariffs import FEED_IN_LEI_KWH, as_tariff, price_at_local
#ix is a list of moments of time
#the output is an array
def _offday(ix: pd.DatetimeIndex) -> np.ndarray:
    """Weekend or Romanian legal holiday"""
    return (ix.dayofweek >= 5) | np.array([is_holiday(d) for d in ix.date])
#site_id = the location of an installation
#future_times data is taken from the "expected" table
#days: standard 28
def load_forecast(telemetry: pd.DataFrame, site_id: str, future_times: pd.DatetimeIndex, days: int = 28):
    #hist = history
    #keeps only the lines of site_id
    hist = telemetry[telemetry.site_id == site_id]
    #keeps on the last 28 days
    hist = hist[hist.timestamp >= hist.timestamp.max() - pd.Timedelta(days=days)]
    #converts to Romanian hour
    loc = pd.DatetimeIndex(hist.timestamp).tz_convert("Europe/Bucharest")
    #creates a key for comparing similar data
    key = lambda ix: list(zip(_offday(ix), ix.hour * 4 + ix.minute // 15))
    #the profile of a house
    prof = hist.assign(k=key(loc)).groupby("k").load_kw.median()
    floc = future_times.tz_convert("Europe/Bucharest")
    return np.array([prof.get(k, hist.load_kw.median()) for k in key(floc)])
def _forecast(expected: pd.DataFrame, telemetry: pd.DataFrame, site_id: str, hours: int):
    """Future 15-min timestamps and the solar surplus forecast (kW) for one site."""
    now = telemetry[telemetry.site_id == site_id].timestamp.max()
    fut = expected[(expected.site_id == site_id) & (expected.timestamp > now)
                   & (expected.timestamp <= now + pd.Timedelta(hours=hours))].sort_values("timestamp")
    if fut.empty:
        return None, None
    t = pd.DatetimeIndex(fut.timestamp)
    surplus_kw = np.clip(fut.expected_kw.values - load_forecast(telemetry, site_id, t), 0, None)
    return t, surplus_kw


def _best_windows(t, surplus_kw, tariff, feed_in_lei_kwh, appliance_kw, window_h, usual_start_h,
                  earliest_h, latest_h, min_saving_lei, top, min_saving_share=0.0):
    """Cheapest window per day for one appliance. Returns numbers only (no text), plus the
    slot index `i` and length `w` so a caller can book the solar it uses."""
    #an hour has 4 15 min
    w = int(window_h * 4)
    #if there isn't enough data about the future, the program stops
    if t is None or len(t) < w:
        return []
    #dt = 15/60 = 0,25 hours
    dt = 0.25
    #calculates how much of the power of the appliance is covered by the solar pannel
    solar_kw = np.minimum(surplus_kw, appliance_kw)
    #how much does a one Kwh will cost in the future
    price = tariff.price(t)
    slot_cost = ((appliance_kw - solar_kw) * price + solar_kw * feed_in_lei_kwh) * dt
    #ones is the frame that helps understand the way the code runs
    ones = np.ones(w)
    #convolve moves the frame
    cost = np.convolve(slot_cost, ones, mode="valid")
    solar_kwh = np.convolve(solar_kw * dt, ones, mode="valid")
    surplus_kwh = np.convolve(surplus_kw * dt, ones, mode="valid")
    avg_price = np.convolve(price, ones, mode="valid") / w

    local = t.tz_convert("Europe/Bucharest")[: len(cost)]
    start_h = local.hour + local.minute / 60
    allowed = (start_h >= earliest_h) & (start_h + window_h <= latest_h)
    run_kwh = appliance_kw * window_h

    picks = []
    for day in sorted(set(local.date)):
        idx = np.where(allowed & (local.date == day))[0]
        if not len(idx):
            continue
        # among equally cheap windows prefer the sunniest: safer if the forecast is a bit off
        i = int(idx[np.argmin(cost[idx] - 1e-3 * surplus_kwh[idx])])
        usual_price = price_at_local(tariff, day, usual_start_h, window_h).mean()
        saving = run_kwh * usual_price - cost[i]
        if saving < max(min_saving_lei, min_saving_share * run_kwh * usual_price):
            continue                       # no better time than the usual one, don't nag
        share = solar_kwh[i] / run_kwh
        # where does the saving come from: own solar, or a cheaper hour of the tariff?
        from_solar = solar_kwh[i] * (avg_price[i] - feed_in_lei_kwh)
        from_tariff = run_kwh * (usual_price - avg_price[i])
        if from_solar >= from_tariff:
            reason = "solar"
            why = f"your panels cover ~{share:.0%} of the {round(run_kwh, 1):g} kWh"
        else:
            reason = "cheap_tariff"
            why = f"off-peak price, {avg_price[i]:.2f} lei/kWh instead of {usual_price:.2f}"
            if share >= 0.1:
                why += f", plus ~{share:.0%} from your panels"
        picks.append({
            "i": i, "w": w,
            "start_local": local[i], "end_local": local[i] + pd.Timedelta(hours=window_h),
            "surplus_kwh": round(float(surplus_kwh[i]), 1),
            "solar_kwh": round(float(solar_kwh[i]), 1),
            "avg_price_lei_kwh": round(float(avg_price[i]), 2),
            "cost_lei": round(float(cost[i]), 2),
            "saving_lei": round(float(saving), 2),
            "reason": reason, "why": why,
        })
    picks = sorted(picks, key=lambda p: -p["saving_lei"])[:top]
    return sorted(picks, key=lambda p: p["start_local"])


def _hhmm(h: float) -> str:
    return f"{int(h):02d}:{int(h % 1 * 60):02d}"


#48 hours so we use an entire sun day
#window_h is the window recommend for charging big appliances
#top = maximum number of recommandations (2 for normal people used to their habits)
#tariff = None for the case where it isn't mentioned
#feed_in_lei_kwh = the price with which the user sells the produced current
#appliance_kw = the average of the power used for the appliance in question
def consumption_advice(expected: pd.DataFrame, telemetry: pd.DataFrame, site_id: str,
                       hours: int = 48, window_h: float = 2.0, top: int = 2,
                       tariff=None, feed_in_lei_kwh: float = FEED_IN_LEI_KWH,
                       appliance_kw: float = 1.0, usual_start_h: float = 19.0,
                       earliest_h: float = 7.0, latest_h: float = 23.0,
                       min_saving_lei: float = 0.1):
    """Cheapest time to run one generic heavy appliance (`appliance_kw` for `window_h` hours),
    at most one window per day.

    Cost of a window = grid energy x tariff price + own solar used x feed-in price
    (solar you use is solar you don't sell). The saving is measured against running
    the same appliance at the household's usual time (`usual_start_h`) on grid power.
    For named devices with a ready-made schedule, use appliance_plan() below.
    """
    t, surplus_kw = _forecast(expected, telemetry, site_id, hours)
    picks = _best_windows(t, surplus_kw, as_tariff(tariff), feed_in_lei_kwh, appliance_kw, window_h,
                          usual_start_h, earliest_h, latest_h, min_saving_lei, top)
    for p in picks:
        p["text"] = (f"{p['start_local']:%a %H:%M}-{p['end_local']:%H:%M}: {p['why']}. Good time for "
                     f"the washing machine, dishwasher or water heater: ~{p['saving_lei']:.1f} lei saved "
                     f"vs. running it at {_hhmm(usual_start_h)} on grid power.")
        for k in ("i", "w", "why"):
            p.pop(k)
    return picks


# Devices worth moving: big and flexible. Phones, tablets or laptops use a few cents a day,
# not worth a notification. usual_start_h is an ASSUMPTION until the household's own habit
# is known (ml/habits.py measures it). `how` is what the customer sets: the platform only
# suggests, it never switches the customer's equipment (brief constraint).
APPLIANCES = {
    "ev": dict(name="electric car", kw=3.7, hours=4.0, earliest_h=0, latest_h=24, usual_start_h=19.0,
               verb="Charge the car",
               how="set the charging schedule in the car's app or on the wallbox"),
    "water_heater": dict(name="water heater", kw=2.0, hours=2.0, earliest_h=0, latest_h=24, usual_start_h=18.0,
                         verb="Heat the water",
                         how="plug the boiler into a smart plug or a timer socket set to these hours"),
    "dishwasher": dict(name="dishwasher", kw=0.6, hours=2.5, earliest_h=0, latest_h=24, usual_start_h=20.0,
                       verb="Run the dishwasher",
                       how="load it as usual and use the delay-start button"),
    "washing_machine": dict(name="washing machine", kw=1.0, hours=2.0, earliest_h=7, latest_h=23,
                            usual_start_h=19.0, verb="Run the washing machine",
                            how="use the delay-start button (daytime only: noise, wet laundry)"),
}


def appliance_plan(expected: pd.DataFrame, telemetry: pd.DataFrame, site_id: str,
                   appliances=("ev", "water_heater", "washing_machine", "dishwasher"),
                   tariff=None, feed_in_lei_kwh: float = FEED_IN_LEI_KWH, hours: int = 48,
                   min_saving_lei: float = 0.1, min_saving_share: float = 0.05,
                   overrides: dict = None) -> list:
    """Tomorrow's schedule for the customer's own devices: when to switch each one on and off,
    how to set it (smart plug, timer, delay start, car app) and the lei saved.

    The solar surplus is shared: the biggest load is placed first and books the panels' output
    it uses, so two devices never count the same kWh. A window is only suggested if it saves at
    least `min_saving_share` (5%) of what the run costs at the usual time: 0.3 lei on a 20-lei
    car charge is not worth a notification. `overrides` changes a preset, e.g.
    {"ev": {"kw": 7.4}} for a faster wallbox.
    """
    #verifies if tariff is a real value
    tariff = as_tariff(tariff)
    t, surplus_kw = _forecast(expected, telemetry, site_id, hours)
    if t is None:
        return []
    remaining = surplus_kw.copy()
    specs = {k: {**APPLIANCES[k], **(overrides or {}).get(k, {})} for k in appliances}
    order = sorted(specs, key=lambda k: -specs[k]["kw"] * specs[k]["hours"])
    plan = []
    for key in order:
        a = specs[key]
        picks = _best_windows(t, remaining, tariff, feed_in_lei_kwh, a["kw"], a["hours"],
                              a["usual_start_h"], a["earliest_h"], a["latest_h"], min_saving_lei, top=2,
                              min_saving_share=min_saving_share)
        for p in picks:
            sl = slice(p["i"], p["i"] + p["w"])
            remaining[sl] -= np.minimum(remaining[sl], a["kw"])   # this solar is now taken
            on, off = p["start_local"], p["end_local"]
            plan.append({
                "appliance": key, "name": a["name"], **{k: v for k, v in p.items() if k not in ("i", "w", "why")},
                "schedule": {"on_local": on.isoformat(), "off_local": off.isoformat(), "how": a["how"]},
                "text": (f"{on:%a %H:%M}-{off:%H:%M}: {a['verb']} ({p['why']}). ~{p['saving_lei']:.1f} lei "
                         f"saved vs. {_hhmm(a['usual_start_h'])}. How: {a['how']}."),
            })
    return sorted(plan, key=lambda p: p["start_local"])


def schedule_ics(plan: list, site_id: str) -> str:
    """The plan as a calendar file (.ics): one reminder per device, so the customer gets a
    notification on the phone when it is time to switch something on. Nothing is sent to
    the devices themselves."""
    utc = lambda ts: pd.Timestamp(ts).tz_convert("UTC").strftime("%Y%m%dT%H%M%SZ")
    stamp = utc(pd.Timestamp.now(tz="UTC"))
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//One energy view//solar schedule//EN"]
    for n, p in enumerate(plan):
        desc = p["text"].replace(",", "\\,").replace(";", "\\;")   # escaping required by .ics
        lines += ["BEGIN:VEVENT", f"UID:{site_id}-{p['appliance']}-{utc(p['start_local'])}-{n}@energyview",
                  f"DTSTAMP:{stamp}", f"DTSTART:{utc(p['start_local'])}", f"DTEND:{utc(p['end_local'])}",
                  f"SUMMARY:{p['name'].capitalize()}: ~{p['saving_lei']:.1f} lei saved",
                  f"DESCRIPTION:{desc}",
                  "BEGIN:VALARM", "TRIGGER:-PT10M", "ACTION:DISPLAY",
                  f"DESCRIPTION:{p['name'].capitalize()} in 10 minutes", "END:VALARM", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
