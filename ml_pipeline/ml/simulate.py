"""Simulated fleet of prosumer installations, 15-minute resolution, with injected faults.

Data contract shared with backend/dashboard (one row per site per 15 min):
    timestamp    UTC, tz-aware
    site_id      str
    pv_kw        average PV production in the interval
    load_kw      average household consumption
    battery_kw   + charging / - discharging (0 if no battery)
    battery_soc  state of charge in % (NaN if no battery)
    grid_kw      + import / - export   (= load - pv + battery)
"""
import numpy as np
import pandas as pd

from .solar import solar_position, angle_of_incidence_cos, physical_pv_kw

SITES = [
    # site_id, name, lat, lon, kWp, tilt, azimuth (0 = south), battery kWh, household scale
    ("S01", "Bucuresti - Pipera",   44.51, 26.12,  8.0, 30,   0, 10.0, 1.0),
    ("S02", "Cluj-Napoca - Gheorgheni", 46.77, 23.63, 6.0, 35, -20, 0.0, 0.8),
    ("S03", "Iasi - Copou",         47.18, 27.57, 10.0, 25,  15, 13.5, 1.3),
    ("S04", "Timisoara - Giroc",    45.70, 21.24,  5.0, 40,   0, 0.0, 0.7),
    ("S05", "Constanta - Palazu",   44.21, 28.60,  9.0, 30,  -10, 10.0, 1.1),
    ("S06", "Brasov - Tractorul",   45.67, 25.62,  7.0, 35,  25, 5.0, 0.9),
    ("S07", "Craiova - Bariera",    44.33, 23.80, 12.0, 20,   0, 15.0, 1.5),
    ("S08", "Oradea - Nufarul",     47.05, 21.93,  6.5, 30,  -30, 0.0, 0.8),
]


# Local horizon shading the physics model knows nothing about (a block of flats, a tree, mountains).
# (min sun azimuth, max sun azimuth, max sun elevation, fraction of production lost)
SHADING = {
    "S01": (-180, -30, 18, 0.65),   # building to the east, mornings
    "S04": (35, 180, 20, 0.6),      # tree to the west, afternoons
    "S06": (-180, 180, 9, 0.7),     # mountain horizon in Brasov
}


def site_table() -> pd.DataFrame:
    cols = ["site_id", "name", "lat", "lon", "kwp", "tilt", "azimuth", "battery_kwh", "household"]
    df = pd.DataFrame(SITES, columns=cols)
    df["inverter_kw"] = (df["kwp"] * 0.9).round(1)
    # GDPR: comparing a household with others needs its explicit consent (in-app accept).
    # Two simulated customers said no, so they are left out of every benchmark.
    df["consent_benchmark"] = ~df.site_id.isin(["S03", "S08"])
    return df


def fault_schedule(end: pd.Timestamp) -> list:
    """Faults placed relative to the end of the data, so the demo works for any date range."""
    d = lambda days, hour=0: end.normalize() - pd.Timedelta(days=days) + pd.Timedelta(hours=hour)
    return [
        {"site_id": "S02", "fault": "soiling",        "start": d(30), "end": end,
         "note": "gradual soiling, up to -25% at the end"},
        {"site_id": "S03", "fault": "inverter_derate", "start": d(12), "end": end,
         "note": "inverter produces 30% below normal"},
        {"site_id": "S05", "fault": "battery_no_charge", "start": d(9), "end": end,
         "note": "battery stops accepting charge"},
        {"site_id": "S07", "fault": "inverter_offline", "start": d(6, 7), "end": d(5, 10),
         "note": "inverter tripped, zero production"},
        {"site_id": "S06", "fault": "comms_loss",      "start": d(4, 8), "end": d(4, 14),
         "note": "logger offline, no data"},
    ]


def _ar1(n, phi, sigma, rng):
    x = np.zeros(n)
    eps = rng.normal(0, sigma, n)
    for i in range(1, n):
        x[i] = phi * x[i - 1] + eps[i]
    return x


def _load_profile(times: pd.DatetimeIndex, scale: float, rng) -> np.ndarray:
    local = times.tz_convert("Europe/Bucharest")
    h = local.hour.values + local.minute.values / 60
    weekend = local.dayofweek.values >= 5
    g = lambda mu, s: np.exp(-0.5 * ((h - mu) / s) ** 2)
    load = (0.35
            + 0.9 * g(7.5, 1.0) * ~weekend
            + 0.6 * g(9.5, 1.5) * weekend
            + 0.7 * g(13.0, 2.0) * weekend
            + 1.5 * g(19.5, 1.8))
    load *= np.exp(rng.normal(0, 0.15, len(times)))
    # appliances: random 2 kW blocks of 30-90 minutes (oven, vacuum, ...)
    n = len(times)
    starts = np.where(rng.random(n) < 0.008)[0]
    for s in starts:
        if 6 <= h[s] <= 22:
            load[s:s + rng.integers(2, 7)] += 2.0
    # habitual appliances, the point of ml/habits.py: a washing machine most
    # evenings around 19:30 and, in larger households, an EV charged around 21:00
    dates = local.normalize()
    for day in pd.unique(dates):
        idx = np.where(dates == day)[0]
        if rng.random() < 0.6:
            k = idx[np.argmin(np.abs(h[idx] - rng.normal(19.5, 0.4)))]
            load[k:k + rng.integers(4, 7)] += 2.1
        if scale >= 1.0 and rng.random() < 0.45:
            k = idx[np.argmin(np.abs(h[idx] - rng.normal(21.0, 0.5)))]
            load[k:k + rng.integers(8, 13)] += 3.5
    return load * scale


def simulate(sites: pd.DataFrame, weather: pd.DataFrame, faults: list, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    out = []
    for _, s in sites.iterrows():
        w = weather[weather.site_id == s.site_id].sort_values("timestamp").reset_index(drop=True)
        t = pd.DatetimeIndex(w.timestamp)
        n = len(w)

        # what the panel really sees differs from the weather model (local clouds, model error)
        local_err = np.exp(_ar1(n, 0.9, 0.04, rng))
        gti_true = w.gti.values * local_err

        cos_z, elev, sun_az = solar_position(t, s.lat, s.lon)
        cos_inc = angle_of_incidence_cos(cos_z, sun_az, s.tilt, s.azimuth)
        iam = 1 - 0.05 * (1 / np.clip(cos_inc, 0.1, 1) - 1)        # reflection losses at low sun
        low_light = 1 - 0.06 * np.exp(-gti_true / 120)              # efficiency drops in dim light
        true_pr = rng.uniform(0.80, 0.88)
        pv = physical_pv_kw(gti_true, w.temp_c.values, s.kwp, pr=true_pr,
                            gamma=-0.0037, inverter_kw=s.inverter_kw)
        pv = pv * np.clip(iam, 0.6, 1) * low_light
        if s.site_id in SHADING:
            az0, az1, el_max, loss = SHADING[s.site_id]
            shaded = (sun_az >= az0) & (sun_az <= az1) & (elev <= el_max)
            pv[shaded] *= 1 - loss
        pv *= 1 + rng.normal(0, 0.015, n)
        pv = np.clip(pv, 0, None)

        for f in faults:
            if f["site_id"] != s.site_id:
                continue
            m = (t >= f["start"]) & (t < f["end"])
            if f["fault"] == "inverter_derate":
                pv[m] *= 0.70
            elif f["fault"] == "inverter_offline":
                pv[m] = 0.0
            elif f["fault"] == "soiling":
                frac = (t[m] - f["start"]) / (f["end"] - f["start"])
                pv[m] *= 1 - 0.25 * np.asarray(frac)

        load = _load_profile(t, s.household, rng)

        # battery: charge from surplus, discharge to cover load
        cap = s.battery_kwh
        bat_kw = np.zeros(n)
        soc = np.full(n, np.nan)
        if cap > 0:
            p_max, e, dt = cap / 2, 0.95, 0.25
            no_charge = np.zeros(n, dtype=bool)
            for f in faults:
                if f["site_id"] == s.site_id and f["fault"] == "battery_no_charge":
                    no_charge |= (t >= f["start"]) & (t < f["end"])
            energy = 0.5 * cap
            for i in range(n):
                net = pv[i] - load[i]
                if net > 0 and not no_charge[i]:
                    p = min(net, p_max, (cap - energy) / (dt * e))
                elif net < 0:
                    p = -min(-net, p_max, (energy - 0.1 * cap) * e / dt)
                else:
                    p = 0.0
                energy += p * dt * (e if p > 0 else 1 / e)
                bat_kw[i] = p
                soc[i] = 100 * energy / cap

        out.append(pd.DataFrame({
            "timestamp": t, "site_id": s.site_id,
            "pv_kw": pv.round(3), "load_kw": load.round(3),
            "battery_kw": bat_kw.round(3), "battery_soc": np.round(soc, 1),
            "grid_kw": (load - pv + bat_kw).round(3),
        }))

    df = pd.concat(out, ignore_index=True)
    for f in faults:   # comms loss = rows simply missing
        if f["fault"] == "comms_loss":
            m = (df.site_id == f["site_id"]) & (df.timestamp >= f["start"]) & (df.timestamp < f["end"])
            df = df[~m]
    return df.reset_index(drop=True)
