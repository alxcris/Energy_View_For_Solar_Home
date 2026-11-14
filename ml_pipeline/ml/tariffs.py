"""What a kWh costs the customer, at every moment. All prices in the project come from here.

Two kinds of contract:
    FixedTariff      same price at every hour (most household contracts)
    TimeOfUseTariff  reduced price in fixed hours: PPC Ore Smart+ by default (weekday
                     nights, weekends, weekday midday from March to October)

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
    """Reduced price in fixed hourly intervals, peak price otherwise. Defaults follow the
    PPC Ore Smart+ household offer (PPC press release, 18 March 2026):
      - every weekday night, 00:00-05:59, all year
      - all day Saturday and Sunday, all year
      - weekday midday 11:00-14:59, March to October (the solar hours; same interval as
        PPC Ore Smart and Ore Smart PRO)
    Legal holidays are not in the offer, so they are off by default.

    Prices are final prices (energy + network tariffs + VAT), and they depend on the
    distribution zone:
      - reduced: "from 0.98 lei/kWh" (PPC), active energy 0.348 lei/kWh
      - standard: ESTIMATE. Active energy is 0.823 lei/kWh, 0.475 more than reduced;
        with 21% VAT that is ~0.57 lei more, so ~1.55 lei/kWh final.
    Intervals are [start, end) in local hours: (0, 6) means 00:00-05:59.
    """

    def __init__(self, offpeak_lei_kwh: float = 0.98, peak_lei_kwh: float = 1.55,
                 night=(0, 6), midday=(11, 15), midday_months=range(3, 11),
                 weekend_offpeak: bool = True, holidays_offpeak: bool = False,
                 name: str = "PPC Ore Smart+"):
        self.offpeak, self.peak = float(offpeak_lei_kwh), float(peak_lei_kwh)
        self.night, self.midday, self.midday_months = night, midday, set(midday_months)
        self.weekend_offpeak, self.holidays_offpeak, self.name = weekend_offpeak, holidays_offpeak, name

    def offpeak_mask(self, times: pd.DatetimeIndex) -> np.ndarray:
        local = pd.DatetimeIndex(times).tz_convert(TZ)
        h = local.hour
        mask = (h >= self.night[0]) & (h < self.night[1])
        if self.midday:
            in_season = np.isin(local.month, list(self.midday_months))
            mask |= in_season & (h >= self.midday[0]) & (h < self.midday[1])
        if self.weekend_offpeak:
            mask |= local.dayofweek >= 5
        if self.holidays_offpeak:
            mask |= np.array([is_holiday(d) for d in local.date], dtype=bool)
        return np.asarray(mask)

    def price(self, times: pd.DatetimeIndex) -> np.ndarray:
        return np.where(self.offpeak_mask(times), self.offpeak, self.peak)

    def __repr__(self):
        return (f"{self.name}: reduced {self.offpeak:.2f} lei/kWh (weekday nights "
                f"{self.night[0]:02d}:00-{self.night[1] - 1:02d}:59, weekends, weekday "
                f"{self.midday[0]:02d}:00-{self.midday[1] - 1:02d}:59 Mar-Oct), "
                f"otherwise {self.peak:.2f}")


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
