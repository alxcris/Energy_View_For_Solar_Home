import os
import sqlite3
from pathlib import Path
import pandas as pd

# Resolve absolute paths
BASE_DIR = Path(__file__).resolve().parent
EXCEL_PATH = BASE_DIR / "Database resources.xlsx"
DB_PATH = BASE_DIR / "solar_energy.db"

DEFAULT_SITE_ID = "SITE-01"


def parse_bucharest_intervals(start_series: pd.Series, end_series: pd.Series) -> tuple[pd.Series, pd.Series]:
    """
    Parsează intervalele de 15 minute și tratează ora dublă de la trecerea la ora de iarnă
    (ultima duminică din octombrie, ex. 26 octombrie 2025).
    Folosește start_time pentru a deduce fusul orar (+03:00 vs +02:00) și îl aplică consistent și pe end_time.
    """
    start_naive = pd.to_datetime(start_series)
    end_naive = pd.to_datetime(end_series)

    start_aware = start_naive.dt.tz_localize(
        "Europe/Bucharest",
        ambiguous="infer",
        nonexistent="shift_forward",
    )

    # Calculate end_time by adding the actual interval duration (in UTC/seconds) to start_aware
    # Thus 03:45+03:00 + 15 min automatically becomes 03:00+02:00 (or 04:00+03:00 if that is how it appears in Excel)
    duration = end_naive - start_naive
   # If in Excel the 03:45 -> 04:00 interval has end_time 04:00:00 (duration = 15 min),
   # and for the second hour 03:45 -> 04:00 (duration = 15 min), we check whether end_naive is ambiguous:
    is_dst = start_aware.map(lambda x: bool(x.dst())).to_numpy()

    end_aware = end_naive.dt.tz_localize(
        "Europe/Bucharest",
        ambiguous=is_dst,
        nonexistent="shift_forward",
    )

    fmt = "%Y-%m-%dT%H:%M:%S%z"
    start_iso = start_aware.dt.strftime(fmt).str.replace(r"([+-]\d{2})(\d{2})$", r"\1:\2", regex=True)
    end_iso = end_aware.dt.strftime(fmt).str.replace(r"([+-]\d{2})(\d{2})$", r"\1:\2", regex=True)

    return start_iso, end_iso


def convert_excel_to_sqlite():
    if not EXCEL_PATH.exists():
        raise FileNotFoundError(f"Excel File NOT FOUND at path: {EXCEL_PATH}")

    # Remove old database
    if DB_PATH.exists():
        os.remove(DB_PATH)
        print(f"Old database '{DB_PATH.name}' was deleted.")

    # Read main sheet
    df_curbe = pd.read_excel(EXCEL_PATH, sheet_name="Curbe la 15 min", engine="openpyxl")
    df_curbe.columns = [
        "start_time",
        "end_time",
        "interval_in_day",
        "energy_mwh",
        "avg_power_mw",
        "notes",
    ]

    df_curbe["start_time"], df_curbe["end_time"] = parse_bucharest_intervals(
        df_curbe["start_time"], df_curbe["end_time"]
    )
    df_curbe.insert(0, "site_id", DEFAULT_SITE_ID)

    # Read "Centralizator" sheet
    df_cent = pd.read_excel(EXCEL_PATH, sheet_name="Centralizator", skiprows=2, engine="openpyxl")
    df_cent.columns = [
        "month",
        "month_start",
        "next_month_start",
        "source_hourly_total_mwh",
        "total_15min_mwh",
        "difference_mwh",
        "intervals_count",
    ]
    df_cent = df_cent.dropna(how="all")
    df_cent.insert(0, "site_id", DEFAULT_SITE_ID)

    # Create tables for API 
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Table 'sites'
    cursor.execute("""
        CREATE TABLE sites (
            site_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            capacity_kwp REAL DEFAULT 0,
            battery_capacity_kwh REAL DEFAULT 0
        )
    """)
    cursor.execute(
        "INSERT INTO sites (site_id, name, capacity_kwp, battery_capacity_kwh) VALUES (?, ?, ?, ?)",
        (DEFAULT_SITE_ID, "Client Industrial (Excel Import)", 0.0, 0.0),
    )

    # Table 'inverters'
    cursor.execute("""
        CREATE TABLE inverters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_id TEXT NOT NULL,
            name TEXT,
            model TEXT,
            FOREIGN KEY (site_id) REFERENCES sites(site_id)
        )
    """)

    # Table 'alerts'
    cursor.execute("""
        CREATE TABLE alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_id TEXT NOT NULL,
            timestamp TEXT,
            severity TEXT,
            message TEXT,
            FOREIGN KEY (site_id) REFERENCES sites(site_id)
        )
    """)

    # Table 'load_curves'
    df_curbe.to_sql("load_curves", conn, if_exists="replace", index=True, index_label="id")

    df_cent.to_sql("monthly_summary", conn, if_exists="replace", index=False)

    cursor.execute("CREATE INDEX idx_load_curves_site_start ON load_curves(site_id, start_time)")
    cursor.execute("CREATE INDEX idx_alerts_site ON alerts(site_id)")

    conn.commit()
    conn.close()

    print(f"Database '{DB_PATH}' was created successfully.")
    print(f"  - sites: 1 row ({DEFAULT_SITE_ID})")
    print(f"  - load_curves: {len(df_curbe)} rows")
    print(f"  - monthly_summary: {len(df_cent)} rows")


if __name__ == "__main__":
    convert_excel_to_sqlite()
