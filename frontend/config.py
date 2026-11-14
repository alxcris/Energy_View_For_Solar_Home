"""Settings shared by the whole frontend."""

import os
import sys
from pathlib import Path

# FastAPI backend root. /health is at the root, data lives under /api/v1.
API_URL = os.getenv("API_URL", "http://localhost:8000")
API_V1 = f"{API_URL}/api/v1"

# True forces simulated data. Even when false, the frontend falls back to mock
# data on its own if the backend does not answer or its database is empty.
USE_MOCK = os.getenv("USE_MOCK", "false").lower() == "true"

# How often data is reloaded (seconds)
REFRESH_SECONDS = 30

# Live view: how often the clock moves one step forward while playing (seconds)
LIVE_TICK_SECONDS = 2.0

# Solar window: the hours we try to move flexible consumption into
SOLAR_WINDOW = (11, 15)

# A telemetry reading older than this is reported as stale instead of live
STALE_AFTER_MINUTES = 60

# Per-user database (accounts, onboarding answers, accepted recommendations)
USER_DB = Path(os.getenv("USER_DB", Path(__file__).resolve().parent / "data" / "app.db"))

# Prices (lei/kWh) for every savings estimate. They come from the ML pipeline
# (ml_pipeline/ml/tariffs.py), so the questionnaire, the recommendations and the
# ML results all use the same tariff. The fallback values match that file.
_ML_DIR = Path(__file__).resolve().parent.parent / "ml_pipeline"
try:
    if str(_ML_DIR) not in sys.path:
        sys.path.append(str(_ML_DIR))
    from ml.tariffs import FEED_IN_LEI_KWH, RETAIL_LEI_KWH
except Exception:  # ml_pipeline missing or its dependencies not installed
    RETAIL_LEI_KWH, FEED_IN_LEI_KWH = 1.30, 0.30

PRICE_BUY_LEI_KWH = RETAIL_LEI_KWH    # what a kWh from the grid costs the customer
PRICE_SELL_LEI_KWH = FEED_IN_LEI_KWH  # what an exported kWh is worth to the prosumer

# Data colours. One hue per concept, used by every chart, card and the flow
# diagram, so a colour always means the same thing: amber is the sun, blue is
# the house, emerald is storage, violet is the grid, cyan is energy leaving,
# pink is money per kWh, rose is a fault or an expensive hour.
COLORS = {
    "solar": "#F59E0B",
    "consumption": "#2563EB",
    "battery": "#059669",
    "grid": "#7C3AED",
    "export": "#0891B2",
    "price": "#DB2777",
    "peak": "#E11D48",
    "bar": "#0D9488",
    "forecast": "#8B5CF6",
    "expected": "#94A3B8",
    "solar_window": "rgba(245, 158, 11, 0.10)",
}

# A categorical ramp for anything that needs several colours at once (the
# consumption breakdown, the appliance plan, multi-series charts). Ordered so
# that neighbours stay distinguishable, and all at a similar depth so no single
# bar shouts louder than the others.
SERIES = ["#2563EB", "#F59E0B", "#0D9488", "#7C3AED", "#DB2777",
          "#059669", "#EA580C", "#0891B2"]

# Interface colours. The brand is green, with proper subtones - a pale mint for
# tints, a mid green for buttons, a deep forest for text on green - so the frame
# has depth instead of one flat colour. Each state keeps its own soft tint
# (green ok, amber warn, rose danger, blue info, violet accent, teal cool) so
# two components side by side are easy to tell apart.
UI = {
    "bg": "#DEEBE3",
    "card": "#FFFFFF",
    "surface": "#EAF3EE",
    "sidebar": "#DFEAE4",
    "text": "#0E2A22",
    "muted": "#576B64",
    "faint": "#8CA39B",
    "border": "#DCE7E1",
    "grid": "#EAF1ED",
    "track": "#E4EDE8",
    "primary": "#12A56F",
    "primary_dark": "#0A7D56",
    "primary_light": "#34C98D",
    "primary_mint": "#D5F2E4",
    "primary_soft": "#E4F6EC",
    "primary_shadow": "rgba(18, 165, 111, 0.26)",
    "ok": "#12A56F",
    "ok_soft": "#E4F6EC",
    "ok_dark": "#0A7D56",
    "danger": "#E11D48",
    "danger_soft": "#FDE7EC",
    "danger_dark": "#A4133C",
    "warn": "#E08600",
    "warn_soft": "#FCF0DB",
    "warn_dark": "#9A5B00",
    "info": "#2563EB",
    "info_soft": "#E7EFFE",
    "info_dark": "#1D4ED8",
    "accent": "#7C3AED",
    "accent_soft": "#F1EBFE",
    "accent_dark": "#5B21B6",
    "cool": "#0891B2",
    "cool_soft": "#E0F4F9",
    "cool_dark": "#0B6E87",
    "hero_from": "#072019",
    "hero_mid": "#0C3D2C",
    "hero_to": "#115E43",
    "hero_text": "#FFFFFF",
    "hero_sub": "rgba(255,255,255,.78)",
    "hero_eyebrow": "#6EE7B7",
    "pill_bg": "#E4F6EC",
    "plan_bg": "#EFFAF4",
    "shadow": "0 1px 2px rgba(14,42,34,.06), 0 12px 30px -14px rgba(14,42,34,.22)",
    "shadow_lg": "0 2px 4px rgba(14,42,34,.05), 0 24px 48px -20px rgba(14,42,34,.24)",
}

SEVERITY_ORDER = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
