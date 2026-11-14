"""End-to-end ML pipeline: weather -> simulated fleet -> expected production -> alerts.

    python run_demo.py                 # offline, synthetic weather
    python run_demo.py --real-weather  # Open-Meteo, last 92 days + 3-day forecast

Writes CSVs to out/ for the backend/dashboard and plots for the slides.
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

from ml.advice import consumption_advice
from ml.anomalies import Config, detect_alerts
import json

from ml.dispatch import plan_dispatch
from ml.tariffs import FixedTariff, TimeOfUseTariff
from ml.pvgis import load_or_fetch, monthly_check
from ml.impact import (ASSUMED_BASELINE_DAYS, ASSUMED_CREW_HOURS, detection_impact,
                       summary as impact_summary)
from ml.habits import detect_events, find_habits, habit_recommendations, peer_benchmark
from ml.model import ExpectedProductionModel, build_features, evaluate
from ml.simulate import SHADING, fault_schedule, simulate, site_table
from ml.weather import fetch_open_meteo, synthetic_weather

FAULT_TO_ALERT = {
    "inverter_derate": "sudden_underperformance",
    "inverter_offline": "inverter_offline",
    "soiling": "gradual_degradation",
    "battery_no_charge": "battery_not_charging",
    "comms_loss": "comms_loss",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--real-weather", action="store_true")
    ap.add_argument("--days", type=int, default=75, help="history length for synthetic weather")
    ap.add_argument("--out", default="out")
    ap.add_argument("--tariff", choices=["fixed", "tou"], default="fixed",
                    help="customer contract: fixed price or time-of-use (cheaper nights/weekends)")
    ap.add_argument("--baseline-days", type=float, default=ASSUMED_BASELINE_DAYS,
                    help="days after a fault starts that O&M finds out TODAY (from interviews)")
    ap.add_argument("--pvgis", action="store_true",
                    help="fetch PVGIS monthly baselines (needs internet once, then cached)")
    ap.add_argument("--crew-hours", type=float, default=ASSUMED_CREW_HOURS,
                    help="hours from detection to a fix on site (from interviews)")
    args = ap.parse_args()
    tariff = TimeOfUseTariff() if args.tariff == "tou" else FixedTariff()
    print(f"Customer tariff: {tariff}")
    out = Path(args.out)
    out.mkdir(exist_ok=True)

    sites = site_table()
    weather = None
    if args.real_weather:
        print("Fetching Open-Meteo weather ...")
        try:
            weather = pd.concat([fetch_open_meteo(s) for s in sites.to_dict("records")], ignore_index=True)
            now = pd.Timestamp.now(tz="UTC").floor("15min")
        except Exception as e:
            print(f"Open-Meteo failed ({e}); falling back to synthetic weather.")
    if weather is None:
        now = pd.Timestamp.now(tz="UTC").normalize()
        start = now - pd.Timedelta(days=args.days)
        weather = pd.concat([synthetic_weather(s, start, now + pd.Timedelta(days=2), seed=i)
                             for i, s in enumerate(sites.to_dict("records"))], ignore_index=True)

    # telemetry exists only up to "now"; weather beyond that is the forecast
    faults = fault_schedule(now)
    telemetry = simulate(sites, weather[weather.timestamp < now], faults)
    train_end = now.normalize() - pd.Timedelta(days=35)   # history before any injected fault

    feats = build_features(weather, sites)
    print("\nModel quality on 7 healthy holdout days:")
    print(evaluate(telemetry, feats, train_end).to_string(index=False))
    per_site = evaluate(telemetry, feats, train_end, by_site=True)
    per_site["shaded roof"] = per_site.index.isin(list(SHADING))
    print("\nPer site (ML learns each roof's shading, physics cannot):")
    print(per_site.to_string())

    model = ExpectedProductionModel().fit(telemetry[telemetry.timestamp < train_end],
                                          feats[feats.timestamp < train_end])
    expected = model.predict(feats)

    cfg = Config()
    alerts = detect_alerts(telemetry, expected, sites, cfg)
    recent = alerts[alerts.end > train_end]

    print(f"\nAlerts since {train_end:%Y-%m-%d}: {len(recent)}")
    show = ["alert_id", "site_id", "type", "severity", "detected_at", "ongoing", "lost_kwh", "lost_lei"]
    print(recent[show].to_string(index=False))

    print("\nDetection vs. injected faults:")
    hits = set()
    for f in faults:
        m = recent[(recent.site_id == f["site_id"]) & (recent.type == FAULT_TO_ALERT[f["fault"]])]
        if m.empty:
            print(f"  {f['site_id']} {f['fault']:<18} MISSED")
            continue
        hits.update(m.index)
        first = m.detected_at.min()
        delay = first - f["start"]
        print(f"  {f['site_id']} {f['fault']:<18} detected after {delay.total_seconds() / 3600:6.1f} h")
    other = recent.drop(index=list(hits))
    faulty = {f["site_id"] for f in faults}
    relabel = other[other.site_id.isin(faulty)]
    fp = other[~other.site_id.isin(faulty)]
    print(f"  extra alerts on faulty sites (other label): {len(relabel)}")
    print(f"  false positives on healthy sites: {len(fp)}")
    if len(other):
        print(other[show].to_string(index=False))

    print("\nWhen to consume (S01, next 48 h):")
    for a in consumption_advice(expected, telemetry, "S01", tariff=tariff):
        print("  " + a["text"])

    print("\nHabits learned from S01's load data (last 28 days):")
    habits = find_habits(detect_events(telemetry, "S01"))
    print(habits.to_string(index=False) if len(habits) else "  none found")
    print("\nTargeted nudges (push-notification style, savings in lei):")
    recs = habit_recommendations(habits, expected, telemetry, "S01", tariff=tariff)
    for r in recs:
        print("  " + r["text"])
    if not recs:
        print("  none - habits already run on solar or no surplus tomorrow")
    bench = peer_benchmark(telemetry, sites, "S01")
    if bench["evening_share"] is None:
        print("\nPeer benchmark: not shown (no consent, or too few consenting peers)")
    else:
        print(f"\nPeer benchmark ({bench['peers']} consenting peers): evening share "
              f"{bench['evening_share']:.0%} vs median of similar homes {bench['fleet_median']:.0%}")
    if bench["text"]:
        print("  " + bench["text"])

    dispatch = plan_dispatch(expected, telemetry, sites, "S01", tariff=tariff)
    print(f"\nBattery/injection plan for S01, next 24 h "
          f"(+{dispatch['uplift_lei']} lei vs always-inject):")
    for line in dispatch["texts"]:
        print("  " + line)
    acts = dispatch["plan"].groupby("action").size()
    print("  slots: " + ", ".join(f"{k} {v}" for k, v in acts.items()))
    dispatch["plan"].to_csv(out / "dispatch_plan.csv", index=False)

    # count only alerts that match a real (injected) fault; false alarms are reported apart
    # demo knows when each injected fault really began: measure the delay from there
    fault_start = {(f["site_id"], FAULT_TO_ALERT[f["fault"]]): f["start"] for f in faults}
    alerts["fault_start"] = [fault_start.get((a.site_id, a.type)) if i in hits else pd.NaT
                             for i, a in alerts.iterrows()]
    recent = alerts[alerts.end > train_end]
    impact = detection_impact(recent.loc[sorted(hits)], args.baseline_days, args.crew_hours)
    print(f"\nImpact - time to spot a problem and energy saved vs today "
          f"(true faults only, {len(fp)} false alarm(s) excluded):")
    for line in impact_summary(impact, args.baseline_days, args.crew_hours):
        print("  " + line)
    impact.to_csv(out / "impact.csv", index=False)

    pv = load_or_fetch(sites, fetch=args.pvgis)
    check = monthly_check(telemetry, pv)
    if len(check):
        print("\nPVGIS monthly check (actual kWh/day vs PVGIS average for the month):")
        print(check.to_string(index=False))
        check.to_csv(out / "pvgis_check.csv", index=False)
    elif args.pvgis:
        print("\nPVGIS check skipped: no network. Run once with internet to fill the cache.")

    # customer-side outputs for every site, for the dashboard
    customer = {}
    plans = []
    for sid in sites.site_id:
        hb = find_habits(detect_events(telemetry, sid))
        nudges = habit_recommendations(hb, expected, telemetry, sid, tariff=tariff)
        tips = consumption_advice(expected, telemetry, sid, tariff=tariff)
        b = peer_benchmark(telemetry, sites, sid)
        dp = plan_dispatch(expected, telemetry, sites, sid, tariff=tariff)
        if len(dp["plan"]):
            plans.append(dp["plan"].assign(site_id=sid))
        customer[sid] = {
            "habits": hb.to_dict("records"),
            "nudges": [{k: str(v) if k.endswith("local") else v for k, v in n.items()} for n in nudges],
            "tips": [t["text"] for t in tips],
            "benchmark": b,
            "dispatch_uplift_lei": dp["uplift_lei"],
            "dispatch_texts": dp["texts"],
        }
    (out / "customer.json").write_text(json.dumps(customer, indent=1, default=str))
    if plans:
        pd.concat(plans).to_csv(out / "dispatch_all.csv", index=False)

    sites.to_csv(out / "sites.csv", index=False)
    telemetry.to_csv(out / "telemetry.csv", index=False)
    expected.to_csv(out / "expected.csv", index=False)
    # for the demo only: mark which alerts match an injected fault (unknowable in production)
    alerts["matches_injected_fault"] = alerts.index.isin(sorted(hits))
    alerts.to_csv(out / "alerts.csv", index=False)
    try:
        from plots import plot_sites
        plot_sites(telemetry, expected, faults, out)
    except ImportError as e:
        print(f"(skipping plots: {e})", file=sys.stderr)
    print(f"\nWrote {out}/sites.csv, telemetry.csv, expected.csv, alerts.csv")


if __name__ == "__main__":
    main()
