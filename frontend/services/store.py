"""One place to read and write "what this user decided".

Pages and components never touch the database directly: they call store.*,
which keeps a copy in st.session_state (fast, no query per rerun) and writes
through to services/db.py. When the database is unavailable, or the visitor
chose to look around without an account, the same functions keep working on
session state alone - the app degrades, it does not break.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import streamlit as st

from services import db


# --- who we are writing for --------------------------------------------------

def user() -> dict | None:
    return st.session_state.get("user")


def user_id() -> int | None:
    u = user()
    return int(u["user_id"]) if u and u.get("user_id") else None


def is_guest() -> bool:
    """A visitor without an account: everything stays in this browser session."""
    u = user()
    return bool(u and u.get("guest"))


def persistent() -> bool:
    """True when what the user decides is actually saved for next time."""
    return user_id() is not None and db.available()


# --- onboarding profile ------------------------------------------------------

def profile() -> dict[str, Any]:
    """The onboarding answers. Loaded from the database once per session."""
    if "profile" not in st.session_state:
        loaded: dict[str, Any] = {}
        uid = user_id()
        if uid is not None:
            try:
                loaded = db.load_profile(uid)
            except db.DatabaseError:
                loaded = {}
        st.session_state["profile"] = loaded or {"step": 1}
    return st.session_state["profile"]


def save_profile(profile_data: dict[str, Any] | None = None) -> None:
    data = profile_data if profile_data is not None else st.session_state.get("profile", {})
    st.session_state["profile"] = data
    uid = user_id()
    if uid is None:
        return
    try:
        db.save_profile(uid, data)
    except db.DatabaseError as exc:
        st.session_state.setdefault("store_errors", []).append(str(exc))


def reset_profile() -> None:
    st.session_state["profile"] = {"step": 1}
    uid = user_id()
    if uid is not None:
        try:
            db.clear_profile(uid)
        except db.DatabaseError:
            pass


def profile_done() -> bool:
    return bool(profile().get("done"))


# --- recommendation decisions ------------------------------------------------

def decisions() -> dict[str, dict]:
    """{notif_id: {state, title, saving}} - accepted, dismissed or snoozed."""
    if "decisions" not in st.session_state:
        loaded: dict[str, dict] = {}
        uid = user_id()
        if uid is not None:
            try:
                loaded = db.get_decisions(uid)
            except db.DatabaseError:
                loaded = {}
        st.session_state["decisions"] = loaded
    return st.session_state["decisions"]


SNOOZE_HOURS = 20  # "not today" comes back tomorrow, not in the next second


def set_decision(notif_id: str, state: str, title: str = "", saving: float = 0.0) -> None:
    decisions()[notif_id] = {"notif_id": notif_id, "state": state, "title": title,
                             "saving": float(saving),
                             "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    uid = user_id()
    if uid is None:
        return
    try:
        db.set_decision(uid, notif_id, state, title, saving)
    except db.DatabaseError as exc:
        st.session_state.setdefault("store_errors", []).append(str(exc))


def undo_decision(notif_id: str) -> None:
    decisions().pop(notif_id, None)
    uid = user_id()
    if uid is not None:
        try:
            db.drop_decision(uid, notif_id)
        except db.DatabaseError:
            pass


def accepted() -> dict[str, dict]:
    return {k: v for k, v in decisions().items() if v.get("state") == "accepted"}


def dismissed() -> set[str]:
    return {k for k, v in decisions().items() if v.get("state") == "dismissed"}


def hidden() -> set[str]:
    """What not to show right now: turned down for good, or postponed today."""
    out, now = set(), datetime.now(timezone.utc)
    for notif_id, item in decisions().items():
        state = item.get("state")
        if state == "dismissed":
            out.add(notif_id)
        elif state == "snoozed":
            try:
                when = datetime.fromisoformat(str(item.get("updated_at")))
                when = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                when = now
            if now - when < timedelta(hours=SNOOZE_HOURS):
                out.add(notif_id)
    return out


# --- activity log ------------------------------------------------------------

def log(kind: str, detail: str = "") -> None:
    uid = user_id()
    if uid is not None:
        db.log_event(uid, kind, detail)
    st.session_state.setdefault("session_log", []).insert(0, (kind, detail))


def events(limit: int = 20) -> list[dict]:
    uid = user_id()
    if uid is not None:
        try:
            return db.recent_events(uid, limit)
        except db.DatabaseError:
            pass
    return [{"ts": "", "kind": k, "detail": d}
            for k, d in st.session_state.get("session_log", [])[:limit]]


def forget_session() -> None:
    """Called on sign-out: nothing of this user stays in the next session."""
    for key in ("user", "profile", "decisions", "session_log", "store_errors",
                "live_idx", "live_playing", "site_id"):
        st.session_state.pop(key, None)
