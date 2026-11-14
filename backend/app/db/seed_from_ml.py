"""Fill the API database (solar_energy.db) from the ML pipeline, using the ORM models in
database.py so the tables can never drift apart from what the routes read.

    cd ml_pipeline && python run_demo.py            # writes ml_pipeline/out/*.csv
    cd ../backend && python -m app.db.seed_from_ml  # fills solar_energy.db
    uvicorn app.main:app --reload

What goes where:
    sites        8 simulated installations + C01, the real PPC consumer (load curve only)
    inverters    one per simulated installation: latest actual and expected power, battery
    load_curves  the real PPC 15-minute curve for C01 + the simulated household load
    alerts       the ML alerts (open = still ongoing), with the estimated loss in kWh

Re-running it replaces everything, so it is safe to run after every run_demo.py.
"""
import argparse
from pathlib import Path

import pandas as pd

from app.db.database import (Alert, Base, Inverter, LoadCurve15Min, SessionLocal, Site,
                             engine)

BACKEND = Path(__file__).resolve().parents[2]
ML_OUT = BACKEND.parent / "ml_pipeline" / "out"
EXCEL_CANDIDATES = [BACKEND.parent / "ml_pipeline" / "data" / "curba_sarcina_test.xlsx",
                    BACKEND / "app" / "db" / "Database resources.xlsx"]
TZ = "Europe/Bucharest"
# placeholder makers so the UI can show the multi-vendor case; the telemetry is simulated
BRANDS = ["Huawei", "Fronius", "SMA"]


def _status(site_alerts: pd.DataFrame) -> str:
    open_ = site_alerts[site_alerts.ongoing.astype(bool)]
    if (open_.severity == "critical").any():
        return "CRITICAL"
    return "WARNING" if len(open_) else "OK"


def _availability(tel: pd.DataFrame, exp: pd.DataFrame, kwp: float, days: int = 30) -> float:
    """Share of sunny 15-min slots (last `days`) in which the inverter actually produced."""
    d = exp.merge(tel[["timestamp", "pv_kw"]], on="timestamp", how="left")
    d = d[d.timestamp >= d.timestamp.max() - pd.Timedelta(days=days)]
    sunny = d[d.expected_kw > 0.1 * kwp]
    if sunny.empty:
        return 100.0
    ok = sunny.pv_kw.fillna(0) >= 0.05 * sunny.expected_kw     # missing data counts as down
    return round(100 * ok.mean(), 1)


def _real_curve(path: Path, site_id: str) -> list:
    raw = pd.read_excel(path, sheet_name="Curbe la 15 min", engine="openpyxl")
    raw.columns = ["start", "end", "interval", "mwh", "mw", "note"][: len(raw.columns)]
    return [LoadCurve15Min(site_id=site_id, start_time=r.start.to_pydatetime(),
                           end_time=r.end.to_pydatetime(), interval_no=int(r.interval),
                           energy_mwh=float(r.mwh), avg_power_mw=float(r.mw),
                           observatii=None if pd.isna(r.note) else str(r.note))
            for r in raw.itertuples()]


def _sim_curve(tel: pd.DataFrame) -> list:
    # local wall-clock time, like the PPC file, so the hourly profile reads naturally
    t = tel.timestamp.dt.tz_convert(TZ)
    start = t.dt.tz_localize(None)
    nr = (start.dt.hour * 4 + start.dt.minute // 15 + 1).astype(int)
    return [LoadCurve15Min(site_id=sid, start_time=s.to_pydatetime(),
                           end_time=(s + pd.Timedelta(minutes=15)).to_pydatetime(),
                           interval_no=int(n), energy_mwh=float(kw) * 0.25 / 1000,
                           avg_power_mw=float(kw) / 1000, observatii=None)
            for sid, s, n, kw in zip(tel.site_id, start, nr, tel.load_kw)]


def seed(ml_out: Path, excel: Path | None):
    sites = pd.read_csv(ml_out / "sites.csv")
    tel = pd.read_csv(ml_out / "telemetry.csv", parse_dates=["timestamp"])
    exp = pd.read_csv(ml_out / "expected.csv", parse_dates=["timestamp"])
    alerts = pd.read_csv(ml_out / "alerts.csv")
    now = tel.timestamp.max()

    Base.metadata.drop_all(bind=engine)          # full refresh
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        for i, s in enumerate(sites.itertuples()):
            st, ex = tel[tel.site_id == s.site_id], exp[exp.site_id == s.site_id]
            site_alerts = alerts[alerts.site_id == s.site_id]
            last = st[st.timestamp == st.timestamp.max()].iloc[0]
            expected_now = ex[ex.timestamp == last.timestamp].expected_kw
            db.add(Site(site_id=s.site_id, name=s.name, status=_status(site_alerts),
                        sla_availability_pct=_availability(st, ex, s.kwp)))
            db.add(Inverter(inverter_id=f"{s.site_id}-INV1", site_id=s.site_id,
                            name="Inverter 1", brand=BRANDS[i % len(BRANDS)],
                            rated_power_kw=float(s.inverter_kw),
                            current_power_kw=round(float(last.pv_kw), 3),
                            expected_power_kw=round(float(expected_now.iloc[0]), 3)
                            if len(expected_now) else 0.0,
                            status=_status(site_alerts),
                            battery_soc_pct=None if pd.isna(last.battery_soc) else float(last.battery_soc),
                            gsm_signal_dbm=None))
        for a in alerts.itertuples():
            db.add(Alert(alert_id=f"{a.site_id}-{a.alert_id}", site_id=a.site_id,
                         inverter_id=f"{a.site_id}-INV1", severity=a.severity,
                         message=f"{a.message} {a.action}", estimated_loss_kwh=float(a.lost_kwh),
                         resolved=0 if bool(a.ongoing) else 1))
        db.add_all(_sim_curve(tel))

        if excel is not None:
            db.add(Site(site_id="C01", name="Real PPC consumer (load curve)", status="OK",
                        sla_availability_pct=None))
            db.add_all(_real_curve(excel, "C01"))
        db.commit()
    finally:
        db.close()
    print(f"Seeded {len(sites)} simulated sites, {len(alerts)} alerts, "
          f"{len(tel)} simulated load rows (data up to {now:%Y-%m-%d %H:%M} UTC)"
          + (f", and C01 from {excel.name}" if excel else ", no real curve (Excel not found)"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ml-out", type=Path, default=ML_OUT)
    ap.add_argument("--excel", type=Path, default=None)
    args = ap.parse_args()
    if not (args.ml_out / "sites.csv").exists():
        raise SystemExit(f"No ML output in {args.ml_out}. Run `python run_demo.py` in ml_pipeline first.")
    excel = args.excel or next((p for p in EXCEL_CANDIDATES if p.exists()), None)
    seed(args.ml_out, excel)


if __name__ == "__main__":
    main()
