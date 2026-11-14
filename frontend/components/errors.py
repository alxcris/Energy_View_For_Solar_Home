"""What the app shows when something is missing, late or broken.

Three jobs:
  * status_strip()  - one line at the top of every page: where the data comes
                      from, whether the backend answers, whether the database
                      is saving. The user never has to guess.
  * error_card()    - a readable error: what happened, why, what to do next.
  * section()       - a context manager that keeps one broken section from
                      taking the whole page down with it.
"""

from __future__ import annotations

import html
import traceback
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

import pandas as pd
import streamlit as st

from config import STALE_AFTER_MINUTES

_TONES = {
    "err": ("var(--ev-danger)", "var(--ev-danger-soft)", "!"),
    "warn": ("var(--ev-warn)", "var(--ev-warn-soft)", "!"),
    "info": ("var(--ev-info)", "var(--ev-info-soft)", "i"),
    "ok": ("var(--ev-primary)", "var(--ev-primary-soft)", "ok"),
}


def error_card(title: str, detail: str = "", hint: str = "", tone: str = "err") -> None:
    """An error the user can act on. Never a raw traceback."""
    color, soft, glyph = _TONES.get(tone, _TONES["err"])
    body = f'<div class="ev-err-d">{html.escape(detail)}</div>' if detail else ""
    tip = f'<div class="ev-err-h">{hint}</div>' if hint else ""
    st.markdown(
        f'<div class="ev-err" style="--tone:{color};--tone-soft:{soft}">'
        f'<div class="ev-err-i" style="color:{color};font-weight:800">{glyph}</div>'
        f'<div><div class="ev-err-t">{html.escape(title)}</div>{body}{tip}</div></div>',
        unsafe_allow_html=True)


def empty_state(title: str, hint: str = "") -> None:
    error_card(title, "", hint, tone="info")


@contextmanager
def section(name: str, hint: str = "") -> Iterator[None]:
    """Wraps one part of a page: if it fails, the rest of the page still loads."""
    try:
        yield
    except Exception as exc:  # noqa: BLE001 - last line of defence before the user
        st.session_state.setdefault("errors", []).append(
            {"section": name, "error": f"{type(exc).__name__}: {exc}",
             "trace": traceback.format_exc()})
        error_card(f"{name} could not be loaded", f"{type(exc).__name__}: {exc}",
                   hint or "The rest of the page is unaffected. Reload to try again.")


def error_log() -> list[dict]:
    return st.session_state.get("errors", [])


def error_log_expander() -> None:
    """For us, not for the customer: everything that failed in this session."""
    errors = error_log()
    if not errors:
        return
    with st.expander(f"Technical details ({len(errors)})"):
        for e in errors:
            st.markdown(f"**{e['section']}** - `{e['error']}`")
            st.code(e["trace"], language="text")


# --- status strip ------------------------------------------------------------

def status_strip(items: list[dict]) -> None:
    """items: {label, state (ok|warn|err|live|off), note (optional)}."""
    chunks = []
    for it in items:
        note = f'<em>&middot; {html.escape(it["note"])}</em>' if it.get("note") else ""
        state = it.get("state", "off")
        chunks.append(f'<div class="ev-item"><span class="ev-dot {state}"></span>'
                      f'{html.escape(it["label"])}{note}</div>')
    st.markdown(f'<div class="ev-status">{"".join(chunks)}</div>', unsafe_allow_html=True)


def data_age(last: pd.Timestamp | datetime | None) -> dict:
    """How old the newest reading is - the honest version of a 'live' badge."""
    if last is None or pd.isna(last):
        return {"state": "err", "label": "No readings", "note": ""}
    last = pd.Timestamp(last)
    minutes = (pd.Timestamp.now() - last).total_seconds() / 60
    stamp = last.strftime("%d %b, %H:%M")
    if minutes < 20:
        return {"state": "live", "label": "Live", "note": f"last reading {stamp}"}
    if minutes < STALE_AFTER_MINUTES:
        return {"state": "ok", "label": "Up to date",
                "note": f"last reading {int(minutes)} min ago"}
    if minutes < 60 * 24 * 7:
        hours = minutes / 60
        age = f"{hours:.0f} h ago" if hours < 48 else f"{hours / 24:.0f} days ago"
        return {"state": "warn", "label": "Readings delayed",
                "note": f"newest: {stamp} ({age})"}
    return {"state": "warn", "label": "Recorded dataset", "note": f"readings up to {stamp}"}


def store_warnings() -> None:
    """If a write to the database failed, the user should know before they rely on it."""
    problems = st.session_state.get("store_errors") or []
    if not problems:
        return
    error_card("Your last change was not saved", problems[-1],
               "It still applies in this session. Check that the database file is writable.",
               tone="warn")
    st.session_state["store_errors"] = []
