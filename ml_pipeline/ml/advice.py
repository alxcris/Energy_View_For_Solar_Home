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
#48 hours so we use an entire sun day
#window_h is the window recommend for charging big appliances
#top = maximum number of recommandations (2 for normal people used to their habits)
#tariff = None for the case where it isn't mentioned
#feed_in_lei_kwh = the price with which the user sells the produced current
def consumption_advice(expected: pd.DataFrame, telemetry: pd.DataFrame, site_id: str,
                       hours: int = 48, window_h: float = 2.0, top: int = 2,
                       tariff=None, feed_in_lei_kwh: float = FEED_IN_LEI_KWH,
                       appliance_kw: float = 1.0, usual_start_h: float = 19.0,
                       earliest_h: float = 7.0, latest_h: float = 23.0,
                       min_saving_lei: float = 0.1):
    """Cheapest time to run one heavy appliance (`appliance_kw` for `window_h` hours),
    at most one window per day.

    Cost of a window = grid energy x tariff price + own solar used x feed-in price
    (solar you use is solar you don't sell). The saving is measured against running
    the same appliance at the household's usual time (`usual_start_h`) on grid power.
    With a fixed tariff the winner is the sunniest window; with a time-of-use tariff a
    cheap evening or weekend slot can beat a weak winter sun.
    """
    tariff = as_tariff(tariff)
    now = telemetry[telemetry.site_id == site_id].timestamp.max()
    fut = expected[(expected.site_id == site_id) & (expected.timestamp > now)
                   & (expected.timestamp <= now + pd.Timedelta(hours=hours))].sort_values("timestamp")
    w = int(window_h * 4)
    if len(fut) < w:
        return []
    t = pd.DatetimeIndex(fut.timestamp)
    dt = 0.25
    surplus_kw = np.clip(fut.expected_kw.values - load_forecast(telemetry, site_id, t), 0, None)
    solar_kw = np.minimum(surplus_kw, appliance_kw)          # part of the run your panels cover
    price = tariff.price(t)
    slot_cost = ((appliance_kw - solar_kw) * price + solar_kw * feed_in_lei_kwh) * dt
    ones = np.ones(w)
    cost = np.convolve(slot_cost, ones, mode="valid")
    solar_kwh = np.convolve(solar_kw * dt, ones, mode="valid")
    surplus_kwh = np.convolve(surplus_kw * dt, ones, mode="valid")
    avg_price = np.convolve(price, ones, mode="valid") / w

    local = t.tz_convert("Europe/Bucharest")[: len(cost)]
    start_h = local.hour + local.minute / 60
    allowed = (start_h >= earliest_h) & (start_h + window_h <= latest_h)
    run_kwh = appliance_kw * window_h
    usual = f"{int(usual_start_h):02d}:{int(usual_start_h % 1 * 60):02d}"

    picks = []
    days = sorted(set(local.date))
    for day in days:
        idx = np.where(allowed & (local.date == day))[0]
        if not len(idx):
            continue
        # among equally cheap windows prefer the sunniest: safer if the forecast is a bit off
        i = int(idx[np.argmin(cost[idx] - 1e-3 * surplus_kwh[idx])])
        usual_price = price_at_local(tariff, day, usual_start_h, window_h).mean()
        saving = run_kwh * usual_price - cost[i]
        if saving < min_saving_lei:
            continue                       # no better time than the usual one, don't nag
        start = local[i]
        end = start + pd.Timedelta(hours=window_h)
        share = solar_kwh[i] / run_kwh
        # where does the saving come from: own solar, or a cheaper hour of the tariff?
        from_solar = solar_kwh[i] * (avg_price[i] - feed_in_lei_kwh)
        from_tariff = run_kwh * (usual_price - avg_price[i])
        if from_solar >= from_tariff:
            reason = "solar"
            why = f"your panels cover ~{share:.0%} of a {run_kwh:.0f} kWh run"
        else:
            reason = "cheap_tariff"
            why = f"off-peak price, {avg_price[i]:.2f} lei/kWh instead of {usual_price:.2f}"
            if share >= 0.1:
                why += f", plus ~{share:.0%} from your panels"
        picks.append({
            "start_local": start, "end_local": end,
            "surplus_kwh": round(float(surplus_kwh[i]), 1),
            "solar_kwh": round(float(solar_kwh[i]), 1),
            "avg_price_lei_kwh": round(float(avg_price[i]), 2),
            "cost_lei": round(float(cost[i]), 2),
            "saving_lei": round(float(saving), 2),
            "reason": reason,
            "text": (f"{start:%a %H:%M}-{end:%H:%M}: {why}. Good time for the washing machine, "
                     f"dishwasher or water heater: ~{saving:.1f} lei saved vs. running it at "
                     f"{usual} on grid power."),
        })
    picks = sorted(picks, key=lambda p: -p["saving_lei"])[:top]
    return sorted(picks, key=lambda p: p["start_local"])
