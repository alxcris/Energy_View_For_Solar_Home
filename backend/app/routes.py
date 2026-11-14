import json
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, extract
from app.db.database import get_db, Site, LoadCurve15Min, Alert
from app.schemas import RecommendationResponse

router = APIRouter(prefix="/api/v1", tags=["Energy Recommendations"])

AI_ADVISOR_URL = "http://127.0.0.1:8001/recommend"
# what the ML pipeline computed per site (nudges in lei, best window, battery plan)
ML_CUSTOMER_JSON = Path(__file__).resolve().parents[2] / "ml_pipeline" / "out" / "customer.json"


def _fallback_recommendations(site_id: str, site_context: dict) -> list:
    """Used when the AI advisor is down: ML nudges first, then the rule-based suggestions."""
    recs = []
    if ML_CUSTOMER_JSON.exists():
        info = json.loads(ML_CUSTOMER_JSON.read_text()).get(site_id, {})
        recs += [n["text"] for n in info.get("nudges", [])]
        recs += info.get("tips", [])
        recs += info.get("dispatch_texts", [])
        if info.get("benchmark", {}).get("text"):
            recs.append(info["benchmark"]["text"])
    recs += site_context.get("actionable_suggestions", [])
    return [r for r in recs if isinstance(r, str) and r.strip()]

@router.get("/sites/{site_id}/recommendations", response_model=RecommendationResponse)
async def get_energy_recommendations(site_id: str, db: Session = Depends(get_db)):
    site_context = get_recommendation_context(site_id, db)

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(AI_ADVISOR_URL, json={"context": site_context})
            resp.raise_for_status()
            ai_response = resp.json()
    except httpx.HTTPStatusError as exc:
        fallback = _fallback_recommendations(site_id, site_context)
        if fallback:
            return RecommendationResponse(site_id=site_id, recommendations=fallback,
                                          summary_data={**site_context, "source": "ml_fallback"})
        raise HTTPException(
            status_code=502,
            detail="Serviciul de recomandari a raspuns cu o eroare.",
        ) from exc
    except httpx.RequestError as exc:
        fallback = _fallback_recommendations(site_id, site_context)
        if fallback:
            return RecommendationResponse(site_id=site_id, recommendations=fallback,
                                          summary_data={**site_context, "source": "ml_fallback"})
        raise HTTPException(
            status_code=503,
            detail="Serviciul de recomandari nu este disponibil momentan.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail="Serviciul de recomandari a trimis un raspuns invalid.",
        ) from exc

    advice_list = ai_response.get("recommendations") if isinstance(ai_response, dict) else None
    if (
        not isinstance(advice_list, list)
        or not advice_list
        or any(not isinstance(advice, str) or not advice.strip() for advice in advice_list)
    ):
        raise HTTPException(
            status_code=502,
            detail="Serviciul de recomandari a trimis recomandari intr-un format invalid.",
        )

    return RecommendationResponse(
        site_id=site_id,
        recommendations=advice_list,
        summary_data=site_context,
    )

@router.get("/sites")
def get_sites(db: Session = Depends(get_db)):
    sites = db.query(Site).all()
    return [
        {
            "site_id": s.site_id,
            "name": s.name,
            "status": s.status,
            "sla_availability_pct": s.sla_availability_pct,
            "total_current_power_kw": round(sum(i.current_power_kw for i in s.inverters), 2),
            "total_expected_power_kw": round(sum(i.expected_power_kw for i in s.inverters), 2),
            "inverters": [
                {
                    "inverter_id": inv.inverter_id,
                    "name": inv.name,
                    "brand": inv.brand,
                    "status": inv.status,
                    "current_power_kw": inv.current_power_kw,
                    "expected_power_kw": inv.expected_power_kw,
                    "battery_soc_pct": inv.battery_soc_pct,
                    "gsm_signal_dbm": inv.gsm_signal_dbm,
                }
                for inv in s.inverters
            ],
        }
        for s in sites
    ]


@router.get("/alerts")
def get_alerts(db: Session = Depends(get_db)):
    return db.query(Alert).filter(Alert.resolved == 0).all()


@router.get("/sites/{site_id}/telemetry")
def get_site_telemetry(site_id: str, limit: int = 96, db: Session = Depends(get_db)):
    """Ultimele N intervale la 15 min (default 96 = ultimele 24h) din curba PPC."""
    rows = (
        db.query(LoadCurve15Min)
        .filter(LoadCurve15Min.site_id == site_id)
        .order_by(LoadCurve15Min.start_time.desc())
        .limit(limit)
        .all()
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Nu exista date pentru acest site.")

    return [
        {
            "timestamp": r.start_time.isoformat(),
            "consumption_kw": round(r.avg_power_mw * 1000, 2),
            "energy_kwh": round(r.energy_mwh * 1000, 3),
        }
        for r in reversed(rows)
    ]


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
    """Agregare lunara (MWh) pentru graficele de istoric / sezonalitate."""
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
def get_recommendation_context(site_id: str, db: Session = Depends(get_db)):
    """
    Context pentru generarea recomandarilor de eficienta energetica:
    identifica varfurile de sarcina, orele cu consum mediu mai redus
    si lunile problematice pe baza curbei de sarcina PPC. Datele de consum
    singure nu sunt suficiente pentru a deduce productia sau surplusul solar.
    """
    site = db.query(Site).filter_by(site_id=site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    hourly = get_hourly_profile(site_id, db)
    monthly = get_monthly_summary(site_id, db)

    sorted_by_load = sorted(hourly, key=lambda x: x["avg_power_kw"], reverse=True)
    top_peak_hours = sorted_by_load[:3]

    daytime_hours = [h for h in hourly if 9 <= h["hour"] <= 16]
    lowest_consumption_hours = sorted(daytime_hours, key=lambda x: x["avg_power_kw"])[:3]

    night_hours = [h["avg_power_kw"] for h in hourly if 2 <= h["hour"] <= 5]
    night_baseload_kw = round(sum(night_hours) / len(night_hours), 2) if night_hours else None

    peak_month = max(monthly, key=lambda x: x["total_mwh"]) if monthly else None
    lowest_month = min(monthly, key=lambda x: x["total_mwh"]) if monthly else None
    total_period_mwh = round(sum(m["total_mwh"] for m in monthly), 2)

    active_alerts = db.query(Alert).filter_by(site_id=site_id, resolved=0).all()

    actionable_suggestions = []
    if top_peak_hours and lowest_consumption_hours:
        peak_hour = top_peak_hours[0]
        lower_load_hour = lowest_consumption_hours[0]
        actionable_suggestions.append(
            f"Consumul mediu al site-ului este {peak_hour['avg_power_kw']} kW la "
            f"{peak_hour['hour']}:00 si {lower_load_hour['avg_power_kw']} kW la "
            f"{lower_load_hour['hour']}:00. Verifica daca unele consumuri flexibile "
            "pot fi mutate catre orele cu sarcina mai mica."
        )
    if night_baseload_kw is not None:
        actionable_suggestions.append(
            f"Consumul mediu observat intre orele 02:00 si 05:00 este {night_baseload_kw} kW. "
            "Verifica daca echipamentele necritice raman pornite in afara programului."
        )

    return {
        "site_id": site.site_id,
        "site_name": site.name,
        "inverters": [
            {
                "name": inv.name,
                "brand": inv.brand,
                "status": inv.status,
                "current_power_kw": inv.current_power_kw,
                "expected_power_kw": inv.expected_power_kw,
            }
            for inv in site.inverters
        ],
        "total_period_consumption_mwh": total_period_mwh,
        "night_baseload_kw": night_baseload_kw,
        "top_peak_hours_to_reduce": top_peak_hours,
        "lowest_consumption_hours_for_load_shifting": lowest_consumption_hours,
        "highest_consumption_month": peak_month,
        "lowest_consumption_month": lowest_month,
        "active_alerts": [a.message for a in active_alerts],
        "actionable_suggestions": actionable_suggestions,
    }