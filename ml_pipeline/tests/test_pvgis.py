"""PVGIS parsing and the monthly check, on a payload shaped like the real API answer."""
import io
import json
import sys
from pathlib import Path
from unittest import mock

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml import pvgis  # noqa: E402

FAKE = {"outputs": {"monthly": {"fixed": [
    {"month": m, "E_d": 10.0 + m, "E_m": 30 * (10.0 + m), "H(i)_d": 3.0, "SD_m": 20.0}
    for m in range(1, 13)]}, "totals": {"fixed": {"E_y": 9000.0}}}}
SITE = {"site_id": "S01", "lat": 44.5, "lon": 26.1, "kwp": 8.0, "tilt": 30, "azimuth": 0}


def test_fetch_and_check(tmp_path=Path("/tmp")):
    with mock.patch("urllib.request.urlopen",
                    return_value=io.BytesIO(json.dumps(FAKE).encode())):
        df = pvgis.load_or_fetch(pd.DataFrame([SITE]), cache=tmp_path / "pv_cache_test.json")
    assert len(df) == 12 and df[df.month == 11].E_d.iloc[0] == 21.0
    t = pd.date_range("2026-11-01", periods=96 * 3, freq="15min", tz="Europe/Bucharest").tz_convert("UTC")
    tel = pd.DataFrame({"timestamp": t, "site_id": "S01", "pv_kw": 1.0})   # 24 kWh/day
    chk = pvgis.monthly_check(tel, df)
    row = chk[chk.month == 11].iloc[0]
    assert round(row.pct_of_pvgis) == round(100 * 24 / 21.0) and not row.flag
    (tmp_path / "pv_cache_test.json").unlink()


if __name__ == "__main__":
    test_fetch_and_check()
    print("ok test_fetch_and_check")
