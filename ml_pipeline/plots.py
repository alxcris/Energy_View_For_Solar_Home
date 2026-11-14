"""Expected vs. actual daily energy for every faulty site, for the slides."""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


def _daily(telemetry, expected):
    d = expected.merge(telemetry, on=["timestamp", "site_id"], how="inner")
    d["date"] = d.timestamp.dt.tz_convert("Europe/Bucharest").dt.date
    d["surplus"] = (d.pv_kw - d.load_kw).clip(lower=0)
    d["stored"] = d.battery_kw.clip(lower=0)
    g = d.groupby(["site_id", "date"])
    daily = g[["expected_kw", "pv_kw", "surplus", "stored"]].sum() * 0.25
    daily["n"] = g.size()
    return daily


def plot_sites(telemetry, expected, faults, out, days=40):
    daily = _daily(telemetry, expected)
    ids = sorted({f["site_id"] for f in faults if f["fault"] != "comms_loss"})
    fig, axes = plt.subplots(len(ids), 1, figsize=(10, 2.6 * len(ids)), sharex=True)
    for ax, sid in zip(axes, ids):
        g = daily.loc[sid]
        g = g[g.n >= 90].tail(days)                       # complete days only
        x = pd.to_datetime(g.index) + pd.Timedelta(hours=12)
        f = next(f for f in faults if f["site_id"] == sid)
        if f["fault"] == "battery_no_charge":
            ax.plot(x, g.surplus, color="#888", lw=1.5, label="solar surplus")
            ax.plot(x, g.stored, color="#1971c2", lw=1.5, label="stored in battery")
            ax.legend(frameon=False, fontsize=9, loc="upper left")
        else:
            ax.plot(x, g.expected_kw, color="#888", lw=1.5, label="expected (from weather)")
            ax.plot(x, g.pv_kw, color="#d9480f", lw=1.5, label="actual")
        loc = lambda ts: ts.tz_convert("Europe/Bucharest").tz_localize(None)
        ax.axvspan(loc(f["start"]), min(loc(f["end"]), x.max() + pd.Timedelta(hours=12)),
                   color="#ffd8a8", alpha=0.5, lw=0)
        ax.set_title(f"{sid}: {f['note']}", fontsize=10, loc="left")
        ax.set_ylabel("kWh / day")
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].legend(frameon=False, fontsize=9, loc="upper left")
    fig.tight_layout()
    fig.savefig(out / "faults_daily.png", dpi=130)
    plt.close(fig)
