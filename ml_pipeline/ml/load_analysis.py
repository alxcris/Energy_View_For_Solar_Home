"""Analysis of a real consumer load curve (the mentor's test file), following his advice:
look at it by season, weekday/weekend, day/night, holidays and vacations, and when
you see a drop, explain what happened there.

  operating_schedule  - when the site actually runs (shifts), from the weekly profile
  growth              - rolling level of consumption (a ramping-up site breaks annual baselines)
  find_drops          - days far below their expected level, each with a label:
                        legal holiday / bridge day / company break / unexplained -> ask the client
  forecast_eval       - day-ahead hourly load forecast (gradient boosting) vs. naive baselines
  pv_what_if          - what a rooftop PV system would do for this load: self-consumption,
                        surplus, and the hours when the inject-or-store decision matters
"""
import datetime as dt

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from .calendar_ro import holiday_name, is_holiday, western_easter
from .real_data import hourly
from .solar import physical_pv_kw
from .weather import synthetic_weather

TZ = "Europe/Bucharest"


def _local_hourly(df):
    h = hourly(df)
    h["local"] = h.timestamp.dt.tz_convert(TZ)
    return h


def daily_kwh(df) -> pd.Series:
    loc = df.timestamp.dt.tz_convert(TZ)
    s = (df.load_kw * 0.25).groupby(loc.dt.date).sum()
    s.index = pd.to_datetime(s.index)
    return s


# ---------------------------------------------------------------- schedule

def operating_schedule(df, on_frac: float = 0.35) -> dict:
    """Average weekly profile (normal working weeks only) -> running hours per weekday."""
    h = _local_hourly(df)
    days = h.local.dt.date
    hol = days.map(is_holiday)
    # drop the holiday weeks and the first ramp-up month so the profile is "normal"
    h = h[~hol & (h.local >= h.local.min() + pd.Timedelta(days=60))]
    prof = h.groupby([h.local.dt.dayofweek, h.local.dt.hour]).load_kw.mean().unstack()
    on = prof > on_frac * prof.values.max()
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    out = {}
    for dow in range(7):
        hrs = [hr for hr in range(24) if on.loc[dow, hr]]
        out[names[dow]] = _ranges(hrs)
    base = float(h[h.local.dt.dayofweek == 6].load_kw.median())   # Sunday = stopped
    return {"hours": out, "profile_kw": prof.round(1), "base_kw": round(base, 1),
            "peak_kw": round(float(h.load_kw.max()), 1)}


def _ranges(hours):
    if not hours:
        return "off"
    out, start, prev = [], hours[0], hours[0]
    for h in hours[1:] + [None]:
        if h is not None and h == prev + 1:
            prev = h
            continue
        out.append(f"{start:02d}-{prev + 1:02d}")
        if h is not None:
            start = prev = h
    return ", ".join(out)


# ---------------------------------------------------------------- growth & drops

def growth(df) -> pd.DataFrame:
    """Monthly average power and working-day energy: is the site ramping up?"""
    d = daily_kwh(df)
    work = d[d.index.dayofweek < 5]
    m = pd.DataFrame({"avg_kw": d.resample("MS").mean() / 24,
                      "workday_kwh": work.resample("MS").median()}).round(0)
    m.index = m.index.strftime("%Y-%m")
    return m


def seasonality(df) -> pd.DataFrame:
    """Median kW by month for the blocks that tell the story: day shift, evening shift,
    the dead hours of the night and Sunday standby (heating/cooling show up there)."""
    loc = df.timestamp.dt.tz_convert(TZ)
    h, dow, m = loc.dt.hour, loc.dt.dayofweek, loc.dt.strftime("%Y-%m")
    wd = dow < 5
    blocks = {
        "day shift 09-17": wd & (h >= 9) & (h < 17),
        "evening 20-24": wd & (h >= 20),
        "night 03-06": wd & (h >= 3) & (h < 6),
        "Sunday standby": dow == 6,
    }
    return pd.DataFrame({k: df.load_kw[v].groupby(m[v]).median() for k, v in blocks.items()}).round(0)


def find_drops(df, ratio: float = 0.5) -> pd.DataFrame:
    """Days below `ratio` x the rolling median of the same weekday (+/- 3 weeks),
    so a growing site does not look like a series of drops. Each drop gets a label."""
    d = daily_kwh(df)
    exp = pd.Series(np.nan, index=d.index)
    for dow in range(7):
        s = d[d.index.dayofweek == dow]
        exp[s.index] = s.rolling(7, center=True, min_periods=3).median()
    r = d / exp
    drops = d[(r < ratio) & (d.index.dayofweek < 6)]   # Sunday is always off
    rows = []
    for day, kwh in drops.items():
        rows.append({"date": day.date(), "weekday": day.strftime("%a"),
                     "kwh": round(kwh), "expected_kwh": round(exp[day]),
                     "pct_of_expected": round(100 * kwh / exp[day]),
                     "explanation": _explain(day.date(), set(drops.index.date))})
    out = pd.DataFrame(rows)
    # merge consecutive days into periods for the slide
    if len(out):
        gap = pd.to_datetime(out.date).diff().dt.days.fillna(99) > 3
        out["period"] = gap.cumsum()
    return out


def _explain(day: dt.date, drop_days: set) -> str:
    name = holiday_name(day)
    if name:
        return f"legal holiday: {name}"
    for k in (1, -1):                      # bridge day next to a holiday or weekend+holiday
        n = day + dt.timedelta(days=k)
        if holiday_name(n):
            return f"bridge day next to {holiday_name(n)}"
    if dt.date(day.year, 12, 22) <= day or day <= dt.date(day.year, 1, 8):
        return "winter break (company closed between holidays)"
    if day == western_easter(day.year) + dt.timedelta(days=1):
        return "Catholic Easter Monday (not a RO holiday) - foreign parent company? ask"
    run = sum(1 for k in range(-6, 7) if day + dt.timedelta(days=k) in drop_days)
    if run >= 3:
        return "multi-day stop - planned maintenance or vacation? ask the client"
    return "unexplained - ask the client (outage, partial shift, fault?)"


# ---------------------------------------------------------------- forecast

def _features(h: pd.DataFrame) -> pd.DataFrame:
    h = h.sort_values("timestamp").copy()
    loc = h.timestamp.dt.tz_convert(TZ)
    h["hour"], h["dow"], h["month"] = loc.dt.hour, loc.dt.dayofweek, loc.dt.month
    h["holiday"] = loc.dt.date.map(is_holiday).astype(int)
    s = h.set_index("timestamp").load_kw
    h["lag_24"] = s.shift(24, freq="h").reindex(h.timestamp).values
    h["lag_168"] = s.shift(168, freq="h").reindex(h.timestamp).values
    h["lag_336"] = s.shift(336, freq="h").reindex(h.timestamp).values
    h["same_hour_4w"] = np.nanmedian(np.vstack([s.shift(168 * k, freq="h").reindex(h.timestamp).values
                                                for k in range(1, 5)]), axis=0)
    h["holiday_lag_168"] = (loc - pd.Timedelta(days=7)).dt.date.map(is_holiday).astype(int).values
    # level of the site over the last 7 days, known the day before (captures the ramp-up)
    lvl = s.rolling("7D").mean().shift(24, freq="h").reindex(h.timestamp).values
    h["level_7d"] = lvl
    return h.dropna(subset=["lag_168", "level_7d"])


FEATS = ["hour", "dow", "holiday", "lag_24", "lag_168", "lag_336", "same_hour_4w",
         "holiday_lag_168", "level_7d"]


def forecast_eval(df, test_days: int = 91) -> dict:
    """Train on the first ~9 months, forecast the last `test_days` day-ahead (hourly).
    Target is load relative to the 7-day level, so a growing site does not fool the model."""
    h = _features(hourly(df))
    split = h.timestamp.max() - pd.Timedelta(days=test_days)
    tr, te = h[h.timestamp <= split], h[h.timestamp > split].copy()
    y = tr.load_kw / tr.level_7d.clip(lower=1)
    gbm = HistGradientBoostingRegressor(max_iter=500, learning_rate=0.05, max_leaf_nodes=31,
                                        l2_regularization=1.0, random_state=0)
    gbm.fit(tr[FEATS], y)
    te["gbm"] = np.clip(gbm.predict(te[FEATS]), 0, None) * te.level_7d.clip(lower=1)
    te["naive_week"] = te.lag_168
    # holiday-aware naive: if last week's day was a holiday, use two weeks ago
    s = h.set_index("timestamp").load_kw
    lag336 = s.shift(336, freq="h").reindex(te.timestamp).values
    te["naive_week_holiday_aware"] = np.where(te.holiday_lag_168 == 1, lag336, te.lag_168)

    def wmape(col, g=te):
        return round(100 * (g[col] - g.load_kw).abs().sum() / g.load_kw.sum(), 1)
    loc = te.timestamp.dt.tz_convert(TZ)
    daily = te.groupby(loc.dt.date)[["load_kw", "gbm", "naive_week", "naive_week_holiday_aware"]].sum()
    # days the client stopped without announcing it cannot be forecast from history;
    # score separately on normal days to show the model, not the stops, drives the error
    drop_days = set(find_drops(df).date)
    normal = te[~loc.dt.date.isin(drop_days).values]
    nd = daily[~pd.Index(daily.index).isin(drop_days)]
    rows = []
    for name, col in [("same hour last week", "naive_week"),
                      ("same hour last week, holiday-aware", "naive_week_holiday_aware"),
                      ("gradient boosting (ours)", "gbm")]:
        rows.append({"model": name, "hourly_wMAPE_%": wmape(col),
                     "daily_wMAPE_%": round(100 * (daily[col] - daily.load_kw).abs().sum()
                                            / daily.load_kw.sum(), 1),
                     "hourly_wMAPE_normal_days_%": wmape(col, normal),
                     "daily_wMAPE_normal_days_%": round(100 * (nd[col] - nd.load_kw).abs().sum()
                                                        / nd.load_kw.sum(), 1)})
    return {"table": pd.DataFrame(rows), "test": te, "model": gbm,
            "test_from": split.tz_convert(TZ).date()}


# ---------------------------------------------------------------- PV what-if

def pv_what_if(df, sizes_kwp=(200, 400, 600), lat=44.43, lon=26.10, tilt=15, azimuth=0,
               retail_lei_kwh=0.85, injection_lei_kwh=0.30, seed=7) -> pd.DataFrame:
    """Rooftop PV on this load, one year at 15 min. Synthetic weather (swap for the
    Open-Meteo archive on a machine with network). Self-consumed energy is valued at
    the retail price, surplus at a typical injection price."""
    site = {"site_id": "C01", "lat": lat, "lon": lon, "tilt": tilt, "azimuth": azimuth}
    t0, t1 = df.timestamp.min(), df.timestamp.max() + pd.Timedelta(minutes=15)
    w = synthetic_weather(site, t0.floor("D"), t1.ceil("D"), seed=seed)
    w = w.set_index("timestamp").reindex(df.timestamp).ffill()
    load = df.load_kw.values
    loc = df.timestamp.dt.tz_convert(TZ)
    offday = (loc.dt.dayofweek == 6) | loc.dt.date.map(is_holiday)
    rows = []
    for kwp in sizes_kwp:
        pv = physical_pv_kw(w.gti.values, w.temp_c.values, kwp, inverter_kw=0.9 * kwp)
        self_c = np.minimum(pv, load)
        surplus = pv - self_c
        e = lambda x: x.sum() * 0.25 / 1000            # MWh
        rows.append({
            "kWp": kwp,
            "pv_MWh": round(e(pv), 0),
            "self_consumed_%": round(100 * self_c.sum() / max(pv.sum(), 1e-9), 0),
            "load_covered_%": round(100 * self_c.sum() / load.sum(), 0),
            "surplus_MWh": round(e(surplus), 0),
            "surplus_on_sundays_holidays_%": round(100 * surplus[offday.values].sum()
                                                   / max(surplus.sum(), 1e-9), 0),
            "savings_k_lei_per_year": round((e(self_c) * retail_lei_kwh
                                             + e(surplus) * injection_lei_kwh), 0),
        })
    return pd.DataFrame(rows)
