from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, extract
from app.database import get_db, Site, LoadCurve15Min, Alert

router = APIRouter(prefix="/api/v1", tags=["Energy, Analytics & Chatbot"])

@router.get("/sites")
def get_sites(db: Session = Depends(get_db)):
    return db.query(Site).all()

@router.get("/alerts")
def get_alerts(db: Session = Depends(get_db)):
    return db.query(Alert).filter(Alert.resolved == 0).all()


@router.get("/sites/{site_id}/hourly-profile")
def get_hourly_profile(site_id: str, db: Session = Depends(get_db)):
    """Profilul mediu orar (0-23) calculat din curba de sarcina la 15 min."""
    rows = (
        db.query(
            extract("hour", LoadCurve15Min.start_time).label("hour"),
            func.avg(LoadCurve15Min.avg_power_mw).label("avg_mw"),
        )
        .filter(LoadCurve15Min.site_id == site_id)
        .group_by("hour")
        .order_by("hour")
        .all()
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Nu exista curba de sarcina pentru acest site.")

    return [
        {
            "hour": int(r.hour),
            "avg_power_mw": round(r.avg_mw, 4),
            "avg_power_kw": round(r.avg_mw * 1000, 2),
        }
        for r in rows
    ]


@router.get("/sites/{site_id}/monthly-summary")
def get_monthly_summary(site_id: str, db: Session = Depends(get_db)):
    """Agregare lunara (MWh) pentru graficele de istoric / Year-over-Year."""
    rows = (
        db.query(
            func.strftime("%Y-%m", LoadCurve15Min.start_time).label("month"),
            func.sum(LoadCurve15Min.energy_mwh).label("total_mwh"),
        )
        .filter(LoadCurve15Min.site_id == site_id)
        .group_by("month")
        .order_by("month")
        .all()
    )
    return [{"month": r.month, "total_mwh": round(r.total_mwh, 3)} for r in rows]


@router.get("/sites/{site_id}/ai-context")
def get_chatbot_context(site_id: str, db: Session = Depends(get_db)):
    """
    Endpoint dedicat Chatbot-ului AI: extrage automat varfurile de consum,
    ferestrele optime de consum (surplus solar) si alertele active din SQLite.
    """
    site = db.query(Site).filter_by(site_id=site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    hourly = get_hourly_profile(site_id, db)
    daytime = [h for h in hourly if 8 <= h["hour"] <= 18]
    best_solar_window = min(daytime, key=lambda x: x["avg_power_kw"]) if daytime else None
    peak_hour = max(hourly, key=lambda x: x["avg_power_kw"]) if hourly else None

    total_mwh = (
        db.query(func.sum(LoadCurve15Min.energy_mwh))
        .filter(LoadCurve15Min.site_id == site_id)
        .scalar()
        or 0.0
    )
    active_alerts = db.query(Alert).filter_by(site_id=site_id, resolved=0).all()

    return {
        "site_name": site.name,
        "inverter_brand": site.brand,
        "sla_availability_pct": site.sla_availability_pct,
        "total_annual_consumption_mwh": round(total_mwh, 2),
        "peak_consumption_hour": peak_hour,
        "best_hour_to_shift_load": best_solar_window,
        "active_alerts": [a.message for a in active_alerts],
        "recommendation_hint": (
            f"Consumul scade la {best_solar_window['avg_power_kw']} kW in jurul orei "
            f"{best_solar_window['hour']}:00 — moment optim pentru a porni consumatori mari pe energie solara."
            if best_solar_window
            else ""
        ),
    }