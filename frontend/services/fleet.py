"""Make the installation list look like a real fleet, without touching the ML
pipeline.

The pipeline simulates eight installations. A demo reads better with the whole
map covered - every Bucharest sector and the big cities - so this adds those as
extra installations. Each one borrows the data of one of the eight real sites
(its "twin"): same telemetry, battery and recommendations, shown under the new
name and pinned at the new coordinates. The dropdown and the "use my location"
button get a full country to work with, and nothing downstream breaks because
every installation still resolves to real pipeline data.
"""

from __future__ import annotations

import pandas as pd

# name, latitude, longitude - the places to add. Specs (kWp, battery, azimuth)
# come from the twin, so the live view, the battery node and the numbers always
# agree with the telemetry behind them.
EXTRA_PLACES = [
    # Bucharest, sector by sector (Pipera is already S01)
    ("Bucuresti - Sector 1 (Baneasa)", 44.512, 26.083),
    ("Bucuresti - Sector 2 (Colentina)", 44.462, 26.134),
    ("Bucuresti - Sector 3 (Titan)", 44.418, 26.151),
    ("Bucuresti - Sector 4 (Berceni)", 44.388, 26.121),
    ("Bucuresti - Sector 5 (Rahova)", 44.409, 26.051),
    ("Bucuresti - Sector 6 (Drumul Taberei)", 44.431, 26.024),
    # the rest of the big cities
    ("Sibiu - Centru", 45.792, 24.152),
    ("Galati - Mazepa", 45.441, 28.053),
    ("Ploiesti - Nord", 44.941, 26.031),
    ("Braila - Centru", 45.271, 27.958),
    ("Arad - Aradul Nou", 46.166, 21.312),
    ("Pitesti - Trivale", 44.857, 24.869),
    ("Bacau - Centru", 46.567, 26.914),
    ("Targu Mures - Tudor", 46.541, 24.558),
    ("Baia Mare - Centru", 47.657, 23.579),
    ("Buzau - Micro 14", 45.151, 26.822),
    ("Satu Mare - Micro 17", 47.792, 22.858),
    ("Suceava - Burdujeni", 47.651, 26.258),
    ("Ramnicu Valcea - Ostroveni", 45.101, 24.371),
    ("Drobeta-Turnu Severin", 44.631, 22.657),
    ("Focsani - Sud", 45.697, 27.186),
    ("Alba Iulia - Cetate", 46.068, 23.581),
    ("Oradea - Centru", 47.057, 21.942),
    ("Cluj-Napoca - Marasti", 46.782, 23.612),
    ("Timisoara - Dumbravita", 45.790, 21.248),
]


# virtual site_id -> real twin site_id, filled in by expand()
_TWIN: dict[str, str] = {}


def expand(real: pd.DataFrame) -> pd.DataFrame:
    """The real sites plus the extra ones, each cloned from a twin."""
    if real.empty:
        return real
    twins = list(real["site_id"])
    rows = []
    for i, (name, lat, lon) in enumerate(EXTRA_PLACES):
        twin_id = twins[i % len(twins)]
        base = real[real["site_id"] == twin_id].iloc[0].to_dict()
        vid = f"V{i + 1:02d}"
        _TWIN[vid] = twin_id
        base.update({"site_id": vid, "name": name, "lat": lat, "lon": lon})
        rows.append(base)
    return pd.concat([real, pd.DataFrame(rows)], ignore_index=True)


def resolve(site_id: str) -> str:
    """The real site whose pipeline data a (possibly virtual) installation reads."""
    return _TWIN.get(site_id, site_id)
