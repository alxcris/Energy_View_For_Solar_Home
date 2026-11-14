"""Run: python -m pytest tests  (or: python tests/test_connectors.py)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml.connectors import (VendorCloudConnector, decode_sunspec_inverter,  # noqa: E402
                           sunspec_to_contract)


def _regs():
    r = [0xFFFF] * 50
    r[0], r[4] = 1234, 0xFFFE            # A = 1234 * 10^-2 = 12.34 A
    r[8], r[11] = 2301, 0xFFFF           # V = 2301 * 10^-1 = 230.1 V
    r[12], r[13] = 4520, 0               # W = 4520 W
    r[14], r[15] = 5000, 0xFFFE          # Hz = 50.00
    r[16], r[17] = 4600, 0               # VA
    r[18], r[19] = (-350) & 0xFFFF, 0    # VAr = -350 (signed)
    r[20], r[21] = 98, 0xFFFE            # PF = 0.98
    r[22], r[23], r[24] = 0x0001, 0x86A0, 0   # WH = 100000 Wh (acc32)
    r[29], r[30] = 4700, 0               # DCW
    r[31], r[35] = 412, 0xFFFF           # TmpCab = 41.2 C
    r[36] = 4                            # MPPT
    return r


def test_sunspec_decode():
    d = decode_sunspec_inverter(_regs())
    assert d["W"] == 4520 and d["VAr"] == -350 and d["WH"] == 100000
    assert abs(d["A"] - 12.34) < 1e-9 and abs(d["Hz"] - 50.0) < 1e-9 and abs(d["PF"] - 0.98) < 1e-9
    assert abs(d["TmpCab"] - 41.2) < 1e-9 and d["St"] == "producing (MPPT)"


def test_sunspec_fault_and_missing():
    r = _regs()
    r[36], r[18] = 7, 0x8000             # FAULT state, VAr not implemented
    d = decode_sunspec_inverter(r)
    assert d["St"] == "FAULT" and d["VAr"] is None


def test_sunspec_to_contract():
    df = sunspec_to_contract([{"timestamp": "2026-11-14T10:00Z", "site_id": "S01",
                               **decode_sunspec_inverter(_regs())}])
    assert abs(df.pv_kw.iloc[0] - 4.52) < 1e-9


def test_vendor_cloud_mapping():
    points = [{"time": "2026-11-14 10:00", "pv_power_w": 3000, "load_power_w": 1200, "soc": 55},
              {"time": "2026-11-14 10:15", "pv_power_w": 3200, "load_power_w": 900, "soc": 58}]
    con = VendorCloudConnector("S01", {"timestamp": ("time", None), "pv_kw": ("pv_power_w", 0.001),
                                       "load_kw": ("load_power_w", 0.001),
                                       "battery_soc": ("soc", None),
                                       "battery_kw": ("battery_power_w", 0.001)},  # not reported
                               tz="Europe/Bucharest")
    df = con.parse(points)
    assert list(df.columns) == ["timestamp", "site_id", "pv_kw", "load_kw", "battery_soc", "grid_kw"]
    assert str(df.timestamp.iloc[0]) == "2026-11-14 08:00:00+00:00"     # local -> UTC
    assert abs(df.grid_kw.iloc[0] - (-1.8)) < 1e-9                      # exporting 1.8 kW


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
