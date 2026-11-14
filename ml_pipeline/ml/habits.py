"""Consumer side: learn each household's habits from its load data and turn them
into targeted, quantified nudges (mentor feedback, 14 Nov).

Three pieces:
  1. detect_events       - heavy-appliance runs found in load_kw (spikes over a rolling baseline)
  2. find_habits         - recurring events clustered by local time of day -> a habit
                           ("most evenings around 19:30 you run a ~2 kW appliance for 1 h")
  3. habit_recommendations - for each habit that burns grid power, the concrete move:
                           shift it into tomorrow's solar-surplus window, with the lei saved
  4. peer_benchmark      - evening consumption share vs. the median of the fleet
                           ("similar homes use 24% of their day in the evening peak, you use 35%")

All texts are one short sentence: these are push notifications, not reports.
Analysing behaviour across users (the benchmark) needs user consent in the app.
"""
import numpy as np
import pandas as pd

from .advice import load_forecast
from .tariffs import FEED_IN_LEI_KWH, price_at_local

TZ = "Europe/Bucharest"


def detect_events(telemetry: pd.DataFrame, site_id: str, days: int = 28,
                  min_kw: float = 1.0, min_steps: int = 2, max_steps: int = 16) -> pd.DataFrame:
    """Heavy-appliance runs: load above a rolling-median baseline by >= min_kw
    for 30 min .. 4 h. Returns one row per event (start_local, duration_h, kwh, peak_kw)."""
    d = telemetry[telemetry.site_id == site_id].sort_values("timestamp")
    d = d[d.timestamp >= d.timestamp.max() - pd.Timedelta(days=days)]
    if d.empty:
        return pd.DataFrame(columns=["start_local", "duration_h", "kwh", "peak_kw", "from_grid_kwh"])
    base = d.load_kw.rolling(16, center=True, min_periods=4).median()
    resid = (d.load_kw - base).values
    on = resid > min_kw
    # grid_kw > 0 means the extra power is imported, not covered by the panels
    grid = np.clip(d.grid_kw.values, 0, None)
    rows, i, n = [], 0, len(on)
    t = pd.DatetimeIndex(d.timestamp).tz_convert(TZ)
    while i < n:
        if not on[i]:
            i += 1
            continue
        j = i
        while j < n and on[j]:
            j += 1
        if min_steps <= j - i <= max_steps:
            seg = slice(i, j)
            rows.append({
                "start_local": t[i],
                "duration_h": round((j - i) * 0.25, 2),
                "kwh": round(float(resid[seg].sum()) * 0.25, 2),
                "peak_kw": round(float(resid[seg].max()), 2),
                "from_grid_kwh": round(float(np.minimum(resid[seg], grid[seg]).clip(0).sum()) * 0.25, 2),
            })
        i = j
    return pd.DataFrame(rows)


def find_habits(events: pd.DataFrame, min_count: int = 6, tol_h: float = 1.5) -> pd.DataFrame:
    """Cluster events by local start hour: >= min_count events within +/- tol_h = a habit."""
    if events.empty:
        return pd.DataFrame(columns=["median_start_h", "events", "kwh_per_event",
                                     "duration_h", "share_from_grid", "label"])
    ev = events.assign(h=[s.hour + s.minute / 60 for s in events.start_local])
    habits, used = [], np.zeros(len(ev), dtype=bool)
    for _ in range(4):                       # at most a few distinct habits
        free = ev[~used]
        if len(free) < min_count:
            break
        # densest 2*tol_h window on the (circular) clock
        counts = {h: ((np.abs((free.h - h + 12) % 24 - 12)) <= tol_h).sum() for h in range(24)}
        h0 = max(counts, key=counts.get)
        m = (np.abs((ev.h - h0 + 12) % 24 - 12) <= tol_h) & ~used
        if m.sum() < min_count:
            break
        used |= m.values
        g = ev[m]
        med_h = float(g.h.median())
        habits.append({
            "median_start_h": round(med_h, 2),
            "events": int(m.sum()),
            "kwh_per_event": round(float(g.kwh.median()), 2),
            "duration_h": round(float(g.duration_h.median()), 2),
            "share_from_grid": round(float(g.from_grid_kwh.sum() / max(g.kwh.sum(), 0.1)), 2),
            "label": _label(med_h, float(g.kwh.median()), float(g.duration_h.median())),
        })
    if not habits:
        return pd.DataFrame(columns=["median_start_h", "events", "kwh_per_event",
                                     "duration_h", "share_from_grid", "label"])
    return pd.DataFrame(habits).sort_values("median_start_h").reset_index(drop=True)


def _label(hour: float, kwh: float, dur_h: float) -> str:
    if kwh >= 5 and dur_h >= 2:
        return "EV or boiler charging"
    if 17 <= hour <= 22:
        return "evening appliance (washing machine, oven)"
    if 6 <= hour <= 10:
        return "morning appliance"
    return "heavy appliance"


def habit_recommendations(habits: pd.DataFrame, expected: pd.DataFrame, telemetry: pd.DataFrame,
                          site_id: str, tariff=None,
                          feed_in_lei_kwh: float = FEED_IN_LEI_KWH) -> list:
    """One push notification per habit worth moving: shift it into tomorrow's best
    solar-surplus window and say how many lei that saves per run and per month."""
    now = telemetry[telemetry.site_id == site_id].timestamp.max()
    fut = expected[(expected.site_id == site_id) & (expected.timestamp > now)
                   & (expected.timestamp <= now + pd.Timedelta(hours=36))].sort_values("timestamp")
    out = []
    if fut.empty or habits.empty:
        return out
    t = pd.DatetimeIndex(fut.timestamp)
    surplus_kw = np.clip(fut.expected_kw.values - load_forecast(telemetry, site_id, t), 0, None)
    tl = t.tz_convert(TZ)
    for _, hb in habits.iterrows():
        if hb.share_from_grid < 0.4:
            continue                          # already mostly on solar, leave it alone
        w = max(int(hb.duration_h * 4), 1)
        roll = np.convolve(surplus_kw, np.ones(w), mode="valid") * 0.25
        if not len(roll) or roll.max() < 0.6 * hb.kwh_per_event:
            continue                          # no window with real surplus, don't nag
        i = int(np.argmax(roll))
        start = tl[i]
        movable = min(hb.kwh_per_event * hb.share_from_grid, float(roll[i]))
        # what that grid energy costs at the usual time, under the customer's own tariff
        usual_price = price_at_local(tariff, start.date(), float(hb.median_start_h),
                                     float(hb.duration_h)).mean()
        lei_run = movable * (usual_price - feed_in_lei_kwh)
        per_month = hb.events / 28 * 30
        out.append({
            "habit": hb.label,
            "usual_time": f"{int(hb.median_start_h):02d}:{int(hb.median_start_h % 1 * 60):02d}",
            "suggested_start_local": start,
            "saving_lei_per_run": round(lei_run, 2),
            "saving_lei_per_month": round(lei_run * per_month, 1),
            "text": (f"Your {hb.label} usually starts around {int(hb.median_start_h):02d}:"
                     f"{int(hb.median_start_h % 1 * 60):02d} and runs on grid power. Tomorrow "
                     f"{start:%H:%M}-{(start + pd.Timedelta(hours=float(hb.duration_h))):%H:%M} "
                     f"your panels cover it: ~{lei_run:.1f} lei saved per run, "
                     f"~{lei_run * per_month:.0f} lei/month."),
        })
    return out


def peer_benchmark(telemetry: pd.DataFrame, sites: pd.DataFrame, site_id: str,
                   days: int = 28, evening=(18, 23), min_peers: int = 3) -> dict:
    """Evening-peak share of consumption vs. the median of comparable sites.

    Data protection: only sites that accepted benchmarking (sites.consent_benchmark) are
    compared, the customer only ever sees an aggregate (the median), and with fewer than
    `min_peers` consenting peers nothing is shown, so no single neighbour can be inferred."""
    res = {"evening_share": None, "fleet_median": None, "flag": False, "text": "",
           "consent": True, "peers": 0}
    if "consent_benchmark" in sites:
        ok = set(sites.site_id[sites.consent_benchmark.astype(bool)])
        if site_id not in ok:
            res["consent"] = False
            return res
    else:
        ok = set(sites.site_id)
    d = telemetry[telemetry.timestamp >= telemetry.timestamp.max() - pd.Timedelta(days=days)]
    d = d[d.site_id.isin(ok)]
    h = pd.DatetimeIndex(d.timestamp).tz_convert(TZ).hour
    share = (d.assign(ev=(h >= evening[0]) & (h < evening[1]))
             .groupby("site_id")
             .apply(lambda g: g.load_kw[g.ev].sum() / max(g.load_kw.sum(), 0.1), include_groups=False))
    res["peers"] = int(len(share) - 1)
    if res["peers"] < min_peers or site_id not in share:
        return res
    mine, med = float(share[site_id]), float(share.drop(site_id).median())
    res.update({"evening_share": round(mine, 2), "fleet_median": round(med, 2),
                "flag": bool(mine > 1.15 * med)})
    if res["flag"]:
        res["text"] = (f"Homes like yours use {med:.0%} of their energy in the evening peak - "
                       f"you use {mine:.0%}. Moving one evening appliance to midday would close the gap.")
    return res
