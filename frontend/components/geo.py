"""Find the user's installation from their browser location.

The app ships with a set of demo installations (the ML pipeline's sites.csv).
A real prosumer has exactly one, at a fixed address, so "which installation is
mine?" is a real onboarding question. This lets the browser answer it: the user
taps "Use my location", the browser asks permission, and the nearest
installation is selected.

It leans on streamlit-js-eval for the one thing Python cannot do on its own -
read navigator.geolocation. If that package is not installed the button simply
does not appear, and the manual picker still works, so nothing breaks.
"""

from __future__ import annotations

from math import asin, cos, radians, sin, sqrt

import pandas as pd
import streamlit as st

try:
    from streamlit_js_eval import get_geolocation
    HAVE_GEO = True
except Exception:  # package not installed - feature hides itself
    HAVE_GEO = False


def available() -> bool:
    return HAVE_GEO


def ready() -> bool:
    return HAVE_GEO


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in km between two points on the globe."""
    lat1, lon1, lat2, lon2 = map(radians, (lat1, lon1, lat2, lon2))
    a = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371 * asin(sqrt(a))


def nearest_site(sites: pd.DataFrame, lat: float, lon: float) -> tuple[str, float] | None:
    """The installation closest to (lat, lon), and how far it is in km."""
    if sites.empty or "lat" not in sites or "lon" not in sites:
        return None
    d = sites.apply(lambda r: _haversine(lat, lon, float(r["lat"]), float(r["lon"])), axis=1)
    i = d.idxmin()
    return sites.loc[i, "name"], float(d.loc[i])


def use_my_location(sites: pd.DataFrame, on_select) -> None:
    """A button that selects the nearest installation from the browser location.

    on_select(name) is called with the chosen installation's name. When the
    optional package is missing the button still shows, disabled, with the one
    command that enables it - so it is never silently absent.
    """
    if not HAVE_GEO:
        st.button("Use my location", icon=":material/my_location:", width="stretch",
                  disabled=True,
                  help="Enable this with:  pip install streamlit-js-eval  (then refresh)")
        return
    if st.button("Use my location", icon=":material/my_location:", width="stretch"):
        st.session_state["geo_locating"] = True
        st.rerun()

    if not st.session_state.get("geo_locating"):
        return
    loc = get_geolocation()  # renders the (invisible) component; None until the browser answers
    if not loc:
        st.caption("Allow location in your browser to pick the nearest installation...")
        return
    st.session_state["geo_locating"] = False
    coords = (loc or {}).get("coords") or {}
    lat, lon = coords.get("latitude"), coords.get("longitude")
    if lat is None or lon is None:
        st.warning("Could not read your location. Pick your installation from the list instead.")
        return
    found = nearest_site(sites, lat, lon)
    if not found:
        st.warning("No installation has coordinates to compare against.")
        return
    name, km = found
    on_select(name)
    st.toast(f"Nearest installation: {name} ({km:.0f} km away)")
    st.rerun()
