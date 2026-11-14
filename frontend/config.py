"""Setari comune pentru tot frontend-ul."""

import os

# Radacina backend-ului FastAPI. /health e la radacina, datele sub /api/v1.
API_URL = os.getenv("API_URL", "http://localhost:8000")
API_V1 = f"{API_URL}/api/v1"

# True forteaza datele simulate. Chiar si pe false, frontend-ul trece singur
# pe mock daca backend-ul nu raspunde sau baza lui e goala (vezi api_client).
USE_MOCK = os.getenv("USE_MOCK", "false").lower() == "true"

# Cat de des se reincarca datele (secunde)
REFRESH_SECONDS = 30

# Fereastra solara: intervalul orar in care mutam consumul flexibil
SOLAR_WINDOW = (11, 15)

# Preturi orientative (lei/kWh) pentru estimarile de economii.
# TODO inainte de pitch: verificati valorile reale pentru prosumatori
# (pretul de cumparare vs. cat primesti pe energia livrata in retea).
PRICE_BUY_LEI_KWH = 1.1
PRICE_SELL_LEI_KWH = 0.4

# Culori fixe, ca graficele sa arate la fel peste tot
COLORS = {
    "consumption": "#3A86FF",
    "solar_window": "rgba(245, 183, 0, 0.18)",
    "peak": "#E63946",
    "bar": "#2EC4B6",
    "expected": "#8A8A8A",
}

SEVERITY_ORDER = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
