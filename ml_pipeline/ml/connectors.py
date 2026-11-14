"""Read-only connectors: the platform works ALONGSIDE the customer's existing inverters and
energy management systems and never replaces or controls them (brief constraint).

Every connector returns the same data contract the rest of the code uses:
    timestamp (UTC), site_id, pv_kw, load_kw, battery_kw, battery_soc, grid_kw
(missing columns are simply absent - downstream code only uses what exists).

Three ways data leaves the equipment (organisers' note + mentor, phase 1 / phase 2):
  1. VendorCloudConnector  - the maker's cloud, read through its API (phase 1).
                             Each maker names fields differently, so a per-vendor mapping
                             turns their JSON into our contract.
  2. SunSpecModbus         - read the inverter on site over Modbus TCP, using the public
                             SunSpec register map (phase 2: parameters the cloud does not show,
                             e.g. reactive/apparent power, cabinet temperature, fault state).
  3. ExcelLoadCurve        - the distributor's 15-minute load curve file (ml/real_data.py).
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .real_data import load_curve

CONTRACT = ["timestamp", "site_id", "pv_kw", "load_kw", "battery_kw", "battery_soc", "grid_kw"]


# ------------------------------------------------------------------ 1. vendor cloud

class VendorCloudConnector:
    """Map a maker-cloud JSON payload (list of points) to the contract.

    mapping: contract column -> (vendor field, multiplier). Example for a cloud that reports
    watts:  {"timestamp": ("time", None), "pv_kw": ("pv_power_w", 0.001), ...}
    The HTTP call itself is vendor specific (auth, paging); pass the decoded JSON here.
    """

    def __init__(self, site_id: str, mapping: dict, tz: str = "UTC"):
        self.site_id, self.mapping, self.tz = site_id, mapping, tz

    def parse(self, points) -> pd.DataFrame:
        if isinstance(points, (str, Path)):
            points = json.loads(Path(points).read_text())
        raw = pd.DataFrame(points)
        out = pd.DataFrame({"site_id": self.site_id}, index=raw.index)
        for col, (field, mult) in self.mapping.items():
            if field not in raw:
                continue                                   # this maker does not report it
            if col == "timestamp":
                ts = pd.to_datetime(raw[field])
                out[col] = (ts.dt.tz_localize(self.tz) if ts.dt.tz is None else ts).dt.tz_convert("UTC")
            else:
                out[col] = pd.to_numeric(raw[field], errors="coerce") * (mult or 1.0)
        if {"load_kw", "pv_kw"} <= set(out) and "grid_kw" not in out:
            out["grid_kw"] = out.load_kw - out.pv_kw + out.get("battery_kw", 0.0)
        cols = [c for c in CONTRACT if c in out]
        return out[cols].sort_values("timestamp").reset_index(drop=True)


# ------------------------------------------------------------------ 2. SunSpec over Modbus

SUNSPEC_BASE = 40000                 # standard start of the SunSpec map ("SunS" marker)
INVERTER_MODELS = {101, 102, 103}    # single phase, split phase, three phase
STATES = {1: "off", 2: "sleeping", 3: "starting", 4: "producing (MPPT)", 5: "throttled",
          6: "shutting down", 7: "FAULT", 8: "standby"}

# offset inside the inverter model block (after the ID and length registers)
_POINTS = {  # name: (offset, type, scale-factor name or None)
    "A": (0, "u16", "A_SF"), "PhVphA": (8, "u16", "V_SF"),
    "W": (12, "i16", "W_SF"), "Hz": (14, "u16", "Hz_SF"), "VA": (16, "i16", "VA_SF"),
    "VAr": (18, "i16", "VAr_SF"), "PF": (20, "i16", "PF_SF"), "WH": (22, "acc32", "WH_SF"),
    "DCW": (29, "i16", "DCW_SF"), "TmpCab": (31, "i16", "Tmp_SF"), "St": (36, "enum", None),
}
_SF = {"A_SF": 4, "V_SF": 11, "W_SF": 13, "Hz_SF": 15, "VA_SF": 17, "VAr_SF": 19,
       "PF_SF": 21, "WH_SF": 24, "DCW_SF": 30, "Tmp_SF": 35}


def _i16(v):
    return v - 0x10000 if v >= 0x8000 else v


def decode_sunspec_inverter(regs) -> dict:
    """Decode one SunSpec inverter model block (registers after ID and L) into
    engineering units. Unimplemented points (0x8000 / 0xFFFF) come back as None."""
    out = {}
    for name, (off, typ, sf_name) in _POINTS.items():
        raw = regs[off]
        if typ == "acc32":
            raw = (regs[off] << 16) | regs[off + 1]
            missing = raw == 0
        elif typ == "i16":
            missing, raw = raw == 0x8000, _i16(raw)
        else:
            missing = raw == 0xFFFF
        if missing:
            out[name] = None
            continue
        if sf_name is None:
            out[name] = STATES.get(raw, f"vendor state {raw}") if name == "St" else raw
            continue
        sf = _i16(regs[_SF[sf_name]])
        out[name] = round(raw * 10.0 ** sf, 4)
    return out


class SunSpecModbus:
    """Poll an inverter on site (Modbus TCP, read-only). Needs `pip install pymodbus`
    and network access to the inverter - i.e. a small gateway at the client, or the GSM
    modem the mentor described for sites whose network PPC may not use."""

    def __init__(self, host: str, port: int = 502, unit: int = 1, site_id: str = "?"):
        self.host, self.port, self.unit, self.site_id = host, port, unit, site_id

    def poll(self) -> dict:
        from pymodbus.client import ModbusTcpClient     # imported only when used
        c = ModbusTcpClient(self.host, port=self.port)
        c.connect()
        try:
            hdr = c.read_holding_registers(SUNSPEC_BASE, count=2, slave=self.unit).registers
            if hdr != [0x5375, 0x6E53]:                  # "SunS"
                raise RuntimeError("no SunSpec map at 40000")
            addr = SUNSPEC_BASE + 2
            while True:                                   # walk the model list
                mid, length = c.read_holding_registers(addr, count=2, slave=self.unit).registers
                if mid == 0xFFFF:
                    raise RuntimeError("no inverter model found")
                if mid in INVERTER_MODELS:
                    regs = c.read_holding_registers(addr + 2, count=length, slave=self.unit).registers
                    return {"timestamp": pd.Timestamp.now(tz="UTC"), "site_id": self.site_id,
                            "model": mid, **decode_sunspec_inverter(regs)}
                addr += 2 + length
        finally:
            c.close()


def sunspec_to_contract(readings: list) -> pd.DataFrame:
    """Polled readings -> contract rows (pv_kw from AC power)."""
    df = pd.DataFrame(readings)
    df["pv_kw"] = df.W.astype(float) / 1000
    return df[["timestamp", "site_id", "pv_kw"] + [c for c in ("VAr", "VA", "TmpCab", "St") if c in df]]


# ------------------------------------------------------------------ 3. distributor file

class ExcelLoadCurve:
    def __init__(self, path, site_id: str = "C01"):
        self.path, self.site_id = path, site_id

    def read(self) -> pd.DataFrame:
        return load_curve(self.path, self.site_id)
