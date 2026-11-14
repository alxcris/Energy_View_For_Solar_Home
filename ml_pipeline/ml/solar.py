"""Solar geometry and a simple physical PV model.

Used by the synthetic weather generator, the simulator and as a feature for the ML model.
All timestamps are UTC (tz-aware pandas DatetimeIndex).
"""
import numpy as np
import pandas as pd


def solar_position(times: pd.DatetimeIndex, lat: float, lon: float):
    """Return (cos_zenith, elevation_deg, azimuth_deg) for each timestamp.

    Azimuth uses the Open-Meteo convention: 0 = south, -90 = east, +90 = west.
    Accuracy of ~1 degree, which is plenty for a 15-minute PV model.
    """
    doy = times.dayofyear.values
    hour = times.hour.values + times.minute.values / 60.0
    b = 2 * np.pi * (doy - 81) / 364.0
    eot_min = 9.87 * np.sin(2 * b) - 7.53 * np.cos(b) - 1.5 * np.sin(b)
    solar_time = hour + lon / 15.0 + eot_min / 60.0
    hour_angle = np.radians(15.0 * (solar_time - 12.0))

    decl = np.radians(23.45) * np.sin(2 * np.pi * (284 + doy) / 365.0)
    phi = np.radians(lat)

    cos_z = np.sin(phi) * np.sin(decl) + np.cos(phi) * np.cos(decl) * np.cos(hour_angle)
    cos_z = np.clip(cos_z, -1, 1)
    elev = np.degrees(np.arcsin(cos_z))

    # azimuth measured from south, positive towards west
    az = np.degrees(np.arctan2(
        np.sin(hour_angle),
        np.cos(hour_angle) * np.sin(phi) - np.tan(decl) * np.cos(phi),
    ))
    return cos_z, elev, az


def angle_of_incidence_cos(cos_z, sun_az_deg, tilt_deg, panel_az_deg):
    """cos of the angle between the sun and the panel normal."""
    z = np.arccos(np.clip(cos_z, -1, 1))
    t = np.radians(tilt_deg)
    return (np.cos(z) * np.cos(t)
            + np.sin(z) * np.sin(t) * np.cos(np.radians(sun_az_deg - panel_az_deg)))


def physical_pv_kw(gti, temp_c, kwp, pr=0.85, gamma=-0.004, inverter_kw=None):
    """Classic PVWatts-style estimate: kWp * irradiance/1000 * PR * temperature derating."""
    gti = np.clip(np.asarray(gti, dtype=float), 0, None)
    t_cell = np.asarray(temp_c, dtype=float) + 0.03 * gti
    p = kwp * gti / 1000.0 * pr * (1 + gamma * (t_cell - 25.0))
    p = np.clip(p, 0, None)
    if inverter_kw is not None:
        p = np.minimum(p, inverter_kw)
    return p
