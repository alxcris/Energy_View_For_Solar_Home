import os
import sqlite3
import pandas as pd

EXCEL_PATH = "Database resources.xlsx"
DB_PATH = "ppc_platform.db"


def convert_excel_to_sqlite():

    # Remove existing database
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"Old database '{DB_PATH}' was deleted.")

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
    df_curbe["start_time"] = pd.to_datetime(df_curbe["start_time"]).dt.strftime("%Y-%m-%d %H:%M:%S")
    df_curbe["end_time"] = pd.to_datetime(df_curbe["end_time"]).dt.strftime("%Y-%m-%d %H:%M:%S")

    # Read Centralizator sheet 
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

    # Create new database with the data from the Excel
    conn = sqlite3.connect(DB_PATH)
    df_curbe.to_sql("load_curve_15min", conn, if_exists="replace", index=True, index_label="id")
    df_cent.to_sql("monthly_summary", conn, if_exists="replace", index=False)

    # Index for quick interogations
    conn.execute("CREATE INDEX idx_load_curve_start ON load_curve_15min(start_time)")
    conn.commit()
    conn.close()

    print(f"Database '{DB_PATH}' was created")
    print(f"  - load_curve_15min: {len(df_curbe)} rows")
    print(f"  - monthly_summary: {len(df_cent)} rows")


if __name__ == "__main__":
    convert_excel_to_sqlite()