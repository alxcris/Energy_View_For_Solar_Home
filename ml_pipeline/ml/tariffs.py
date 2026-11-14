"""What a kWh costs the customer, at every moment. All prices in the project come from here.

Two kinds of contract:
    FixedTariff      same price at every hour (most household contracts)
    TimeOfUseTariff  cheaper at night, on weekends and on legal holidays (dynamic offers
                     such as PPC Ore Smart+)

Every function that needs a price takes `tariff=`: a Tariff, a plain number (lei/kWh, treated
as a fixed price) or None (the default fixed price below).
"""
import numpy as np
import pandas as pd

from .calendar_ro import is_holiday

TZ = "Europe/Bucharest"

# PPC fixed-price household offer, final price incl. network tariffs and VAT:
# 1.29-1.37 lei/kWh depending on the distribution zone (economica.net, 2026).
RETAIL_LEI_KWH = 1.30

# ASSUMPTION: what an exported kWh is worth to a prosumer. Replace with the
# compensation price from the customer's contract.
FEED_IN_LEI_KWH = 0.30


class FixedTariff:
    def __init__(self, lei_kwh: float = RETAIL_LEI_KWH, name: str = "fixed"):
        self.lei_kwh, self.name = float(lei_kwh), name

    def price(self, times: pd.DatetimeIndex) -> np.ndarray:
        return np.full(len(times), self.lei_kwh)

    def __repr__(self):
        return f"FixedTariff({self.lei_kwh:.2f} lei/kWh)"


class TimeOfUseTariff:
    """Off-peak at night, all weekend and on Romanian legal holidays, peak otherwise.

    The defaults are ILLUSTRATIVE: PPC Ore Smart+ advertises final prices from 0.98 lei/kWh
    with reduced prices at night and on weekends, but the exact hours and the peak price
    must come from the customer's contract.
    """

    def __init__(self, offpeak_lei_kwh: float = 0.98, peak_lei_kwh: float = 1.40,
                 offpeak_from_h: int = 22, offpeak_to_h: int = 7, name: str = "time-of-use"):
        self.offpeak, self.peak = float(offpeak_lei_kwh), float(peak_lei_kwh)
        self.from_h, self.to_h, self.name = offpeak_from_h, offpeak_to_h, name

    def price(self, times: pd.DatetimeIndex) -> np.ndarray:
        local = pd.DatetimeIndex(times).tz_convert(TZ)
        night = (local.hour >= self.from_h) | (local.hour < self.to_h)
        offday = (local.dayofweek >= 5) | np.array([is_holiday(d) for d in local.date], dtype=bool)
        return np.where(night | offday, self.offpeak, self.peak)

    def __repr__(self):
        return (f"TimeOfUseTariff(off-peak {self.offpeak:.2f}, peak {self.peak:.2f} lei/kWh, "
                f"off-peak {self.from_h:02d}:00-{self.to_h:02d}:00 + weekends/holidays)")


def as_tariff(t=None):
    """Accept a Tariff, a number (fixed lei/kWh) or None (default fixed price)."""
    if t is None:
        return FixedTariff()
    if isinstance(t, (int, float)):
        return FixedTariff(t)
    return t


def price_at_local(tariff, day, start_h: float, hours: float) -> np.ndarray:
    """Prices for a run starting at local hour `start_h` on `day`, one value per 15 min."""
    start = pd.Timestamp(day).tz_localize(TZ) + pd.Timedelta(hours=start_h)
    times = pd.date_range(start, periods=max(int(round(hours * 4)), 1), freq="15min")
    return as_tariff(tariff).price(times.tz_convert("UTC"))
