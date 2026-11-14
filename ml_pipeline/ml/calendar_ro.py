"""Romanian legal holidays, including the moving Orthodox ones (Good Friday, Easter,
Rusalii). The mentor's real load curve shows production stopping on exactly these days,
so the load forecast and the drop detector both need them."""
import datetime as dt
from functools import lru_cache


def orthodox_easter(year: int) -> dt.date:
    """Meeus' Julian algorithm, converted to the Gregorian calendar (valid 1900-2099)."""
    a, b, c = year % 4, year % 7, year % 19
    d = (19 * c + 15) % 30
    e = (2 * a + 4 * b - d + 34) % 7
    month, day = divmod(d + e + 114, 31)
    return dt.date(year, month, day + 1) + dt.timedelta(days=13)


def western_easter(year: int) -> dt.date:
    """Anonymous Gregorian algorithm. Not a Romanian holiday, but foreign-owned
    plants sometimes close on Easter Monday, so it is useful as a hint."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return dt.date(year, month, day + 1)


@lru_cache(maxsize=None)
def ro_holidays(year: int) -> dict:
    """date -> name, Romanian legal holidays (Codul muncii, art. 139)."""
    fixed = {
        (1, 1): "Anul Nou", (1, 2): "Anul Nou (a doua zi)",
        (1, 6): "Boboteaza", (1, 7): "Sf. Ioan",
        (1, 24): "Ziua Unirii", (5, 1): "Ziua Muncii", (6, 1): "Ziua Copilului",
        (8, 15): "Adormirea Maicii Domnului", (11, 30): "Sf. Andrei",
        (12, 1): "Ziua Nationala", (12, 25): "Craciun", (12, 26): "Craciun (a doua zi)",
    }
    out = {dt.date(year, m, d): n for (m, d), n in fixed.items()}
    e = orthodox_easter(year)
    out[e - dt.timedelta(days=2)] = "Vinerea Mare"
    out[e] = "Pastele"
    out[e + dt.timedelta(days=1)] = "Pastele (a doua zi)"
    out[e + dt.timedelta(days=49)] = "Rusalii"
    out[e + dt.timedelta(days=50)] = "Rusalii (a doua zi)"
    return out


def holiday_name(day) -> str:
    day = day.date() if hasattr(day, "date") else day
    return ro_holidays(day.year).get(day, "")


def is_holiday(day) -> bool:
    return bool(holiday_name(day))
