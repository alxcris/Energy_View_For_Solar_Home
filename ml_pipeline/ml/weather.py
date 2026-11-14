"""Weather input: Open-Meteo (real, free, no API key) or a synthetic generator (offline).

Both return the same 15-minute DataFrame per site:
    timestamp (UTC), site_id, gti (W/m2 on the panel plane), ghi, temp_c, wind_ms
"""
import json
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd

from .solar import solar_position, angle_of_incidence_cos

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


def fetch_open_meteo(site: dict, past_days: int = 92, forecast_days: int = 3) -> pd.DataFrame:
    """15-minute weather for one site: the last `past_days` plus `forecast_days` ahead.

    Open-Meteo azimuth convention matches ours (0 = south, -90 = east, 90 = west).
    """
    params = {
        "latitude": site["lat"],
        "longitude": site["lon"],
        "minutely_15": "global_tilted_irradiance,shortwave_radiation,temperature_2m,wind_speed_10m",
        "tilt": site["tilt"],
        "azimuth": site["azimuth"],
        "past_days": past_days,
        "forecast_days": forecast_days,
        "wind_speed_unit": "ms",
        "timezone": "GMT",
    }
    url = OPEN_METEO_URL + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as resp:
        data = json.load(resp)
    m = data["minutely_15"]
    df = pd.DataFrame({
        "timestamp": pd.to_datetime(m["time"]).tz_localize("UTC"),
        "gti": m["global_tilted_irradiance"],
        "ghi": m["shortwave_radiation"],
        "temp_c": m["temperature_2m"],
        "wind_ms": m["wind_speed_10m"],
    })
    df["site_id"] = site["site_id"]
    return df.fillna({"gti": 0, "ghi": 0}).ffill()


def synthetic_weather(site: dict, start, end, seed: int = 0) -> pd.DataFrame:
    """Plausible 15-minute weather: clear-sky geometry x a random cloud process."""
    rng = np.random.default_rng(seed)
    times = pd.date_range(start, end, freq="15min", inclusive="left", tz="UTC")
    n = len(times)
    cos_z, elev, sun_az = solar_position(times, site["lat"], site["lon"])
    cz = np.clip(cos_z, 0.0, None)

    # Haurwitz clear-sky GHI
    with np.errstate(divide="ignore", over="ignore"):
        ghi_clear = np.where(cz > 0.01, 1098 * cz * np.exp(-0.057 / np.maximum(cz, 0.01)), 0.0)

    # Cloud fraction: daily regime + AR(1) intraday wiggle, all in [0, 1]
    days = times.normalize()
    uniq = days.unique()
    regime = pd.Series(rng.beta(0.7, 0.9, len(uniq)), index=uniq)
    cloud = regime.reindex(days).values
    ar = np.zeros(n)
    for i in range(1, n):
        ar[i] = 0.97 * ar[i - 1] + rng.normal(0, 0.06)
    cloud = np.clip(cloud + ar, 0, 1)

    ghi = ghi_clear * (1 - 0.75 * cloud ** 3.4)          # Kasten-Czeplak
    dhi = ghi * (0.2 + 0.75 * cloud)
    bhi = ghi - dhi
    dni = np.where(cz > 0.05, bhi / np.maximum(cz, 0.05), 0.0)
    cos_inc = np.clip(angle_of_incidence_cos(cos_z, sun_az, site["tilt"], site["azimuth"]), 0, None)
    beta = np.radians(site["tilt"])
    gti = dni * cos_inc + dhi * (1 + np.cos(beta)) / 2 + ghi * 0.2 * (1 - np.cos(beta)) / 2
    gti = np.where(cz > 0, gti, 0.0)

    doy = times.dayofyear.values
    hour = times.hour.values + times.minute.values / 60 + site["lon"] / 15
    temp = (12 + 11 * np.cos(2 * np.pi * (doy - 200) / 365)        # seasonal
            + 5 * np.cos(2 * np.pi * (hour - 15) / 24) * (1 - 0.6 * cloud)  # diurnal
            + rng.normal(0, 0.8, n))
    wind = np.clip(2.5 + 2 * cloud + rng.normal(0, 1, n), 0, None)

    return pd.DataFrame({
        "timestamp": times, "site_id": site["site_id"],
        "gti": gti, "ghi": ghi, "temp_c": temp, "wind_ms": wind,
    })
