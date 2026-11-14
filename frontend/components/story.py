"""The problem, on the page itself.

Challenge 1 is "every device shows its own piece, nobody sees it all": the
inverter app, the battery portal and the smart meter each show one fragment.
This panel puts those three fragments side by side and then the single live
view that replaces them - so the app states the problem it solves, right where
the customer is looking at the solution.
"""

from __future__ import annotations

import html

import streamlit as st

from components.theme import section
from config import COLORS

# each source, the fragment it shows, and why that fragment is not enough
FRAGMENTS = [
    ("Inverter app", "Isolated production", COLORS["solar"],
     "Disconnected inverters hide the real output - you see a number, not whether it's right."),
    ("Battery portal", "Standalone storage", COLORS["battery"],
     "Charge levels sit decoupled from what the house actually uses and from export prices."),
    ("Smart meter", "Delayed billing", COLORS["grid"],
     "Grid imports and injections only surface on the end-of-month reconciliation."),
]

_ICONS = {
    "Inverter app": '<path d="M3 20 L9 9 H23 L29 20 Z" fill="none" stroke="{c}" stroke-width="2" '
                    'stroke-linejoin="round"/><path d="M16 9 V20" stroke="{c}" stroke-width="2"/>',
    "Battery portal": '<rect x="7" y="6" width="18" height="12" rx="3" fill="none" stroke="{c}" '
                      'stroke-width="2"/><rect x="25" y="9" width="3" height="6" rx="1" fill="{c}"/>'
                      '<rect x="10" y="9" width="7" height="6" rx="1.5" fill="{c}"/>',
    "Smart meter": '<circle cx="16" cy="13" r="9" fill="none" stroke="{c}" stroke-width="2"/>'
                   '<path d="M16 13 L21 9" stroke="{c}" stroke-width="2" stroke-linecap="round"/>',
}


def why_one_view() -> None:
    """Three fragmented sources, in parallel, then the single view that unifies them."""
    section("Why one view", "today each device shows only its own piece")
    cards = []
    for name, frag, color, why in FRAGMENTS:
        icon = _ICONS[name].replace("{c}", color)
        cards.append(
            f'<div class="ev-panel" style="padding:15px 16px;border-top:3px solid {color}">'
            f'<div style="display:flex;align-items:center;gap:10px">'
            f'<svg viewBox="0 0 32 26" width="30" height="24">{icon}</svg>'
            f'<div><div class="ev-panel-name">{html.escape(name)}</div>'
            f'<div class="ev-panel-sub">{html.escape(frag)}</div></div></div>'
            f'<div class="ev-panel-sub" style="margin-top:10px;line-height:1.45">'
            f'{html.escape(why)}</div></div>'
        )
    st.markdown('<div class="ev-panels">' + "".join(cards) + "</div>", unsafe_allow_html=True)
    st.markdown(
        '<div class="ev-plan" style="margin-top:12px">'
        '<div class="ev-rec-title">One Energy View puts all three together</div>'
        '<div class="ev-rec-body" style="margin-bottom:0">Production, storage and the grid '
        'in a single live picture - which is exactly what you are looking at above. '
        'Nobody has to open three apps to understand one home.</div></div>',
        unsafe_allow_html=True)
