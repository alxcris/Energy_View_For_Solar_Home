"""Expected PV production from weather: physics baseline + gradient boosting correction.

One pooled model for the whole fleet (target = kW per kWp, so sites of any size share it),
then a per-site calibration factor learned on healthy history (captures each site's own losses).
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from .solar import solar_position, angle_of_incidence_cos, physical_pv_kw

FEATURES = ["site_code", "gti", "ghi", "temp_c", "wind_ms", "elev", "sun_az", "cos_inc",
            "phys_per_kwp", "tilt", "azimuth", "clip_ratio"]


def build_features(weather: pd.DataFrame, sites: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for code, (_, s) in enumerate(sites.iterrows()):
        w = weather[weather.site_id == s.site_id].copy()
        t = pd.DatetimeIndex(w.timestamp)
        cos_z, elev, sun_az = solar_position(t, s.lat, s.lon)
        w["elev"], w["sun_az"] = elev, sun_az
        w["site_code"] = code   # lets the model learn each roof's own shading
        w["cos_inc"] = angle_of_incidence_cos(cos_z, sun_az, s.tilt, s.azimuth)
        w["phys_per_kwp"] = physical_pv_kw(w.gti, w.temp_c, 1.0)
        w["tilt"], w["azimuth"] = s.tilt, s.azimuth
        w["kwp"], w["inverter_kw"] = s.kwp, s.inverter_kw
        w["clip_ratio"] = s.inverter_kw / s.kwp
        parts.append(w)
    return pd.concat(parts, ignore_index=True)


class ExpectedProductionModel:
    def __init__(self, daylight_elev: float = -1.0):
        self.daylight_elev = daylight_elev
        self.gbm = HistGradientBoostingRegressor(
            max_iter=400, learning_rate=0.05, max_leaf_nodes=31,
            l2_regularization=1.0, categorical_features=[0], random_state=0)
        self.calib = {}       # site_id -> ML calibration factor
        self.phys_calib = {}  # site_id -> physics calibration factor (fair baseline)

    def fit(self, telemetry: pd.DataFrame, feats: pd.DataFrame):
        d = feats.merge(telemetry[["timestamp", "site_id", "pv_kw"]], on=["timestamp", "site_id"])
        d = d[d.elev > self.daylight_elev]
        y = d.pv_kw / d.kwp
        self.gbm.fit(d[FEATURES], y)

        d = d.assign(ml=self._raw(d), phys=self._phys_raw(d))
        for sid, g in d.groupby("site_id"):
            sunny = g.ml > 0.1 * g.kwp
            self.calib[sid] = float(np.median(g.pv_kw[sunny] / g.ml[sunny])) if sunny.any() else 1.0
            self.phys_calib[sid] = float(np.median(g.pv_kw[sunny] / g.phys[sunny])) if sunny.any() else 1.0
        return self

    def _raw(self, d):
        p = np.clip(self.gbm.predict(d[FEATURES]), 0, None) * d.kwp.values
        return np.minimum(p, d.inverter_kw.values)

    def _phys_raw(self, d):
        return physical_pv_kw(d.gti, d.temp_c, d.kwp.values, inverter_kw=d.inverter_kw.values)

    def predict(self, feats: pd.DataFrame) -> pd.DataFrame:
        d = feats.copy()
        day = d.elev > self.daylight_elev
        ml = np.zeros(len(d))
        ml[day.values] = self._raw(d[day])
        d["expected_kw"] = ml * d.site_id.map(self.calib).fillna(1.0).values
        d["physics_kw"] = self._phys_raw(d) * d.site_id.map(self.phys_calib).fillna(1.0).values
        d.loc[~day, ["expected_kw", "physics_kw"]] = 0.0
        return d[["timestamp", "site_id", "expected_kw", "physics_kw"]]


def evaluate(telemetry, feats, train_end, holdout_days=7, by_site=False) -> pd.DataFrame:
    """Train on history minus the last `holdout_days`, score on those days (all healthy)."""
    split = train_end - pd.Timedelta(days=holdout_days)
    tel_tr = telemetry[telemetry.timestamp < split]
    model = ExpectedProductionModel().fit(tel_tr, feats[feats.timestamp < split])
    test_f = feats[(feats.timestamp >= split) & (feats.timestamp < train_end)]
    pred = model.predict(test_f).merge(telemetry[["timestamp", "site_id", "pv_kw"]],
                                       on=["timestamp", "site_id"])
    pred = pred.merge(feats[["timestamp", "site_id", "kwp"]], on=["timestamp", "site_id"])
    day = pred[pred.expected_kw > 0]
    if by_site:
        g = day.groupby("site_id")
        return pd.DataFrame({
            "physics_wMAE_%": (100 * g.apply(lambda x: (x.physics_kw - x.pv_kw).abs().sum() / x.pv_kw.sum())).round(1),
            "ML_wMAE_%": (100 * g.apply(lambda x: (x.expected_kw - x.pv_kw).abs().sum() / x.pv_kw.sum())).round(1),
        })

    rows = []
    for name, col in [("physics (calibrated)", "physics_kw"), ("ML (GBM + physics)", "expected_kw")]:
        nmae = (day[col] - day.pv_kw).abs().sum() / day.pv_kw.sum()
        daily = day.assign(date=day.timestamp.dt.date).groupby(["site_id", "date"])[[col, "pv_kw"]].sum()
        daily = daily[daily.pv_kw > 1.0]
        mape = ((daily[col] - daily.pv_kw).abs() / daily.pv_kw).mean()
        rows.append({"model": name, "15min_wMAE_%": round(100 * nmae, 1),
                     "daily_energy_MAPE_%": round(100 * mape, 1)})
    return pd.DataFrame(rows)
