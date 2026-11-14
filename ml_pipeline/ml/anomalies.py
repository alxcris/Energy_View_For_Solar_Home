"""Rule-based anomaly detection on top of the expected-production model.

Every alert is explainable ("produced 68% of what the weather allowed") and carries an
estimated cost, which is what O&M and the SLA care about.

Alert types:
    inverter_offline        near-zero production while the sun is up       (critical)
    sudden_underperformance step drop vs. expected, e.g. inverter/string     (warning/critical)
    gradual_degradation     slow drift, e.g. soiling                         (info/warning)
    battery_not_charging    solar surplus available but battery not charging (warning)
    comms_loss              telemetry missing                                (warning)
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .tariffs import FEED_IN_LEI_KWH, RETAIL_LEI_KWH

DT_H = 0.25  # 15 minutes


@dataclass
class Config:
    price_lei_kwh: float = RETAIL_LEI_KWH    # value of self-consumed kWh (tariffs.py)
    feed_in_lei_kwh: float = FEED_IN_LEI_KWH # value of exported kWh (tariffs.py)
    sunny_frac: float = 0.15           # row is "sunny" if expected >= 15% of kWp
    offline_ratio: float = 0.05        # actual < 5% of expected -> offline
    offline_min_rows: int = 4          # 1 hour
    min_daily_kwh_per_kwp: float = 0.4 # skip very dark days (ratio too noisy)
    sudden_ratio: float = 0.80         # daily ratio below this ...
    sudden_drop: float = 0.15          # ... and at least this far below the previous week
    sudden_min_days: int = 1
    drift_window: int = 5              # days in rolling ratio
    drift_ratio: float = 0.86
    drift_min_days: int = 3
    surplus_kw: float = 0.3
    soc_full: float = 90.0
    bat_min_rows: int = 4              # 1 hour of surplus with no charging
    gap_min_rows: int = 4              # 1 hour without data


def _runs(mask: np.ndarray):
    """Yield (start_idx, end_idx_inclusive) for consecutive True values."""
    if not mask.any():
        return
    d = np.diff(np.concatenate([[0], mask.astype(int), [0]]))
    for s, e in zip(np.where(d == 1)[0], np.where(d == -1)[0] - 1):
        yield s, e


def _merge_runs(mask: np.ndarray, max_gap: int):
    """Like _runs, but runs separated by <= max_gap False values are joined (one cloudy day)."""
    merged = []
    for a, b in _runs(mask):
        if merged and a - merged[-1][1] - 1 <= max_gap:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    return merged


def _alert(site, kind, severity, start, end, detected_at, ongoing, lost_kwh, lost_lei, msg, action):
    # site["name"], not site.name: on a pandas row .name is the index label
    return {"site_id": site.site_id, "site_name": site["name"], "type": kind, "severity": severity,
            "start": start, "end": end, "detected_at": detected_at, "ongoing": bool(ongoing),
            "lost_kwh": round(float(lost_kwh), 1), "lost_lei": round(float(lost_lei), 1),
            "message": msg, "action": action}


def detect_alerts(telemetry: pd.DataFrame, expected: pd.DataFrame, sites: pd.DataFrame,
                  cfg: Config = Config()) -> pd.DataFrame:
    alerts = []
    for _, s in sites.iterrows():
        tel = telemetry[telemetry.site_id == s.site_id].set_index("timestamp").sort_index()
        if tel.empty:
            continue
        exp = expected[expected.site_id == s.site_id].set_index("timestamp").sort_index()
        exp = exp.loc[tel.index.min():tel.index.max()]
        d = exp[["expected_kw"]].join(tel.drop(columns="site_id"), how="left")
        missing = d.pv_kw.isna().values
        offline_rows = np.zeros(len(d), dtype=bool)

        # 1. comms loss
        for a, b in _runs(missing):
            if b - a + 1 >= cfg.gap_min_rows:
                start, end = d.index[a], d.index[b] + pd.Timedelta(minutes=15)
                hours = (b - a + 1) * DT_H
                alerts.append(_alert(s, "comms_loss", "warning", start, end,
                                     start + pd.Timedelta(minutes=15 * cfg.gap_min_rows),
                                     b == len(d) - 1, 0, 0,
                                     f"No data received from the installation for {hours:.1f} h.",
                                     "Check the data logger connection / the client's router."))

        # 2. inverter offline — evaluated only on sunny rows, so a fault spanning the night stays one alert
        sunny = (d.expected_kw >= cfg.sunny_frac * s.kwp).values & ~missing
        idx = np.where(sunny)[0]
        bad = (d.pv_kw.values[idx] < cfg.offline_ratio * d.expected_kw.values[idx])
        for a, b in _runs(bad):
            if b - a + 1 < cfg.offline_min_rows:
                continue
            i0, i1 = idx[a], idx[b]
            # the inverter is offline until it actually produces again (also through clouds and night)
            pv, ex = d.pv_kw.values, d.expected_kw.values
            while (i1 + 1 < len(d) and not missing[i1 + 1]
                   and pv[i1 + 1] < max(cfg.offline_ratio * ex[i1 + 1], 0.01 * s.kwp)):
                i1 += 1
            offline_rows[i0:i1 + 1] = True
            seg = d.iloc[i0:i1 + 1]
            lost = ((seg.expected_kw - seg.pv_kw.fillna(0)).clip(lower=0) * DT_H).sum()
            alerts.append(_alert(s, "inverter_offline", "critical", d.index[i0],
                                 d.index[i1] + pd.Timedelta(minutes=15),
                                 d.index[idx[a + cfg.offline_min_rows - 1]] + pd.Timedelta(minutes=15),
                                 i1 == len(d) - 1, lost, lost * cfg.price_lei_kwh,
                                 "Near-zero production although the weather allows normal output.",
                                 "Check the inverter (error code, tripped protection). Urgent intervention."))

        # 3. daily energy ratio -> sudden drop / gradual drift
        dd = d.copy()
        dd["date"] = dd.index.tz_convert("Europe/Bucharest").date
        complete = dd.pv_kw.notna().groupby(dd.date).mean() >= 0.9
        explained = set(dd.date[offline_rows])   # already covered by an offline alert
        dd = dd[dd.date.map(complete) & ~dd.date.isin(explained)]
        daily = dd.groupby("date").agg(exp_kwh=("expected_kw", "sum"), act_kwh=("pv_kw", "sum")) * DT_H
        daily = daily[daily.exp_kwh >= cfg.min_daily_kwh_per_kwp * s.kwp]
        if len(daily) > cfg.drift_window:
            daily["ratio"] = daily.act_kwh / daily.exp_kwh
            base = daily.ratio.rolling(7, min_periods=3).median().shift(1)
            daily["roll"] = (daily.act_kwh.rolling(cfg.drift_window).sum()
                             / daily.exp_kwh.rolling(cfg.drift_window).sum())
            sudden = ((daily.ratio < cfg.sudden_ratio).values)
            used = np.zeros(len(daily), dtype=bool)
            for a, b in _merge_runs(sudden, max_gap=2):
                if b - a + 1 < cfg.sudden_min_days or (base.iloc[a] - daily.ratio.iloc[a]) < cfg.sudden_drop:
                    continue
                used[a:b + 1] = True
                seg = daily.iloc[a:b + 1]
                lost = (seg.exp_kwh - seg.act_kwh).sum()
                r = seg.act_kwh.sum() / seg.exp_kwh.sum()
                alerts.append(_alert(
                    s, "sudden_underperformance", "critical" if r < 0.6 else "warning",
                    _day_start(seg.index[0]), _day_end(seg.index[-1]),
                    _day_end(daily.index[a + cfg.sudden_min_days - 1]), b == len(daily) - 1,
                    lost, lost * cfg.price_lei_kwh,
                    f"Producing {100 * r:.0f}% of what the weather allowed "
                    f"(sudden drop from ~{100 * base.iloc[a]:.0f}% the week before).",
                    "Likely an inverter or string fault. Check per-MPPT curves and inverter error log."))
            drift = (daily.roll < cfg.drift_ratio).values & ~used
            for a, b in _merge_runs(drift, max_gap=2):
                if b - a + 1 < cfg.drift_min_days:
                    continue
                seg = daily.iloc[a:b + 1]
                lost = (seg.exp_kwh - seg.act_kwh).sum()
                r = seg.act_kwh.sum() / seg.exp_kwh.sum()
                per_month = lost / len(seg) * 30 * cfg.price_lei_kwh
                alerts.append(_alert(
                    s, "gradual_degradation", "warning" if r < 0.8 else "info",
                    _day_start(seg.index[0]), _day_end(seg.index[-1]),
                    _day_end(daily.index[a + cfg.drift_min_days - 1]), b == len(daily) - 1, lost, lost * cfg.price_lei_kwh,
                    f"Performance drifting down: {100 * r:.0f}% of expected over the last days "
                    f"(~{per_month:.0f} lei/month lost if left alone).",
                    "Likely soiling or new shading. Schedule panel cleaning / visual inspection."))

        # 4. battery not charging despite surplus
        if s.battery_kwh > 0:
            surplus = (d.pv_kw - d.load_kw).values
            cand = (~missing) & (surplus > cfg.surplus_kw) & (d.battery_soc.values < cfg.soc_full)
            idx = np.where(cand)[0]
            bad = d.battery_kw.values[idx] <= 0.05
            for a, b in _runs(bad):
                if b - a + 1 < cfg.bat_min_rows:
                    continue
                i0, i1 = idx[a], idx[b]
                rows = idx[a:b + 1]
                # energy that could have been stored: surplus per day, capped by usable capacity
                per_day = pd.Series(surplus[rows] * DT_H,
                                    index=d.index[rows].tz_convert("Europe/Bucharest").date).groupby(level=0).sum()
                lost = per_day.clip(upper=0.9 * s.battery_kwh).sum()
                alerts.append(_alert(
                    s, "battery_not_charging", "warning", d.index[i0], d.index[i1] + pd.Timedelta(minutes=15),
                    d.index[idx[a + cfg.bat_min_rows - 1]] + pd.Timedelta(minutes=15), b == len(bad) - 1,
                    lost, lost * (cfg.price_lei_kwh - cfg.feed_in_lei_kwh),
                    f"Battery not charging despite solar surplus (SoC {d.battery_soc.values[i1]:.0f}%). "
                    f"~{lost:.0f} kWh went to the grid instead of being stored.",
                    "Check the BMS / charging settings of the hybrid inverter."))

    cols = ["site_id", "site_name", "type", "severity", "start", "end", "detected_at", "ongoing",
            "lost_kwh", "lost_lei", "message", "action"]
    out = pd.DataFrame(alerts, columns=cols)
    if not out.empty:
        sev = {"critical": 0, "warning": 1, "info": 2}
        out = out.sort_values(["ongoing", "severity", "detected_at"],
                              key=lambda c: c.map(sev) if c.name == "severity" else c,
                              ascending=[False, True, False]).reset_index(drop=True)
        out.insert(0, "alert_id", [f"A{i + 1:03d}" for i in range(len(out))])
    return out


def _day_start(date):
    return pd.Timestamp(date).tz_localize("Europe/Bucharest").tz_convert("UTC")


def _day_end(date):
    return _day_start(date) + pd.Timedelta(days=1)
