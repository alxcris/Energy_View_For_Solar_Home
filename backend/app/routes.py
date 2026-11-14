from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List

router = APIRouter(prefix="/api/v1", tags=["Energy & O&M"])

class SiteSummary(BaseModel):
    site_id: str
    name: str
    brand: str
    status: str
    sla_availability_pct: float
    current_power_kw: float
    expected_power_kw: float


class TelemetryPoint(BaseModel):
    timestamp: str
    active_power_kw: float
    expected_power_kw: float
    voltage_v: float
    current_a: float
    frequency_hz: float
    inverter_temp_c: float
    # Parametri optionali (apar doar la invertoarele care ii au)
    battery_soc_pct: Optional[float] = None
    gsm_signal_dbm: Optional[int] = None


class AlertItem(BaseModel):
    alert_id: str
    site_id: str
    severity: str
    message: str
    estimated_loss_kwh: float
    resolved: bool = False

MOCK_SITES = [
    SiteSummary(
        site_id="SITE-001",
        name="Hala Logistica Chitila",
        brand="Huawei",
        status="OK",
        sla_availability_pct=96.4,
        current_power_kw=42.5,
        expected_power_kw=43.0,
    ),
    SiteSummary(
        site_id="SITE-002",
        name="Depozit Otopeni",
        brand="Fronius",
        status="CRITICAL",
        sla_availability_pct=88.5,
        current_power_kw=18.2,
        expected_power_kw=31.0,
    ),
]

@router.get("/sites", response_model=List[SiteSummary])
def get_sites():
    # Returneaza toate instalatiile unificate indiferent de producator
    return MOCK_SITES


@router.get("/sites/{site_id}/telemetry", response_model=List[TelemetryPoint])
def get_site_telemetry(site_id: str):
    # Returneaza productia reala vs asteptata si parametrii disponibili.
    if site_id not in {s.site_id for s in MOCK_SITES}:
        raise HTTPException(status_code=404, detail="Site not found")

    if site_id == "SITE-001":
        # Huawei cu baterie si GSM
        return [
            TelemetryPoint(
                timestamp="2026-11-14T12:00:00",
                active_power_kw=42.5,
                expected_power_kw=43.0,
                voltage_v=231.4,
                current_a=61.2,
                frequency_hz=50.01,
                inverter_temp_c=41.2,
                battery_soc_pct=84.0,
                gsm_signal_dbm=-68,
            )
        ]

    # Fronius fara baterie (parametrii optionali raman None)
    return [
        TelemetryPoint(
            timestamp="2026-11-14T12:00:00",
            active_power_kw=18.2,
            expected_power_kw=31.0,
            voltage_v=229.8,
            current_a=26.4,
            frequency_hz=49.98,
            inverter_temp_c=54.7,
        )
    ]


@router.get("/alerts", response_model=List[AlertItem])
def get_alerts():
    # Alerte timpurii O&M cand productia scade sub asteptari
    return [
        AlertItem(
            alert_id="ALT-101",
            site_id="SITE-002",
            severity="CRITICAL",
            message="Productie cu 41% sub estimatul meteo (18.2 kW vs 31.0 kW) - posibil string defect.",
            estimated_loss_kwh=38.4,
            resolved=False,
        )
    ]