"""Loader for real 15-minute load curves in the distributor's Excel format
("Curba de sarcina la 15 min", sheet "Curbe la 15 min").

Returns the same contract as the simulator, so everything downstream works on it:
    timestamp (UTC, tz-aware), site_id, load_kw

Things the file itself documents (sheet "Info") and that we handle here:
  - timestamps are local time (Europe/Bucharest). On the autumn DST change the
    03:00-04:00 hour appears twice; the "Observatii" column says which copy is
    summer time (EEST) and which is winter time (EET).
  - the spring DST hour does not exist and is simply missing.
  - the source is HOURLY data split into 4 equal quarter-hours, so there is no
    real information inside an hour. We keep 15-min rows for the contract but
    the analysis works at hourly resolution.
"""
import numpy as np
import pandas as pd

SHEET = "Curbe la 15 min"


def load_curve(path, site_id: str = "C01") -> pd.DataFrame:
    raw = pd.read_excel(path, sheet_name=SHEET)
    raw.columns = ["start", "end", "interval", "mwh", "mw", "note"][: len(raw.columns)]
    note = raw.get("note", pd.Series("", index=raw.index)).fillna("").astype(str)

    # DST: rows flagged as the first appearance of the repeated hour are summer time
    ambiguous = np.where(note.str.contains("EEST|ora de var", case=False), True,
                         np.where(note.str.contains("EET|ora de iarn", case=False), False, True))
    local = pd.DatetimeIndex(raw.start).tz_localize("Europe/Bucharest", ambiguous=ambiguous,
                                                     nonexistent="shift_forward")
    df = pd.DataFrame({
        "timestamp": local.tz_convert("UTC"),
        "site_id": site_id,
        "load_kw": (raw.mwh.astype(float) * 1000 * 4).round(3),   # MWh per 15 min -> kW
    })
    df = df.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    df.attrs["resolution"] = "hourly, split evenly into 15 min"
    return df


def hourly(df: pd.DataFrame) -> pd.DataFrame:
    """Back to the real (hourly) resolution: mean kW per UTC hour."""
    h = df.assign(timestamp=df.timestamp.dt.floor("h"))
    return h.groupby(["site_id", "timestamp"], as_index=False).load_kw.mean()
