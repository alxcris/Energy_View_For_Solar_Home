"""Two views of the detail behind the big numbers:

    panel_array()        which string is working and how much it makes right now
    consumption_split()  where a day's kWh actually go

Both are plain HTML + CSS (styles in components/theme.py): a card per string,
with the panels drawn as cells that brighten while they produce and a bar that
compares what the string makes with what the weather allows.
"""

from __future__ import annotations

import html

import streamlit as st

from components.theme import badge
from config import COLORS, SERIES

_STATE_BADGE = {"ok": ("Producing", "ok"), "watch": ("Check", "warn"),
                "alarm": ("Fault", "err"), "idle": ("Resting", "mute")}
_STATE_CLASS = {"ok": "live", "watch": "watch", "alarm": "alarm", "idle": ""}


def _cells(panels: int, ratio: float | None, state: str) -> str:
    """The panels themselves: brighter cells mean more power per panel."""
    shown = min(panels, 12)
    if state == "idle":
        color = "#D8E0E8"
    elif state == "alarm":
        color = "#E7B4B4"
    else:
        strength = 0.45 + 0.55 * min(1.0, ratio or 0.6)
        color = f"color-mix(in srgb, {COLORS['solar']} {strength * 100:.0f}%, #DCE4EC)"
    return (f'<div class="ev-cells" style="--cell:{color}">' + "<b></b>" * shown + "</div>")


def panel_card(row: dict) -> str:
    label, tone = _STATE_BADGE[row["state"]]
    current, expected = row["current_kw"], row["expected_kw"]
    scale = max(expected, current, 0.1) * 1.15
    width = min(100.0, current / scale * 100)
    marker = min(100.0, expected / scale * 100)
    pct = f"{row['ratio'] * 100:.0f}% of expected" if row["ratio"] is not None else "-"
    return (
        f'<div class="ev-panel {_STATE_CLASS[row["state"]]}">'
        f'<div class="ev-panel-top"><div>'
        f'<div class="ev-panel-name">{html.escape(row["name"])}</div>'
        f'<div class="ev-panel-sub">{row["panels"]} panels &middot; {row["kwp"]:.2f} kWp '
        f'&middot; {html.escape(row["facing"])}</div></div>{badge(label, tone)}</div>'
        f'<div class="ev-panel-val">{current:.2f}<small>kW</small></div>'
        f'<div class="ev-panel-bar" style="--w:{width:.0f}%;--exp:{marker:.0f}%;'
        f'--bc:{COLORS["solar"] if row["state"] != "alarm" else COLORS["peak"]}">'
        f'<i></i><u></u></div>'
        f'<div class="ev-panel-foot"><span>expected {expected:.2f} kW</span>'
        f'<span>{pct}</span></div>'
        f'{_cells(row["panels"], row["ratio"], row["state"])}'
        f'<div class="ev-panel-sub" style="margin-top:8px">{html.escape(row["note"])}</div>'
        f'</div>'
    )


def panel_array(rows: list[dict]) -> None:
    """A card per string of panels."""
    if not rows:
        st.caption("No array registered for this installation.")
        return
    st.markdown('<div class="ev-panels">' + "".join(panel_card(r) for r in rows) + "</div>",
                unsafe_allow_html=True)


def consumption_bars(rows: list[dict]) -> None:
    """Where the day's kWh go, as a short list with bars."""
    if not rows:
        st.caption("Not enough consumption data yet.")
        return
    total = sum(r["kwh"] for r in rows)
    out = []
    for r in rows:
        color = SERIES[int(r.get("series", 0)) % len(SERIES)]
        out.append(
            f'<div style="margin-bottom:11px">'
            f'<div style="display:flex;justify-content:space-between;font-size:.86rem;'
            f'font-weight:600;color:var(--ev-text)"><span>{html.escape(r["label"])}</span>'
            f'<span class="ev-num">{r["kwh"]:.1f} kWh &middot; {r["share"] * 100:.0f}%</span></div>'
            f'<div class="ev-panel-bar" style="--w:{r["share"] * 100:.0f}%;--exp:-10px;--bc:{color}">'
            f'<i></i></div>'
            f'<div class="ev-panel-sub">{html.escape(r.get("hint", ""))}</div></div>')
    st.markdown("".join(out) + f'<div class="ev-panel-sub ev-num">About {total:.1f} kWh on a '
                               f'typical day.</div>', unsafe_allow_html=True)


def device_plan(devices: list[dict]) -> None:
    """The appliance schedule the ML pipeline worked out: what to run, when, and how."""
    if not devices:
        return
    cards = []
    for i, d in enumerate(devices[:4]):
        colour = SERIES[i % len(SERIES)]
        name = str(d.get("name", "appliance")).capitalize()
        window = f'{d.get("on", "")} - {d.get("off", "")}'.strip(" -")
        saving = float(d.get("saving_lei") or 0)
        cards.append(
            f'<div class="ev-panel" style="padding:14px 16px;border-left:4px solid {colour}">'
            f'<div class="ev-panel-top"><div>'
            f'<div class="ev-panel-name">{html.escape(name)}</div>'
            f'<div class="ev-panel-sub">{html.escape(window)}</div></div>'
            f'{badge(f"~{saving:.1f} lei", "ok" if saving >= 1 else "mute")}</div>'
            f'<div class="ev-panel-sub" style="margin-top:8px">'
            f'{html.escape(str(d.get("how", "")))}</div></div>')
    st.markdown('<div class="ev-panels">' + "".join(cards) + "</div>",
                unsafe_allow_html=True)
