"""What sits behind the inverter: the strings of panels, and where the kWh go.

The telemetry gives one production figure per installation. A customer looking
at a screen asks a narrower question - "is every panel working?" - and an O&M
operator asks "which part is down?". This module splits a site into the strings
its kWp implies and spreads the measured production over them, so the shortfall
shows up where the fault is instead of being hidden in one number.

The split is deterministic (same site, same strings, every run) and marked as
derived wherever it is shown: the inverters in this dataset report one total,
so the per-string numbers are an estimate, not a second measurement.
"""

from __future__ import annotations

import hashlib

import pandas as pd

PANEL_WATT = 450  # a current residential panel

# faults that show up as a part of the array producing less than the weather allows
ARRAY_FAULTS = {"gradual_degradation", "sudden_underperformance", "string_offline",
                "inverter_offline", "shading", "soiling"}


def _unit(seed: str) -> float:
    """A stable number in [0, 1) from a string - same site, same layout, every run."""
    return int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def orientation(azimuth: float) -> str:
    if abs(azimuth) <= 12:
        return "south"
    return "south-east" if azimuth < 0 else "south-west"


def strings(site: dict) -> list[dict]:
    """The strings of an installation, derived from its installed power."""
    kwp = float(site.get("kwp") or 0)
    if kwp <= 0:
        return []
    count = 1 if kwp <= 4 else 2 if kwp <= 8.5 else 3
    panels_total = max(count, round(kwp * 1000 / PANEL_WATT))
    base, extra = divmod(panels_total, count)
    facing = orientation(float(site.get("azimuth") or 0))
    out = []
    for i in range(count):
        panels = base + (1 if i < extra else 0)
        out.append({
            "id": f"{site.get('site_id', 'S')}-{chr(65 + i)}",
            "name": f"String {chr(65 + i)}",
            "panels": panels,
            "kwp": round(panels * PANEL_WATT / 1000, 2),
            "facing": facing if i == 0 or count < 3 else f"{facing} (lower row)",
        })
    return out


def string_layout(site: dict, fault_type: str | None = None) -> dict:
    """The fixed part of the array: each string's share, its stable jitter and
    which one carries a fault. Python and the browser both work from this, so
    the live view and the server-rendered pages cannot drift apart."""
    rows = strings(site)
    if not rows:
        return {"strings": [], "array_fault": False}
    total = sum(r["kwp"] for r in rows) or 1.0
    faulty_idx = min(int(_unit(str(site.get("site_id", "")) + "fault") * len(rows)),
                     len(rows) - 1)
    out = [{**r, "share": r["kwp"] / total,
            "jitter": round(0.97 + 0.06 * _unit(r["id"]), 4),
            "faulty": i == faulty_idx} for i, r in enumerate(rows)]
    return {"strings": out,
            "array_fault": bool(fault_type and fault_type in ARRAY_FAULTS)}


def live_strings(site: dict, pv_kw: float, expected_kw: float | None = None,
                 fault_type: str | None = None) -> list[dict]:
    """Each string with what it produces now, what it should produce, and its state.

    When the site has an array fault, most of the missing power is put on one
    string - that is what a real string-level monitor would show, and it is what
    sends a technician to the right place.
    """
    layout = string_layout(site, fault_type)["strings"]
    if not layout:
        return []
    pv_kw = max(0.0, float(pv_kw or 0))
    expected = float(expected_kw) if expected_kw is not None and expected_kw == expected_kw else None

    deficit = max(0.0, (expected or 0) - pv_kw) if expected else 0.0
    array_fault = bool(fault_type and fault_type in ARRAY_FAULTS) and deficit > 0.05

    rows = []
    for i, s in enumerate(layout):
        share = s["share"]
        exp_kw = (expected or pv_kw) * share
        if array_fault:
            # the faulty string carries most of the loss, the healthy ones a little
            loss = deficit * (0.78 if s["faulty"] else 0.22 / max(1, len(layout) - 1))
            cur = max(0.0, exp_kw - loss)
        else:
            cur = pv_kw * share * s["jitter"]
        ratio = cur / exp_kw if exp_kw > 0.05 else None

        if exp_kw <= 0.05:
            state, note = "idle", "no sun on it right now"
        elif ratio is None or ratio >= 0.92:
            state, note = "ok", "producing as expected"
        elif ratio >= 0.75:
            state, note = "watch", f"{(1 - ratio) * 100:.0f}% below expected"
        else:
            state, note = "alarm", f"only {ratio * 100:.0f}% of what the weather allows"
        rows.append({**s, "current_kw": round(cur, 2), "expected_kw": round(exp_kw, 2),
                     "ratio": ratio, "state": state, "note": note})
    return rows


def array_summary(rows: list[dict]) -> dict:
    """One line about the whole array, for a KPI card or a badge."""
    if not rows:
        return {"state": "idle", "text": "no array registered", "working": 0, "total": 0}
    total = len(rows)
    bad = [r for r in rows if r["state"] == "alarm"]
    watch = [r for r in rows if r["state"] == "watch"]
    if all(r["state"] == "idle" for r in rows):
        return {"state": "idle", "text": "the array is resting", "working": 0, "total": total}
    if bad:
        return {"state": "alarm", "text": f"{bad[0]['name']} is down", "working": total - len(bad),
                "total": total}
    if watch:
        return {"state": "watch", "text": f"{watch[0]['name']} is lagging",
                "working": total - len(watch), "total": total}
    return {"state": "ok", "text": "every string is producing", "working": total, "total": total}


def consumption_split(hourly: pd.DataFrame, customer: dict | None = None) -> list[dict]:
    """Roughly where a day's kWh go: the always-on base, the habits we recognised, the rest.

    The base load is the quietest hour of the night held for 24 hours; the
    habits come from the ML pipeline (customer.json). Anything left over is
    everyday use we cannot name yet.
    """
    if hourly is None or hourly.empty:
        return []
    total = float(hourly["avg_power_kw"].sum())  # one day, hourly averages = kWh
    if total <= 0:
        return []
    base = float(hourly["avg_power_kw"].min()) * 24
    rows = [{"label": "Always on (fridge, router, standby)", "kwh": round(base, 1),
             "series": 3, "hint": ""}]
    named = 0.0
    for habit in (customer or {}).get("habits", [])[:3]:
        kwh = float(habit.get("kwh_per_event", 0)) * max(1, int(habit.get("events", 1))) / 14
        if kwh < 0.1:
            continue
        named += kwh
        rows.append({"label": (habit.get("label") or "recognised habit").capitalize(),
                     "kwh": round(kwh, 1), "series": 1 + len(rows) % 5,
                     "hint": ""})
    rest = max(0.0, total - base - named)
    rows.append({"label": "Everything else", "kwh": round(rest, 1), "series": 0,
                 "hint": "cooking, lights, everyday use"})
    for r in rows:
        r["share"] = r["kwh"] / total if total else 0
    return [r for r in rows if r["kwh"] > 0.05]
