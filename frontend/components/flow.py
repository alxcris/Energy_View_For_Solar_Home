"""The live energy flow: where the current actually goes, right now.

One picture answers the question the challenge is about - panels, inverter,
home, battery and grid, with the current drawn as moving pulses along each
line. Direction, speed and thickness come from the data:

    pv_kw       panels  -> inverter          (always this way)
    load_kw     inverter -> home             (always this way)
    battery_kw  > 0 charging  -> towards the battery
                < 0 discharging -> towards the inverter
    grid_kw     > 0 importing -> from the grid
                < 0 exporting -> towards the grid

Everything is SVG plus CSS animation (the styles live in components/theme.py),
so it works inside Streamlit with no extra component and no JavaScript, and it
stands still for anyone whose system asks for reduced motion.
"""

from __future__ import annotations

import html

import streamlit as st

from config import COLORS, UI

# geometry of the diagram, in viewBox units
VIEW = (880, 400)
BOX = (176, 104)
SOLAR_XY, BATTERY_XY = (24, 40), (24, 270)
HOME_XY, GRID_XY = (680, 40), (680, 270)
HUB = (440, 207, 58)  # cx, cy, r

PATHS = {
    "solar": "M 200,92 C 290,92 320,140 394,171",
    "battery": "M 200,322 C 290,322 320,274 394,243",
    "home": "M 486,171 C 560,140 590,92 680,92",
    "grid": "M 486,243 C 560,274 590,322 680,322",
}
PILLS = {"solar": (303, 120), "battery": (303, 294), "home": (577, 120), "grid": (577, 294)}

MIN_KW = 0.05  # below this we treat a line as idle


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _line(key: str, color: str, kw: float, reverse: bool, peak: float) -> str:
    """A track, plus a moving pulse when power is actually flowing."""
    path = PATHS[key]
    track = f'<path class="track" d="{path}"/>'
    if kw < MIN_KW:
        return track
    ratio = _clamp(kw / peak, 0.06, 1.0)
    width = 4 + 7 * ratio                      # thicker line = more kW
    speed = _clamp(2.3 - 1.75 * ratio, 0.55, 2.3)  # faster pulse = more kW
    rev = " rev" if reverse else ""
    return (
        track
        + f'<path class="beam" d="{path}" stroke="{color}" stroke-width="{width:.1f}"/>'
        + f'<path class="pulse{rev}" d="{path}" stroke="{color}" '
          f'stroke-width="{width * 0.55:.1f}" style="animation-duration:{speed:.2f}s"/>'
    )


def _pill(key: str, text: str, color: str) -> str:
    cx, cy = PILLS[key]
    width = 20 + 7.6 * len(text)
    return (f'<g><rect x="{cx - width / 2:.1f}" y="{cy - 13}" width="{width:.1f}" height="26" '
            f'rx="13" fill="{UI["card"]}" stroke="{color}" stroke-opacity=".4"/>'
            f'<text class="t-pill" x="{cx}" y="{cy + 5}" text-anchor="middle" fill="{color}">'
            f'{html.escape(text)}</text></g>')


def _node(xy: tuple[int, int], label: str, value: str, unit: str, sub: str,
          icon: str, state: str = "on") -> str:
    x, y = xy
    w, h = BOX
    cls = {"on": "box", "idle": "box", "off": "box off", "fault": "box fault"}[state]
    dim = ' opacity=".55"' if state in ("off", "idle") else ""
    return (
        f'<g{dim}>'
        f'<rect class="{cls}" x="{x}" y="{y}" width="{w}" height="{h}" rx="16"/>'
        f'<g transform="translate({x + 16},{y + 33})">{icon}</g>'
        f'<text class="t-label" x="{x + 68}" y="{y + 38}">{html.escape(label)}</text>'
        f'<text class="t-val" x="{x + 68}" y="{y + 64}">{html.escape(value)}'
        f'<tspan class="t-sub" dx="4">{html.escape(unit)}</tspan></text>'
        f'<text class="t-sub" x="{x + 68}" y="{y + 84}">{html.escape(sub)}</text>'
        f'</g>'
    )


# --- icons (38x38 each) ------------------------------------------------------

def _sun_icon(active: bool) -> str:
    rays = "".join(
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"/>' for x1, y1, x2, y2 in [
            (19, 0, 19, 5), (19, 33, 19, 38), (0, 19, 5, 19), (33, 19, 38, 19),
            (5.6, 5.6, 9.2, 9.2), (28.8, 28.8, 32.4, 32.4),
            (5.6, 32.4, 9.2, 28.8), (28.8, 9.2, 32.4, 5.6)])
    spin = ' class="rays"' if active else ""
    return (f'<g{spin} style="transform-origin:19px 19px">'
            f'<g stroke="{COLORS["solar"]}" stroke-width="2.1" stroke-linecap="round" '
            f'opacity="{0.9 if active else 0.4}">{rays}</g></g>'
            f'<circle cx="19" cy="19" r="8.6" fill="{COLORS["solar"]}" '
            f'opacity="{1 if active else 0.45}"/>')


def _battery_icon(soc: float | None, charging: bool) -> str:
    if soc is None:
        return (f'<rect x="9" y="5" width="20" height="29" rx="6" fill="{UI["card"]}" '
                f'stroke="{UI["faint"]}" stroke-width="2" stroke-dasharray="3 3"/>')
    fill_h = max(2.0, 25.0 * _clamp(soc, 0, 100) / 100)
    bolt = (f'<path d="M20 13 L13.5 22 h4.2 l-1 7 6.5-9.5h-4.2z" fill="{UI["card"]}" '
            f'class="glow"/>') if charging else ""
    return (f'<rect x="15.5" y="2" width="7" height="4" rx="1.5" fill="{COLORS["battery"]}"/>'
            f'<rect x="9" y="5" width="20" height="29" rx="6" fill="{UI["card"]}" '
            f'stroke="{COLORS["battery"]}" stroke-width="2"/>'
            f'<rect x="12" y="{7 + (25 - fill_h):.1f}" width="14" height="{fill_h:.1f}" rx="3.5" '
            f'fill="{COLORS["battery"]}"/>{bolt}')


def _home_icon(active: bool) -> str:
    glow = ' class="glow"' if active else ""
    return (f'<path d="M3 18.5 L19 4 L35 18.5 V35 H3 Z" fill="{UI["card"]}" '
            f'stroke="{COLORS["consumption"]}" stroke-width="2" stroke-linejoin="round"/>'
            f'<rect{glow} x="14.5" y="23" width="9" height="12" rx="1.6" '
            f'fill="{COLORS["consumption"]}"/>')


def _grid_icon() -> str:
    return (f'<g stroke="{COLORS["grid"]}" stroke-width="2" fill="none" stroke-linecap="round" '
            f'stroke-linejoin="round"><path d="M7 35 L19 4 L31 35"/><path d="M11.5 23 H26.5"/>'
            f'<path d="M14 15 H24"/><path d="M4 11 H34"/></g>')


def _hub(self_use: float) -> str:
    cx, cy, r = HUB
    inner = r - 8
    circ = 2 * 3.14159 * inner
    arc = circ * _clamp(self_use, 0, 1)
    return (
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{UI["card"]}" stroke="{UI["border"]}" '
        f'stroke-width="1.2"/>'
        f'<circle cx="{cx}" cy="{cy}" r="{inner}" fill="none" stroke="{UI["track"]}" stroke-width="6"/>'
        f'<circle class="ring-arc" cx="{cx}" cy="{cy}" r="{inner}" fill="none" '
        f'stroke="{UI["primary"]}" stroke-width="6" stroke-linecap="round" '
        f'stroke-dasharray="{arc:.1f} {circ - arc:.1f}" transform="rotate(-90 {cx} {cy})"/>'
        f'<path d="M{cx + 1} {cy - 36} L{cx - 9} {cy - 20} h6.5 l-1.6 11 L{cx + 9} {cy - 25} '
        f'h-6.5z" fill="{COLORS["solar"]}"/>'
        f'<text class="t-hub" x="{cx}" y="{cy + 14}" text-anchor="middle">'
        f'{self_use * 100:.0f}%</text>'
        f'<text class="t-hub-sub" x="{cx}" y="{cy + 30}" text-anchor="middle">SELF-USE</text>'
        f'<text class="t-label" x="{cx}" y="{cy - r - 14}" text-anchor="middle">Inverter</text>'
    )


def _narrative(pv: float, load: float, batt: float, grid: float, soc: float | None) -> str:
    """One sentence under the diagram, so nobody has to decode the picture."""
    if pv < MIN_KW:
        source = ("the battery is running the house" if batt < -MIN_KW
                  else "the house is running on the grid" if grid > MIN_KW
                  else "the house is using almost nothing")
        return f"The panels are not producing right now, so {source}."

    covered = min(pv, load)
    parts = [f"your panels are producing {pv:.1f} kW and cover "
             f"{covered / load * 100 if load > 0.01 else 100:.0f}% of what the house uses"]
    if batt > MIN_KW:
        parts.append(f"{batt:.1f} kW is going into the battery"
                     + (f" ({soc:.0f}% full)" if soc is not None else ""))
    elif batt < -MIN_KW:
        parts.append(f"the battery is adding {abs(batt):.1f} kW")
    if grid < -MIN_KW:
        parts.append(f"the surplus of {abs(grid):.1f} kW is sold to the grid")
    elif grid > MIN_KW:
        parts.append(f"the missing {grid:.1f} kW comes from the grid")
    text = ", ".join(parts) + "."
    return text[0].upper() + text[1:]


def energy_flow_html(pv_kw: float, load_kw: float, battery_kw: float | None,
                     soc: float | None, grid_kw: float, kwp: float = 0.0,
                     battery_kwh: float = 0.0, fault_note: str = "") -> str:
    """The whole diagram as one block of HTML."""
    pv = max(0.0, float(pv_kw or 0))
    load = max(0.0, float(load_kw or 0))
    grid = float(grid_kw or 0)
    has_battery = bool(battery_kwh) and battery_kw is not None and soc is not None
    batt = float(battery_kw or 0) if has_battery else 0.0
    peak = max(2.0, kwp or 0, pv, load, abs(grid), abs(batt))
    self_use = 1.0 if load <= 0.01 else _clamp((load - max(grid, 0.0)) / load, 0, 1)

    lines = (
        _line("solar", COLORS["solar"], pv, reverse=False, peak=peak)
        + _line("home", COLORS["consumption"], load, reverse=False, peak=peak)
        + _line("battery", COLORS["battery"], abs(batt), reverse=batt > 0, peak=peak)
        + _line("grid", COLORS["grid"], abs(grid), reverse=grid > 0, peak=peak)
    )

    pills = ""
    if pv >= MIN_KW:
        pills += _pill("solar", f"{pv:.1f} kW", COLORS["solar"])
    if load >= MIN_KW:
        pills += _pill("home", f"{load:.1f} kW", COLORS["consumption"])
    if abs(batt) >= MIN_KW:
        pills += _pill("battery", f"{abs(batt):.1f} kW", COLORS["battery"])
    if abs(grid) >= MIN_KW:
        pills += _pill("grid", f"{abs(grid):.1f} kW", COLORS["grid"])

    battery_state = ("off" if not has_battery
                     else "charging" if batt > MIN_KW
                     else "discharging" if batt < -MIN_KW else "idle")
    nodes = (
        _node(SOLAR_XY, "Solar panels", f"{pv:.1f}", "kW", f"of {kwp:.1f} kWp installed",
              _sun_icon(pv >= MIN_KW), "on" if pv >= MIN_KW else "idle")
        + _node(BATTERY_XY, "Battery",
                "none" if not has_battery else f"{soc:.0f}",
                "" if not has_battery else "%",
                "not installed" if not has_battery
                else {"charging": f"charging at {batt:.1f} kW",
                      "discharging": f"supplying {abs(batt):.1f} kW",
                      "idle": f"idle · {battery_kwh:.0f} kWh"}[battery_state],
                _battery_icon(soc if has_battery else None, battery_state == "charging"),
                "off" if not has_battery else "on")
        + _node(HOME_XY, "Your home", f"{load:.1f}", "kW",
                "using now" if load >= MIN_KW else "almost nothing",
                _home_icon(load >= MIN_KW), "on" if load >= MIN_KW else "idle")
        + _node(GRID_XY, "Grid", f"{abs(grid):.1f}", "kW",
                "importing" if grid > MIN_KW else "exporting" if grid < -MIN_KW else "balanced",
                _grid_icon(), "on" if abs(grid) >= MIN_KW else "idle")
    )

    legend = "".join(
        f'<span><i style="--c:{color}"></i>{label} <b>{value}</b></span>'
        for label, value, color in [
            ("Panels", f"{pv:.1f} kW", COLORS["solar"]),
            ("Home", f"{load:.1f} kW", COLORS["consumption"]),
            ("Battery", {"charging": f"charging {batt:.1f} kW",
                         "discharging": f"discharging {abs(batt):.1f} kW",
                         "idle": "idle", "off": "not installed"}[battery_state],
             COLORS["battery"]),
            ("Grid", f"importing {grid:.1f} kW" if grid > MIN_KW
             else f"exporting {abs(grid):.1f} kW" if grid < -MIN_KW else "balanced",
             COLORS["grid"]),
        ])
    note = (f'<span style="color:{UI["danger"]}"><b>{html.escape(fault_note)}</b></span>'
            if fault_note else "")

    return (
        f'<div class="ev-flow"><svg viewBox="0 0 {VIEW[0]} {VIEW[1]}" '
        f'role="img" aria-label="Energy flow: panels {pv:.1f} kW, home {load:.1f} kW, '
        f'battery {battery_state}, grid {grid:+.1f} kW">'
        f'{lines}{_hub(self_use)}{nodes}{pills}</svg>'
        f'<div class="ev-flow-legend">{legend}{note}</div></div>'
        f'<div class="ev-sec" style="margin:10px 0 2px"><span class="ev-sec-c">'
        f'{html.escape(_narrative(pv, load, batt, grid, soc if has_battery else None))}'
        f'</span></div>'
    )


def energy_flow(**kwargs) -> None:
    """Draws the diagram on the page."""
    st.markdown(energy_flow_html(**kwargs), unsafe_allow_html=True)
