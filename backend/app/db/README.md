# Solar Energy: Database Module

Overview of the implementation of `solar_energy.py` and `database.py`

1. [Overview](#1-overview)
2. [How the files fit together](#2-how-the-files-fit-together)
3. [Database schema](#3-database-schema)
4. [The clock change problem (DST)](#4-the-clock-change-problem-dst)
5. [Running it](#5-running-it)
6. [Things to watch out for](#6-things-to-watch-out-for)

---

## 1. Overview

This module stores production data for a photovoltaic installation in a SQLite database called `solar_energy.db`. The raw data lives in an Excel workbook with 15-minute load curves, and one of the two files turns that workbook into a database that the rest of the app can query.

The split is simple:

| File | What it does |
|---|---|
| `solar_energy.py` | Reads the Excel file, cleans up the timestamps, wipes the old database and builds a fresh one. |
| `database.py` | Sets up SQLAlchemy, defines the ORM models and hands out database sessions to the app. |

You run the first one by hand when you need to (re)load data. The second one is imported by the backend and used at runtime.

---

## 2. How the files fit together

### 2.1 `solar_energy.py`: the import script

The whole script is one function, `convert_excel_to_sqlite()`, and it's meant to be run directly. Here's what it does, in order:

**Finds its files.** Paths are built from `Path(__file__).resolve().parent`, so the Excel file and the database are always looked for next to the script. It doesn't matter which folder you run it from.

**Deletes the old database.** If `solar_energy.db` already exists, it's removed with `os.remove()` before anything else happens. This is deliberate, but it does mean every run starts from scratch (more on that in [section 6](#6-things-to-watch-out-for)).

**Reads two sheets with pandas** (using `openpyxl`):

- `Curbe la 15 min` becomes the `load_curves` table.
- `Centralizator` (skipping the first two rows) becomes `monthly_summary`.

**Renames the columns by position.** The Excel headers are overwritten with fixed names such as `start_time`, `end_time`, `interval_in_day`, `energy_mwh`, `avg_power_mw` and `notes`. That only works if the sheet has exactly the expected number of columns.

**Fixes the timestamps.** `parse_bucharest_intervals()` puts every timestamp in the `Europe/Bucharest` time zone and deals with the repeated hour in autumn. [Section 4](#4-the-clock-change-problem-dst) explains how.

**Creates the tables.** `sites`, `inverters` and `alerts` are created with plain `CREATE TABLE` statements. `load_curves` and `monthly_summary` are created by pandas through `DataFrame.to_sql()`.

**Adds indexes.** One on `load_curves (site_id, start_time)` and one on `alerts (site_id)`.

**Seeds one site.** A single row, `SITE-01` ("Client Industrial (Excel Import)"), so the foreign keys have something to point at.

### 2.2 `database.py`: SQLAlchemy and the ORM models

This file has the setup the app needs to talk to the database:

| Piece | What it is |
|---|---|
| `DATABASE_URL` | `sqlite:///./solar_energy.db`. Note that this path is relative to the working directory. |
| `engine` | Created with `check_same_thread=False`, which lets different threads share the connection. Web servers need that. |
| `SessionLocal` | A session factory with `autocommit=False` and `autoflush=False`. |
| `Base` | The declarative base class that the models inherit from. |

It also has two helper functions:

- `init_db()` calls `Base.metadata.create_all()`. It creates any ORM tables that don't exist yet and leaves existing ones alone.
- `get_db()` is a generator built for dependency injection. It opens a session, yields it, and closes it in a `finally` block, so you never leak connections. With FastAPI it looks like this:

```python
from fastapi import Depends
from sqlalchemy.orm import Session
from database import get_db, Site

@app.get("/sites")
def list_sites(db: Session = Depends(get_db)):
    return db.query(Site).all()
```

There are four models: `Site`, `Inverter`, `LoadCurve15Min` and `Alert`. The `monthly_summary` table has no model.

---

## 3. Database schema

### 3.1 How the tables relate

```
sites (1) ──< inverters (N)
sites (1) ──< load_curves (N)
sites (1) ──< alerts (N)
inverters (1) ──< alerts (N)      [inverter_id is optional, ORM only]
sites (1) ──< monthly_summary (N) [logical link only, no foreign key]
```

Everything hangs off `site_id`. Alerts can also point at a specific inverter through `inverter_id`.

The column types below are the ones defined in the ORM. Where the SQL created by `solar_energy.py` differs, [section 6](#6-things-to-watch-out-for) covers it.

### 3.2 `sites`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `site_id` | `String` | PK, indexed | Unique ID, e.g. `SITE-01` |
| `name` | `String` | NOT NULL | Site name |
| `sla_availability_pct` | `Float` | default `96.0` | SLA availability target (%) |
| `status` | `String` | default `"OK"` | `OK`, `WARNING` or `CRITICAL` |

A site has many inverters (`cascade="all, delete-orphan"`), so deleting a site deletes its inverters too.

### 3.3 `inverters`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `inverter_id` | `String` | PK, indexed | Inverter ID |
| `site_id` | `String` | FK to `sites.site_id`, NOT NULL, indexed | The site it belongs to |
| `name` | `String` | NOT NULL | e.g. `"Invertor Hala Est"` |
| `brand` | `String` | NOT NULL | Huawei, Fronius, SMA |
| `rated_power_kw` | `Float` | NOT NULL | Installed capacity (kW) |
| `current_power_kw` | `Float` | default `0.0` | Power right now (kW) |
| `expected_power_kw` | `Float` | default `0.0` | Power we'd expect (kW) |
| `status` | `String` | default `"OK"` | `OK`, `WARNING` or `CRITICAL` |
| `battery_soc_pct` | `Float` | nullable | Battery state of charge (%) |
| `gsm_signal_dbm` | `Integer` | nullable | GSM signal strength (dBm) |

The last two are optional because not every manufacturer exposes them.

### 3.4 `load_curves`

The 15-minute data from Excel.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | `Integer` | PK, autoincrement | Row ID |
| `site_id` | `String` | FK to `sites.site_id`, NOT NULL, indexed | Which site |
| `start_time` | `DateTime` | NOT NULL, indexed | Start of the interval |
| `end_time` | `DateTime` | NOT NULL | End of the interval |
| `interval_no` | `Integer` | NOT NULL | Interval number within the day |
| `energy_mwh` | `Float` | NOT NULL | Energy (MWh) |
| `avg_power_mw` | `Float` | NOT NULL | Average power (MW) |
| `observatii` | `String` | nullable | Free-text remarks |

One thing to know: in the database that `solar_energy.py` actually produces, `start_time` and `end_time` are stored as TEXT in ISO 8601 format with an offset, not as real datetimes.

### 3.5 `alerts`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `alert_id` | `String` | PK, indexed | Alert ID |
| `site_id` | `String` | FK to `sites.site_id`, NOT NULL, indexed | Which site |
| `inverter_id` | `String` | FK to `inverters.inverter_id`, nullable | Which inverter, if any |
| `severity` | `String` | NOT NULL | Severity level |
| `message` | `String` | NOT NULL | What happened |
| `estimated_loss_kwh` | `Float` | default `0.0` | Estimated energy lost (kWh) |
| `resolved` | `Integer` | default `0` | 0 = open, 1 = resolved |

### 3.6 `monthly_summary`

Only the import script creates this table, from the `Centralizator` sheet. There's no ORM model, and pandas picks the column types on its own.

| Column | What it holds |
|---|---|
| `site_id` | Added by the script (`SITE-01`) |
| `month` | The month |
| `month_start` | First moment of the month |
| `next_month_start` | First moment of the next month |
| `source_hourly_total_mwh` | Total from the hourly source data (MWh) |
| `total_15min_mwh` | Total from the 15-minute curves (MWh) |
| `difference_mwh` | The gap between those two totals (MWh) |
| `intervals_count` | How many intervals were counted |

It's there for reconciliation: it lets you check that the 15-minute data adds up to the hourly source.

---

## 4. The clock change problem (DST)

In Romania the clocks go back on the last Sunday of October (26 October in 2025). At 04:00 summer time (`+03:00`) the clock drops to 03:00 winter time (`+02:00`), which means the hour from 03:00 to 03:59 happens twice. A plain timestamp in Excel, with no time zone attached, can't tell you which of the two it is.

`parse_bucharest_intervals()` handles it in four steps:

1. **Start times.** They're localized with `tz_localize("Europe/Bucharest", ambiguous="infer", nonexistent="shift_forward")`. With `ambiguous="infer"`, pandas works out from the row order which 03:xx is the first pass (`+03:00`) and which is the second (`+02:00`).
2. **End times.** The DST flag of each start time is passed as `ambiguous=is_dst` when localizing the matching end time, so both ends of an interval get the same offset.
3. **Spring.** `nonexistent="shift_forward"` covers the opposite problem in March, when an hour is skipped entirely.
4. **Output.** Timestamps are formatted as ISO 8601 with an offset (`%Y-%m-%dT%H:%M:%S%z`), and a regex turns `+0300` into `+03:00`.

Around the autumn change the result looks like this:

| start_time | end_time |
|---|---|
| `2025-10-26T02:45:00+03:00` | `2025-10-26T03:00:00+03:00` |
| `2025-10-26T03:00:00+03:00` | `2025-10-26T03:15:00+03:00` |
| `2025-10-26T03:45:00+03:00` | see the caveat in section 6.3 |
| `2025-10-26T03:00:00+02:00` | `2025-10-26T03:15:00+02:00` |
| `2025-10-26T03:45:00+02:00` | `2025-10-26T04:00:00+02:00` |

The rows in the Excel sheet have to be in chronological order. If they aren't, `ambiguous="infer"` can fail or hand out the wrong offsets.

---

## 5. Running it

### 5.1 What you need

- Python 3.9 or newer (the script uses `tuple[...]` type hints)
- SQLAlchemy 1.4 or newer
- `Database resources.xlsx` in the same folder as `solar_energy.py`, with the sheets `Curbe la 15 min` and `Centralizator`

### 5.2 Install the dependencies

```bash
python -m venv .venv
source .venv/bin/activate        # on Windows: .venv\Scripts\activate
pip install pandas openpyxl sqlalchemy
```

### 5.3 Build the database

```bash
python solar_energy.py
```

You should see something like:

```
Old database 'solar_energy.db' was deleted.      # only if one existed
Database '.../solar_energy.db' was created successfully.
  - sites: 1 row (SITE-01)
  - load_curves: <N> rows
  - monthly_summary: <M> rows
```

### 5.4 Use it from the app

```python
from database import SessionLocal, init_db

init_db()                 # creates missing ORM tables, doesn't touch existing ones
db = SessionLocal()
try:
    ...                   # your queries
finally:
    db.close()
```

### 5.5 Sanity check

```bash
sqlite3 solar_energy.db ".tables"
sqlite3 solar_energy.db "SELECT start_time, end_time FROM load_curves WHERE start_time LIKE '2025-10-26T03%';"
```

---

## 6. Things to watch out for

### 6.1 The script and the ORM models don't agree

The import script and the ORM models describe different versions of the same tables. Someone on the backend team should line them up. Here's where they differ.

**`sites`**

| `solar_energy.py` (SQL) | `database.py` (ORM) |
|---|---|
| `site_id`, `name` | `site_id`, `name` (same) |
| `capacity_kwp`, `battery_capacity_kwh` | not present |
| not present | `sla_availability_pct`, `status` |

**`inverters`**

| `solar_energy.py` (SQL) | `database.py` (ORM) |
|---|---|
| `id INTEGER AUTOINCREMENT` (PK) | `inverter_id String` (PK) |
| `model` | `brand` |
| `site_id`, `name` | `site_id`, `name` (same) |
| not present | `rated_power_kw`, `current_power_kw`, `expected_power_kw`, `status`, `battery_soc_pct`, `gsm_signal_dbm` |

**`alerts`**

| `solar_energy.py` (SQL) | `database.py` (ORM) |
|---|---|
| `id INTEGER AUTOINCREMENT` (PK) | `alert_id String` (PK) |
| `timestamp` | not present |
| `severity`, `message`, `site_id` | `severity`, `message`, `site_id` (same) |
| not present | `inverter_id`, `estimated_loss_kwh`, `resolved` |

**`load_curves`**

| `solar_energy.py` | `database.py` (ORM) | What differs |
|---|---|---|
| `interval_in_day` | `interval_no` | Name |
| `notes` | `observatii` | Name |
| `start_time`, `end_time` as ISO 8601 TEXT with offset | `DateTime` | Type |
| `id` created by `to_sql`, no explicit PK or autoincrement | `id` as PK with autoincrement | Constraints |

**`monthly_summary`** exists only in the database and has no ORM model.

### 6.2 What that means in practice

- **`init_db()` won't fix a mismatched schema.** `create_all()` skips tables that already exist. If the database came from `solar_energy.py`, the ORM tables won't be recreated, and queries can fail with `no such column` errors for things like `brand`, `interval_no` or `observatii`.
- **Datetimes stored as ISO text can break reads.** SQLAlchemy's `DateTime` type on SQLite expects `YYYY-MM-DD HH:MM:SS[.ffffff]`, not `...T03:00:00+02:00`. You can use `String` columns in the ORM, or write a `TypeDecorator` or do the parsing yourself.
- **The two files point at the database differently.** `solar_energy.py` uses an absolute path next to the script. `database.py` uses `./solar_energy.db`, relative to wherever the app was started. Launch the app from another folder and SQLAlchemy may quietly create or open a different, empty database. Building `DATABASE_URL` from `Path(__file__).resolve().parent` would fix that.
- **Units are mixed.** `load_curves` is in MW and MWh, while `inverters` is in kW. Convert explicitly wherever the two meet.

### 6.3 Other things worth knowing

- **Every run wipes the database.** Anything added after the import (inverters, alerts, status changes) is lost the next time you run the script. A backup step, or a switch to upserts, would make this safer.
- **`inverters` and `alerts` start empty.** Nothing imports data into them yet.
- **SQLite doesn't enforce foreign keys by default.** If you want it to, run `PRAGMA foreign_keys = ON` on each connection, for example in a SQLAlchemy `connect` event listener.
- **Columns are renamed by position.** The script expects 6 columns in `Curbe la 15 min` and 7 in `Centralizator`. If the sheet layout changes, assigning `df.columns` will raise a `ValueError`.
- **Longer term,** it would help to add a migration tool like Alembic and treat the ORM models as the single source of truth, with the import script inserting rows through SQLAlchemy sessions instead of raw SQL.
- **Worth double-checking: the 03:45 interval on the autumn change day.** For the interval that starts at `03:45+03:00`, the `end_time` in Excel is a naive `04:00`. That time isn't ambiguous, so `tz_localize` will give it `+02:00`, and the interval would come out as 75 minutes long instead of 15. Check this against the real data, for instance by computing `end_time - start_time` and comparing it with 15 minutes. A sturdier approach is to calculate `end_time = start_time + 15 min` in UTC. Also, the `duration` variable in that function is computed but never used.
