"""PVGIS check (organisers' starting point for "lower than expected"): PVGIS, the European
Commission JRC's free tool, estimates how much a PV system of a given size, tilt and
orientation should produce in an average month at that location. We compare each site's
actual daily energy with the PVGIS daily average for the same month.

This is a coarse monthly sanity check next to our 15-minute weather model: PVGIS knows the
long-term climate, not this month's clouds, so only big gaps mean something.

PVGIS needs internet. Results are cached in data/pvgis_cache.json, so run once on a machine
with network (python run_demo.py --pvgis) and the demo works offline afterwards.
"""
import json
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

URL = "https://re.jrc.ec.europa.eu/api/v5_2/PVcalc"
CACHE = Path("data/pvgis_cache.json")


def fetch_monthly(site: dict, loss_pct: float = 14.0) -> pd.DataFrame:
    """Average energy per month for one site: month, E_d (kWh/day), E_m (kWh/month).
    Azimuth convention matches ours and PVGIS 'aspect': 0 = south, -90 = east, 90 = west."""
    params = {"lat": site["lat"], "lon": site["lon"], "peakpower": site["kwp"],
              "loss": loss_pct, "angle": site["tilt"], "aspect": site["azimuth"],
              "outputformat": "json"}
    with urllib.request.urlopen(URL + "?" + urllib.parse.urlencode(params), timeout=30) as r:
        data = json.load(r)
    rows = data["outputs"]["monthly"]["fixed"]
    return pd.DataFrame([{"month": int(x["month"]), "E_d": float(x["E_d"]), "E_m": float(x["E_m"])}
                         for x in rows])


def load_or_fetch(sites: pd.DataFrame, cache: Path = CACHE, fetch: bool = True) -> pd.DataFrame:
    """Cached PVGIS months for every site; fetches the missing ones if allowed."""
    store = json.loads(cache.read_text()) if cache.exists() else {}
    changed = False
    for s in sites.to_dict("records"):
        key = f'{s["site_id"]}:{s["lat"]}:{s["lon"]}:{s["kwp"]}:{s["tilt"]}:{s["azimuth"]}'
        if key in store or not fetch:
            continue
        try:
            store[key] = fetch_monthly(s).to_dict("records")
            changed = True
        except Exception as e:                       # offline, proxy, API change
            print(f"  PVGIS unavailable for {s['site_id']} ({type(e).__name__}); skipped")
            break
    if changed:
        cache.parent.mkdir(exist_ok=True)
        cache.write_text(json.dumps(store, indent=1))
    rows = []
    for key, months in store.items():
        sid = key.split(":")[0]
        if sid in set(sites.site_id):
            rows += [{"site_id": sid, **m} for m in months]
    return pd.DataFrame(rows)


def monthly_check(telemetry: pd.DataFrame, pvgis: pd.DataFrame, flag_below: float = 0.7) -> pd.DataFrame:
    """Actual kWh/day per site and month vs the PVGIS average for that month."""
    if pvgis.empty:
        return pd.DataFrame()
    t = telemetry.assign(month=telemetry.timestamp.dt.tz_convert("Europe/Bucharest").dt.month,
                         day=telemetry.timestamp.dt.tz_convert("Europe/Bucharest").dt.date)
    daily = t.groupby(["site_id", "month", "day"]).pv_kw.sum().mul(0.25).reset_index()
    act = daily.groupby(["site_id", "month"]).agg(actual_kwh_day=("pv_kw", "mean"),
                                                  days=("day", "count")).reset_index()
    out = act.merge(pvgis, on=["site_id", "month"])
    out["pct_of_pvgis"] = (100 * out.actual_kwh_day / out.E_d).round(0)
    out["flag"] = out.pct_of_pvgis < 100 * flag_below
    return out.rename(columns={"E_d": "pvgis_kwh_day"}).round(2)
