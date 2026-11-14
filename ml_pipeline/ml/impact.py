"""The number the brief asks for: "a visible reduction in wasted energy, or in the time it
takes to spot a problem". Compares each alert as we detect it with how the same fault plays
out today.

Two inputs come from the O&M interviews, not from us, and are parameters on purpose:
    baseline_days  how many days after a fault starts O&M finds out today
    crew_hours     how long from "we know" to "fixed on site"
Until the team has the real numbers, the defaults are marked as ASSUMPTIONS in every output.

The availability KPI is the one PPC guarantees its clients (90% in the mentor's words).
"""
import pandas as pd

from .tariffs import RETAIL_LEI_KWH

ASSUMED_BASELINE_DAYS = 7.0
ASSUMED_CREW_HOURS = 24.0


def detection_impact(alerts: pd.DataFrame, baseline_days: float = ASSUMED_BASELINE_DAYS,
                     crew_hours: float = ASSUMED_CREW_HOURS, price_lei_kwh: float = RETAIL_LEI_KWH,
                     month_days: float = 30.0) -> pd.DataFrame:
    rows = []
    for _, a in alerts.iterrows():
        if a.type == "comms_loss":
            continue                                  # no energy lost, nothing to compare
        start, end, det = (pd.Timestamp(a.start), pd.Timestamp(a.end), pd.Timestamp(a.detected_at))
        observed_days = max((end - start).total_seconds() / 86400, 1 / 24)
        loss_per_day = a.lost_kwh / observed_days
        # delay is measured from when the fault really began if known (demo: injected
        # faults), else from when the anomaly became visible in the data
        began = pd.Timestamp(a.fault_start) if "fault_start" in a and pd.notna(a.fault_start) else start
        ours_h = max((det - began).total_seconds() / 3600, 0.0)
        days_today = baseline_days + crew_hours / 24
        days_ours = (ours_h + crew_hours) / 24
        kwh_today, kwh_ours = loss_per_day * days_today, loss_per_day * days_ours
        row = {
            "site_id": a.site_id, "type": a.type,
            "detected_after_h_ours": round(ours_h, 1),
            "detected_after_h_today": round(baseline_days * 24, 1),
            "lost_kwh_today": round(kwh_today, 1), "lost_kwh_ours": round(kwh_ours, 1),
            # a slow fault we flag later than today's baseline saves nothing (never negative)
            "saved_kwh": round(max(kwh_today - kwh_ours, 0.0), 1),
            "saved_lei": round(max(kwh_today - kwh_ours, 0.0) * price_lei_kwh, 1),
            "faster_than_today": ours_h < baseline_days * 24,
        }
        if a.type == "inverter_offline":              # SLA: share of the month the site works
            row["availability_today_%"] = round(100 * max(0, 1 - days_today / month_days), 1)
            row["availability_ours_%"] = round(100 * max(0, 1 - days_ours / month_days), 1)
        rows.append(row)
    return pd.DataFrame(rows)


def summary(impact: pd.DataFrame, baseline_days: float, crew_hours: float) -> list:
    if impact.empty:
        return ["No faults to compare."]
    assumed = (baseline_days == ASSUMED_BASELINE_DAYS and crew_hours == ASSUMED_CREW_HOURS)
    tag = " (ASSUMED baseline - replace with the O&M interview answer)" if assumed else ""
    med = impact.detected_after_h_ours.median()
    lines = [
        f"Time to spot a problem: median {med:.0f} h with us vs {baseline_days * 24:.0f} h today{tag}.",
        *[f"Slower than today's baseline: {r.type} on {r.site_id} ({r.detected_after_h_ours:.0f} h) - "
          f"slow drifts are flagged late on purpose to avoid false alarms on cloudy days."
          for r in impact[~impact.faster_than_today].itertuples()],
        f"Energy saved on these {len(impact)} faults: {impact.saved_kwh.sum():.0f} kWh "
        f"(~{impact.saved_lei.sum():.0f} lei).",
    ]
    off = impact.dropna(subset=["availability_ours_%"]) if "availability_ours_%" in impact else []
    if len(off):
        r = off.iloc[0]
        lines.append(f"Inverter trip on {r.site_id}: monthly availability "
                     f"{r['availability_today_%']:.0f}% today vs {r['availability_ours_%']:.0f}% "
                     f"with us (PPC guarantees 90%).")
    return lines
