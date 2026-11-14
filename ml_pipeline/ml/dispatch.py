"""Step 3 of the mentor's framing (centralize -> compare -> decide -> act):
decide, for every 15-min slot of the next day, what to do with the energy -
charge the battery, inject into the grid, hold back or discharge.

His live demo showed a site that decided NOT to inject and to absorb from the
grid instead, because at that hour the day-ahead price made injection
worthless. This module reproduces that decision and prices it in lei.

Explainable rules, not a black box: every slot gets an action and a reason.
"""
import numpy as np
import pandas as pd

from .advice import load_forecast
from .tariffs import as_tariff

TZ = "Europe/Bucharest"


def day_ahead_price(times: pd.DatetimeIndex) -> np.ndarray:
    """Synthetic OPCOM-like day-ahead curve in lei/kWh: morning and evening
    peaks, a deep midday dip on sunny/weekend days that can touch zero -
    the moment when injecting earns nothing. Swap for the real OPCOM feed."""
    local = times.tz_convert(TZ)
    h = local.hour.values + local.minute.values / 60
    weekend = (local.dayofweek.values >= 5).astype(float)
    g = lambda mu, s: np.exp(-0.5 * ((h - mu) / s) ** 2)
    p = 0.55 + 0.45 * g(20, 1.5) + 0.25 * g(8, 1.2) - (0.50 + 0.12 * weekend) * g(13.5, 1.8)
    return np.round(p, 3)


def plan_dispatch(expected: pd.DataFrame, telemetry: pd.DataFrame, sites: pd.DataFrame,
                  site_id: str, hours: int = 24, tariff=None,
                  eff: float = 0.95) -> dict:
    """Greedy, explainable plan for the next `hours`. Returns the per-slot plan,
    the lei gained vs. the naive policy (always inject surplus, never plan the
    battery) and short texts for the dashboard."""
    s = sites[sites.site_id == site_id].iloc[0]
    cap, p_max = float(s.battery_kwh), float(s.battery_kwh) / 2
    tel = telemetry[telemetry.site_id == site_id]
    now = tel.timestamp.max()
    fut = expected[(expected.site_id == site_id) & (expected.timestamp > now)
                   & (expected.timestamp <= now + pd.Timedelta(hours=hours))].sort_values("timestamp")
    if fut.empty:
        return {"plan": pd.DataFrame(), "uplift_lei": 0.0, "texts": []}

    t = pd.DatetimeIndex(fut.timestamp)
    pv = fut.expected_kw.values
    load = load_forecast(telemetry, site_id, t)
    price = day_ahead_price(t)
    retail = as_tariff(tariff).price(t)          # what the customer pays per kWh, slot by slot
    dt = 0.25
    # charging is worth it when the energy, discharged later against the most expensive
    # retail hour still ahead, beats selling it right now
    later_retail = np.maximum.accumulate(retail[::-1])[::-1]
    charge_below = later_retail * eff * eff

    soc = tel.battery_soc.dropna()
    energy = (float(soc.iloc[-1]) / 100 * cap) if cap > 0 and len(soc) else 0.5 * cap
    floor = 0.1 * cap

    rows, smart_lei, naive_lei = [], 0.0, 0.0
    naive_energy = energy
    for i in range(len(t)):
        surplus = pv[i] - load[i]
        e = abs(surplus) * dt
        if surplus >= 0:
            naive_lei += e * price[i]                       # naive: inject everything, any price
            charge = 0.0
            if cap > 0 and price[i] < charge_below[i] and energy < cap:
                charge = min(surplus, p_max, (cap - energy) / (dt * eff))
                energy += charge * dt * eff
            inject = max(surplus - charge, 0.0)
            if price[i] <= 0.02:
                action, reason = ("charge" if charge > 0 else "hold"), "price ~0, injection earns nothing"
                inject = 0.0                                 # the Mogosoaia decision
            elif charge > 0:
                action, reason = "charge", f"store now, discharge at retail {later_retail[i]:.2f} lei later"
            else:
                action, reason = "inject", f"price {price[i]:.2f} lei/kWh beats storing"
            smart_lei += inject * dt * price[i]
        else:
            need = -surplus
            if naive_energy > floor:                         # naive still uses the battery passively
                d = min(need, p_max, (naive_energy - floor) * eff / dt)
                naive_energy -= d * dt / eff
                naive_lei -= (need - d) * dt * retail[i]
            else:
                naive_lei -= e * retail[i]
            disc = 0.0
            if cap > 0 and energy > floor:
                disc = min(need, p_max, (energy - floor) * eff / dt)
                energy -= disc * dt / eff
            smart_lei -= (need - disc) * dt * retail[i]
            action = "discharge" if disc > 0 else "import"
            reason = "cover the load from the battery" if disc > 0 else "battery empty, buy from grid"
        rows.append({"timestamp_local": t[i].tz_convert(TZ), "pv_kw": round(pv[i], 2),
                     "load_kw": round(load[i], 2), "price_lei_kwh": price[i],
                     "action": action, "reason": reason,
                     "battery_soc": round(100 * energy / cap, 1) if cap else np.nan})

    plan = pd.DataFrame(rows)
    texts = []
    zero = plan[(plan.action.isin(["hold", "charge"])) & (plan.price_lei_kwh <= 0.02)]
    if len(zero):
        z = zero.iloc[0]
        texts.append(f"{z.timestamp_local:%a %H:%M}: day-ahead price ~0 lei/kWh - "
                     "do not inject, charge the battery instead.")
    peak = plan[plan.action == "inject"].sort_values("price_lei_kwh", ascending=False)
    if len(peak):
        p = peak.iloc[0]
        texts.append(f"{p.timestamp_local:%a %H:%M}: inject at {p.price_lei_kwh:.2f} lei/kWh, "
                     "the best price of the day.")
    return {"plan": plan, "uplift_lei": round(smart_lei - naive_lei, 2), "texts": texts}
