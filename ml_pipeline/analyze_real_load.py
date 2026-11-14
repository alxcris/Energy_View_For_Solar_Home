"""Analysis of the real load curve from the mentor (PPC), one consumer, Oct 2025 - Sep 2026.

    python analyze_real_load.py                      # uses data/curba_sarcina_test.xlsx
    python analyze_real_load.py path/to/file.xlsx    # any file in the same distributor format

Writes to out/: real_load.csv (contract format), real_drops.csv, real_forecast.csv,
real_pv_what_if.csv and three plots for the slides.
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from ml.load_analysis import (daily_kwh, find_drops, forecast_eval, growth,
                              operating_schedule, pv_what_if, seasonality)
from ml.real_data import load_curve

TZ = "Europe/Bucharest"


def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "data/curba_sarcina_test.xlsx")
    out = Path("out")
    out.mkdir(exist_ok=True)
    df = load_curve(path)
    loc = df.timestamp.dt.tz_convert(TZ)
    print(f"Loaded {len(df)} rows, {loc.min():%Y-%m-%d} to {loc.max():%Y-%m-%d} "
          f"({df.attrs['resolution']})")
    print(f"Total {df.load_kw.sum() * 0.25 / 1000:.0f} MWh, average {df.load_kw.mean():.0f} kW, "
          f"peak {df.load_kw.max():.0f} kW")

    sch = operating_schedule(df)
    print("\n1) When the site runs (hours above 35% of peak, normal weeks):")
    for day, hrs in sch["hours"].items():
        print(f"   {day}: {hrs}")
    print(f"   load when stopped (Sundays): ~{sch['base_kw']} kW, peak {sch['peak_kw']} kW")

    print("\n2) Growth - the site is ramping up, so baselines must be rolling, not annual:")
    print(growth(df).to_string())

    print("\n   Median kW by month and block (summer vs winter, day vs night):")
    print(seasonality(df).to_string())

    drops = find_drops(df)
    print(f"\n3) Drops: {len(drops)} working days below 50% of their expected level")
    if len(drops):
        for _, g in drops.groupby("period"):
            first, last = g.date.iloc[0], g.date.iloc[-1]
            span = f"{first:%d %b}" + (f" - {last:%d %b}" if last != first else "")
            reasons = "; ".join(dict.fromkeys(g.explanation))
            print(f"   {span:<16} {reasons}")

    fc = forecast_eval(df)
    print(f"\n4) Day-ahead hourly load forecast, tested on {fc['test_from']} onwards:")
    print(fc["table"].to_string(index=False))
    print("   (normal days = excluding the unannounced stops above; those need the client's"
          " calendar, not a better model)")

    pv = pv_what_if(df)
    print("\n5) What if this client had rooftop PV (synthetic weather, Bucharest):")
    print(pv.to_string(index=False))

    df.to_csv(out / "real_load.csv", index=False)
    drops.to_csv(out / "real_drops.csv", index=False)
    fc["test"][["timestamp", "load_kw", "gbm", "naive_week"]].to_csv(out / "real_forecast.csv",
                                                                       index=False)
    pv.to_csv(out / "real_pv_what_if.csv", index=False)
    plots(df, drops, fc, out)
    print(f"\nWrote {out}/real_*.csv and real_heatmap.png, real_daily_drops.png, real_forecast.png")


def plots(df, drops, fc, out):
    loc = df.timestamp.dt.tz_convert(TZ)
    # 1) heatmap: one row per day, one column per hour - shifts, weekends, holidays, ramp-up
    h = df.assign(day=loc.dt.date, hour=loc.dt.hour).groupby(["day", "hour"]).load_kw.mean().unstack()
    fig, ax = plt.subplots(figsize=(7, 9))
    im = ax.imshow(h.values, aspect="auto", cmap="viridis", interpolation="nearest")
    ax.set_xticks(range(0, 24, 3))
    ax.set_xticklabels([f"{x:02d}" for x in range(0, 24, 3)])
    months = pd.to_datetime(pd.Series(h.index))
    first = months.groupby(months.dt.to_period("M")).idxmin()
    ax.set_yticks(first.values)
    ax.set_yticklabels([months[i].strftime("%b %Y") for i in first.values])
    ax.set_xlabel("hour of day (local)")
    ax.set_title("Real consumer load, kW (one row per day)")
    fig.colorbar(im, ax=ax, label="kW")
    fig.tight_layout()
    fig.savefig(out / "real_heatmap.png", dpi=150)
    plt.close(fig)

    # 2) daily energy with the drops marked and labelled by cause
    d = daily_kwh(df)
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.plot(d.index, d.values / 1000, lw=0.8, color="0.4")
    if len(drops):
        dd = pd.to_datetime(drops.date)
        kinds = drops.explanation.str.split(" ").str[0].map(
            {"legal": "legal holiday", "bridge": "bridge day", "winter": "winter break"}
        ).fillna("ask the client")
        colors = {"legal holiday": "#2a7", "bridge day": "#7b5", "winter break": "#38c",
                  "ask the client": "#d43"}
        for k, c in colors.items():
            m = (kinds == k).values
            if m.any():
                ax.scatter(dd[m], drops.kwh[m] / 1000, color=c, s=22, zorder=3, label=k)
        ax.legend(frameon=False, fontsize=8)
    ax.set_ylabel("MWh per day")
    ax.set_title("Daily consumption and the drops we explained")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    fig.savefig(out / "real_daily_drops.png", dpi=150)
    plt.close(fig)

    # 3) forecast vs actual, two test weeks
    te = fc["test"]
    t0 = te.timestamp.min() + pd.Timedelta(days=14)
    w = te[(te.timestamp >= t0) & (te.timestamp < t0 + pd.Timedelta(days=14))]
    wl = w.timestamp.dt.tz_convert(TZ)
    fig, ax = plt.subplots(figsize=(11, 3.6))
    ax.plot(wl, w.load_kw, color="0.2", lw=1.2, label="actual")
    ax.plot(wl, w.gbm, color="#38c", lw=1.2, label="our day-ahead forecast")
    ax.plot(wl, w.naive_week, color="#d43", lw=0.8, ls="--", label="same hour last week")
    ax.set_ylabel("kW")
    ax.legend(frameon=False, fontsize=8, ncol=3)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    fig.savefig(out / "real_forecast.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    main()
