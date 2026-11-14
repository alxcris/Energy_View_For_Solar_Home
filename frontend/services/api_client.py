"""Singurul loc din frontend care stie de unde vin datele.

Ordinea de decizie, la fiecare apel:
1. USE_MOCK=true -> date simulate;
2. backend-ul nu raspunde la /health -> date simulate;
3. backend-ul raspunde dar nu are date (baza goala / 404) -> date simulate;
4. altfel -> datele reale de la /api/v1.

Paginile nu fac niciodata request-uri direct, apeleaza doar functiile de aici.
"""

import pandas as pd
import requests
import streamlit as st

from config import API_URL, API_V1, REFRESH_SECONDS, USE_MOCK
from services import mock_data, ml_source


def _get(path: str, params: dict | None = None):
    r = requests.get(f"{API_V1}{path}", params=params, timeout=5)
    r.raise_for_status()
    return r.json()


@st.cache_data(ttl=10)
def _backend_alive() -> bool:
    if USE_MOCK:
        return False
    try:
        return requests.get(f"{API_URL}/health", timeout=2).status_code == 200
    except requests.RequestException:
        return False


@st.cache_data(ttl=REFRESH_SECONDS)
def _raw_sites() -> list[dict]:
    if _backend_alive():
        try:
            sites = _get("/sites")
            if sites:
                return sites
        except requests.RequestException:
            pass
    return mock_data.get_sites()


def data_source() -> str:
    """'api' sau 'mock' - folosit si de banner, si de pagini daca au nevoie."""
    if not _backend_alive():
        return "mock"
    try:
        return "api" if _get("/sites") else "mock"
    except requests.RequestException:
        return "mock"


def api_status_banner() -> None:
    if ml_source.available() and not USE_MOCK:
        return  # paginile folosesc pipeline-ul ML, nu e nimic de semnalat
    if USE_MOCK:
        st.info("Date simulate (USE_MOCK=true).")
    elif not _backend_alive():
        st.warning(f"Backend-ul nu raspunde la {API_URL} - merg pe date simulate.")
    elif data_source() == "mock":
        st.warning("Backend-ul merge, dar baza lui e goala - date simulate. "
                   "Ruleaza `python tools/seed_db.py` in folderul backend/.")


def get_sites() -> pd.DataFrame:
    sites = _raw_sites()
    flat = [{k: v for k, v in s.items() if k != "inverters"} for s in sites]
    return pd.DataFrame(flat)


def get_inverters(site_id: str) -> pd.DataFrame:
    site = next((s for s in _raw_sites() if s["site_id"] == site_id), None)
    return pd.DataFrame(site["inverters"]) if site else pd.DataFrame()


@st.cache_data(ttl=REFRESH_SECONDS)
def get_telemetry(site_id: str, limit: int = 96) -> pd.DataFrame:
    rows = None
    if _backend_alive():
        try:
            rows = _get(f"/sites/{site_id}/telemetry", {"limit": limit})
        except requests.RequestException:
            rows = None
    if rows is None:
        rows = mock_data.get_telemetry(site_id, limit)
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


@st.cache_data(ttl=REFRESH_SECONDS)
def get_hourly_profile(site_id: str) -> pd.DataFrame:
    rows = None
    if _backend_alive():
        try:
            rows = _get(f"/sites/{site_id}/hourly-profile")
        except requests.RequestException:
            rows = None
    return pd.DataFrame(rows or mock_data.get_hourly_profile(site_id))


@st.cache_data(ttl=REFRESH_SECONDS)
def get_monthly_summary(site_id: str) -> pd.DataFrame:
    rows = None
    if _backend_alive():
        try:
            rows = _get(f"/sites/{site_id}/monthly-summary")
            rows = rows or None
        except requests.RequestException:
            rows = None
    return pd.DataFrame(rows or mock_data.get_monthly_summary(site_id))


@st.cache_data(ttl=REFRESH_SECONDS)
def get_alerts() -> pd.DataFrame:
    rows = None
    if _backend_alive():
        try:
            rows = _get("/alerts")
        except requests.RequestException:
            rows = None
    if rows is None:
        rows = mock_data.get_alerts()
    return pd.DataFrame(rows)


@st.cache_data(ttl=REFRESH_SECONDS)
def get_ai_context(site_id: str) -> dict:
    if _backend_alive():
        try:
            return _get(f"/sites/{site_id}/ai-context")
        except requests.RequestException:
            pass
    return mock_data.get_ai_context(site_id)


def get_ai_recommendations(site_id: str) -> list[str] | None:
    """Recomandarile serviciului AI (backend -> :8001). None daca nu e disponibil."""
    if not _backend_alive():
        return None
    try:
        return _get(f"/sites/{site_id}/recommendations").get("recommendations")
    except requests.RequestException:
        return None
