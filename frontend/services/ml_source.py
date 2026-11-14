"""Reads the ML pipeline results (ml_pipeline/out/*.csv), if they exist.

This is the best data source: production + consumption + battery + grid,
weather-expected production, alerts with the loss in lei and personalised
recommendations (customer.json). Generate them with:

    cd ml_pipeline && python run_demo.py
"""

import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from config import REFRESH_SECONDS  # kept for callers that still import it
from services import fleet

TZ = "Europe/Bucharest"


def _out_dir() -> Path:
    override = os.getenv("ML_OUT")
    if override:
        return Path(override)
    for p in ("../ml_pipeline/out", "ml_pipeline/out"):
        if Path(p).exists():
            return Path(p)
    return Path("../ml_pipeline/out")


def available() -> bool:
    out = _out_dir()
    return (out / "sites.csv").exists() and (out / "telemetry.csv").exists()


def _stamp(*names: str) -> float:
    """The newest mtime of the files a reader depends on.

    It is the cache key: the files only change when someone re-runs the pipeline,
    so the data is read once and every rerun after that is free - but a new
    run_demo.py is picked up immediately, without a stale time-to-live.
    """
    out = _out_dir()
    times = [(out / n).stat().st_mtime for n in names if (out / n).exists()]
    return max(times) if times else 0.0


@st.cache_data(show_spinner=False)
def _read_sites(stamp: float) -> pd.DataFrame:
    return pd.read_csv(_out_dir() / "sites.csv")


def get_sites() -> pd.DataFrame:
    return fleet.expand(_read_sites(_stamp("sites.csv")))


@st.cache_data(show_spinner=False)
def _read_telemetry(stamp: float) -> pd.DataFrame:
    out = _out_dir()
    df = pd.read_csv(out / "telemetry.csv", parse_dates=["timestamp"])
    exp = pd.read_csv(out / "expected.csv", parse_dates=["timestamp"])
    df = df.merge(exp[["timestamp", "site_id", "expected_kw"]],
                  on=["timestamp", "site_id"], how="left")
    df["timestamp"] = df["timestamp"].dt.tz_convert(TZ).dt.tz_localize(None)
    return df


def _telemetry() -> pd.DataFrame:
    return _read_telemetry(_stamp("telemetry.csv", "expected.csv"))


@st.cache_data(show_spinner=False)
def _timeseries(site_id: str, days: int, stamp: float) -> pd.DataFrame:
    df = _telemetry()
    df = df[df["site_id"] == site_id]
    t0 = df["timestamp"].max() - pd.Timedelta(days=days)
    df = df[df["timestamp"] >= t0].copy()
    # columns compatible with the pages that only know about consumption
    df["consumption_kw"] = df["load_kw"]
    df["energy_kwh"] = df["load_kw"] * 0.25
    return df


def get_timeseries(site_id: str, days: int = 3) -> pd.DataFrame:
    return _timeseries(fleet.resolve(site_id), days, _stamp("telemetry.csv", "expected.csv"))


@st.cache_data(show_spinner=False)
def _hourly_profile(site_id: str, stamp: float) -> pd.DataFrame:
    df = _telemetry()
    df = df[df["site_id"] == site_id]
    g = df.groupby(df["timestamp"].dt.hour)["load_kw"].mean().round(2)
    return pd.DataFrame({"hour": g.index, "avg_power_kw": g.values})


def get_hourly_profile(site_id: str) -> pd.DataFrame:
    return _hourly_profile(fleet.resolve(site_id), _stamp("telemetry.csv"))


def get_daily_energy(site_id: str, days: int = 14) -> pd.DataFrame:
    df = get_timeseries(site_id, days)
    g = (df.groupby(df["timestamp"].dt.date)["energy_kwh"].sum()).round(1)
    return pd.DataFrame({"day": [d.strftime("%d %b") for d in g.index], "kwh": g.values})


def last_reading() -> pd.Timestamp | None:
    """The newest timestamp in the dataset - used by the data-health badge."""
    df = _telemetry()
    return df["timestamp"].max() if not df.empty else None


@st.cache_data(show_spinner=False)
def _read_alerts(stamp: float) -> pd.DataFrame:
    df = pd.read_csv(_out_dir() / "alerts.csv")
    df["detected_at"] = (pd.to_datetime(df["detected_at"], utc=True)
                         .dt.tz_convert(TZ).dt.tz_localize(None))
    return df


def get_alerts() -> pd.DataFrame:
    return _read_alerts(_stamp("alerts.csv"))


@st.cache_data(show_spinner=False)
def _read_customer(stamp: float) -> dict:
    p = _out_dir() / "customer.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def get_customer(site_id: str) -> dict:
    return _read_customer(_stamp("customer.json")).get(fleet.resolve(site_id), {})


def schedule_ics(site_id: str) -> bytes | None:
    """The appliance schedule the pipeline wrote as a calendar file, if it exists."""
    p = _out_dir() / f"schedule_{fleet.resolve(site_id)}.ics"
    try:
        return p.read_bytes() if p.exists() else None
    except OSError:
        return None


@st.cache_data(show_spinner=False)
def _read_dispatch(stamp: float) -> pd.DataFrame:
    """Tomorrow's battery plan, quarter-hour by quarter-hour."""
    out = _out_dir()
    path = out / "dispatch_all.csv"
    if not path.exists():
        path = out / "dispatch_plan.csv"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    df["timestamp_local"] = (pd.to_datetime(df["timestamp_local"], utc=True)
                             .dt.tz_convert(TZ).dt.tz_localize(None))
    return df


def get_dispatch(site_id: str) -> pd.DataFrame:
    df = _read_dispatch(_stamp("dispatch_all.csv", "dispatch_plan.csv"))
    if df.empty:
        return df
    if "site_id" in df.columns:
        df = df[df["site_id"] == fleet.resolve(site_id)]
    return df


@st.cache_data(show_spinner=False)
def _read_impact(stamp: float) -> pd.DataFrame:
    """What the monitoring was worth: our detection time against a weekly check."""
    path = _out_dir() / "impact.csv"
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def get_impact() -> pd.DataFrame:
    return _read_impact(_stamp("impact.csv"))


def get_devices(site_id: str) -> list[dict]:
    """The appliance schedule the pipeline worked out for this customer."""
    return get_customer(site_id).get("devices", [])  # get_customer already resolves


def nudges_as_notifications(site_id: str) -> list[dict]:
    """The ML recommendations, in the inbox card format."""
    info = get_customer(site_id)
    cards = []
    for i, n in enumerate(info.get("nudges", [])):
        cards.append({
            "id": f"ml_nudge_{site_id}_{i}",
            "title": "A habit spotted in your consumption",
            "body": n["text"],
            "saving": float(n.get("saving_lei_per_run", 0)),
        })
    return cards
