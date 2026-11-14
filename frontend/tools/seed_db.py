"""Umple solar_energy.db cu date de test: site-uri, invertoare, alerte si
curba de sarcina PPC din xlsx. De rulat o data, din folderul backend:

    python ../frontend/tools/seed_db.py

(sau copiaza scriptul in backend/ si ruleaza-l de acolo)
"""

import sqlite3
import sys
from pathlib import Path

from openpyxl import load_workbook

DB = Path("solar_energy.db")
XLSX = Path("Curba de sarcina la 15 min_TEST.xlsx")

SITES = [
    ("SITE-01", "Consumator PPC (curba reala)", 98.5, "OK"),
    ("SITE-02", "Brutaria Dana", 91.2, "CRITICAL"),
]

INVERTERS = [
    ("INV-01", "SITE-01", "Invertor principal", "Huawei", 10.0, 6.2, 6.5, "OK", 64.0, -71),
    ("INV-02", "SITE-02", "Invertor hala", "Fronius", 20.0, 9.8, 14.5, "CRITICAL", None, -89),
]

ALERTS = [
    ("AL-001", "SITE-02", "INV-02", "CRITICAL", "Productie cu 32% sub asteptari de 6 ore", 28.4, 0),
    ("AL-002", "SITE-01", "INV-01", "INFO", "Lipsesc 30 min de date (comunicatie GSM)", 0.0, 0),
]


def main() -> None:
    if not DB.exists() or not XLSX.exists():
        sys.exit(f"Ruleaza scriptul din folderul care contine {DB} si {XLSX} (backend/).")

    db = sqlite3.connect(DB)
    db.executemany("INSERT OR REPLACE INTO sites VALUES (?,?,?,?)", SITES)
    db.executemany("INSERT OR REPLACE INTO inverters VALUES (?,?,?,?,?,?,?,?,?,?)", INVERTERS)
    db.executemany("INSERT OR REPLACE INTO alerts VALUES (?,?,?,?,?,?,?)", ALERTS)

    db.execute("DELETE FROM load_curves WHERE site_id = 'SITE-01'")
    ws = load_workbook(XLSX, read_only=True)["Curbe la 15 min"]
    rows = ws.iter_rows(min_row=2, values_only=True)
    data = [
        ("SITE-01", start.isoformat(sep=" "), end.isoformat(sep=" "),
         int(no), float(mwh or 0), float(mw or 0), obs)
        for start, end, no, mwh, mw, obs in rows
        if start is not None
    ]
    db.executemany(
        "INSERT INTO load_curves (site_id, start_time, end_time, interval_no, energy_mwh, avg_power_mw, observatii) "
        "VALUES (?,?,?,?,?,?,?)",
        data,
    )
    db.commit()
    n = db.execute("SELECT COUNT(*) FROM load_curves").fetchone()[0]
    print(f"Gata: {len(SITES)} site-uri, {len(INVERTERS)} invertoare, {len(ALERTS)} alerte, {n} intervale de 15 min.")


if __name__ == "__main__":
    main()
