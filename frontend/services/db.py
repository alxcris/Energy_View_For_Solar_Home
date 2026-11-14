"""Per-user storage for the frontend: accounts and everything the user decided.

Why a database and not st.session_state: the answers to the questionnaire, the
recommendations the customer accepted and the ones they told us never to show
again have to survive a page reload, a different browser and a second device.
st.session_state forgets all of it the moment the tab closes.

One SQLite file (config.USER_DB), four tables:

    users        one row per account (prosumer or O&M operator)
    profiles     one row per user: the onboarding answers, as JSON
    decisions    one row per (user, recommendation): accepted / dismissed / snoozed
    events       an activity log, so the user can see what the app did for them

Passwords are never stored: only a PBKDF2-SHA256 hash with a per-user salt.
This module is plain Python (no Streamlit), so it can be tested on its own.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from config import USER_DB

PBKDF2_ROUNDS = 120_000
MIN_PASSWORD_LEN = 6

DEMO_USERS = [
    # email, name, password, role, site_id
    ("demo@ppc.ro", "Demo prosumer", "demo1234", "customer", "S01"),
    ("om@ppc.ro", "O&M operator", "demo1234", "operator", None),
]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    email      TEXT UNIQUE NOT NULL,
    name       TEXT NOT NULL,
    pw_hash    TEXT NOT NULL,
    pw_salt    TEXT NOT NULL,
    role       TEXT NOT NULL DEFAULT 'customer',
    site_id    TEXT,
    created_at TEXT NOT NULL,
    last_login TEXT
);
CREATE TABLE IF NOT EXISTS profiles (
    user_id    INTEGER PRIMARY KEY REFERENCES users(user_id),
    data       TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS decisions (
    user_id    INTEGER NOT NULL REFERENCES users(user_id),
    notif_id   TEXT NOT NULL,
    state      TEXT NOT NULL,
    title      TEXT,
    saving     REAL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, notif_id)
);
CREATE TABLE IF NOT EXISTS events (
    event_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   INTEGER NOT NULL REFERENCES users(user_id),
    ts        TEXT NOT NULL,
    kind      TEXT NOT NULL,
    detail    TEXT
);
CREATE INDEX IF NOT EXISTS ix_events_user ON events(user_id, ts DESC);
"""


class DatabaseError(RuntimeError):
    """Anything that went wrong with the database, in words a page can show."""


class EmailTaken(DatabaseError):
    pass


class WeakPassword(DatabaseError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    """One connection per operation, committed on the way out."""
    path = Path(USER_DB)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(path, timeout=10)
    except (OSError, sqlite3.Error) as exc:
        raise DatabaseError(f"Could not open the database at {path}: {exc}") from exc
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA foreign_keys = ON")
        yield con
        con.commit()
    except sqlite3.Error as exc:
        con.rollback()
        raise DatabaseError(str(exc)) from exc
    finally:
        con.close()


def init(seed_demo: bool = True) -> None:
    """Creates the tables if they are missing. Safe to call on every run."""
    with _conn() as con:
        con.executescript(_SCHEMA)
    if seed_demo:
        for email, name, password, role, site_id in DEMO_USERS:
            if get_by_email(email) is None:
                try:
                    create_user(email, name, password, role=role, site_id=site_id)
                except DatabaseError:
                    pass  # a parallel session created it first - fine


# --- passwords ---------------------------------------------------------------

def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt),
                               PBKDF2_ROUNDS).hex()


# --- users -------------------------------------------------------------------

def _row_to_user(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    user = {k: row[k] for k in row.keys()}
    user.pop("pw_hash", None)
    user.pop("pw_salt", None)
    return user


def get_by_email(email: str) -> dict | None:
    with _conn() as con:
        row = con.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
    return _row_to_user(row)


def get_user(user_id: int) -> dict | None:
    with _conn() as con:
        row = con.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    return _row_to_user(row)


def create_user(email: str, name: str, password: str, role: str = "customer",
                site_id: str | None = None) -> dict:
    """Creates an account. Raises EmailTaken or WeakPassword with a readable message."""
    email = (email or "").strip().lower()
    name = (name or "").strip() or email.split("@")[0]
    if "@" not in email or "." not in email.split("@")[-1]:
        raise DatabaseError("That does not look like an email address.")
    if len(password or "") < MIN_PASSWORD_LEN:
        raise WeakPassword(f"The password needs at least {MIN_PASSWORD_LEN} characters.")
    salt = secrets.token_hex(16)
    try:
        with _conn() as con:
            cur = con.execute(
                "INSERT INTO users (email, name, pw_hash, pw_salt, role, site_id, created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (email, name, _hash(password, salt), salt, role, site_id, _now()))
            user_id = int(cur.lastrowid)
    except DatabaseError as exc:
        if "UNIQUE" in str(exc):
            raise EmailTaken("There is already an account with this email address.") from exc
        raise
    log_event(user_id, "account_created", email)
    return get_user(user_id)  # type: ignore[return-value]


def authenticate(email: str, password: str) -> dict | None:
    """The user, if the password matches. None otherwise (no reason given to the caller)."""
    with _conn() as con:
        row = con.execute("SELECT * FROM users WHERE email = ?",
                          ((email or "").strip().lower(),)).fetchone()
        if row is None:
            return None
        if not secrets.compare_digest(_hash(password or "", row["pw_salt"]), row["pw_hash"]):
            return None
        con.execute("UPDATE users SET last_login = ? WHERE user_id = ?", (_now(), row["user_id"]))
        user = _row_to_user(row)
    log_event(int(user["user_id"]), "login", "")
    return user


def set_site(user_id: int, site_id: str) -> None:
    """Remembers which installation this user looks at, so the app opens on it."""
    with _conn() as con:
        con.execute("UPDATE users SET site_id = ? WHERE user_id = ?", (site_id, user_id))


# --- onboarding profile ------------------------------------------------------

def save_profile(user_id: int, profile: dict[str, Any]) -> None:
    payload = json.dumps(_jsonable(profile), ensure_ascii=False)
    with _conn() as con:
        con.execute(
            "INSERT INTO profiles (user_id, data, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
            (user_id, payload, _now()))


def load_profile(user_id: int) -> dict[str, Any]:
    with _conn() as con:
        row = con.execute("SELECT data FROM profiles WHERE user_id = ?", (user_id,)).fetchone()
    if row is None:
        return {}
    try:
        return json.loads(row["data"])
    except json.JSONDecodeError:
        return {}


def clear_profile(user_id: int) -> None:
    with _conn() as con:
        con.execute("DELETE FROM profiles WHERE user_id = ?", (user_id,))


def _jsonable(value: Any) -> Any:
    """st.pills and friends can hand us sets and tuples; JSON only takes lists."""
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return value


# --- recommendation decisions ------------------------------------------------

def set_decision(user_id: int, notif_id: str, state: str, title: str = "",
                 saving: float = 0.0) -> None:
    """state: accepted | dismissed | snoozed."""
    with _conn() as con:
        con.execute(
            "INSERT INTO decisions (user_id, notif_id, state, title, saving, updated_at) "
            "VALUES (?,?,?,?,?,?) ON CONFLICT(user_id, notif_id) DO UPDATE SET "
            "state = excluded.state, title = excluded.title, saving = excluded.saving, "
            "updated_at = excluded.updated_at",
            (user_id, notif_id, state, title, float(saving), _now()))
    log_event(user_id, f"recommendation_{state}", title or notif_id)


def get_decisions(user_id: int) -> dict[str, dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT notif_id, state, title, saving, updated_at FROM decisions WHERE user_id = ?",
            (user_id,)).fetchall()
    return {r["notif_id"]: {k: r[k] for k in r.keys()} for r in rows}


def drop_decision(user_id: int, notif_id: str) -> None:
    with _conn() as con:
        con.execute("DELETE FROM decisions WHERE user_id = ? AND notif_id = ?",
                    (user_id, notif_id))


def clear_decisions(user_id: int) -> None:
    with _conn() as con:
        con.execute("DELETE FROM decisions WHERE user_id = ?", (user_id,))


# --- activity log ------------------------------------------------------------

def log_event(user_id: int, kind: str, detail: str = "") -> None:
    """Best effort: an app should not break because its own log is unavailable."""
    try:
        with _conn() as con:
            con.execute("INSERT INTO events (user_id, ts, kind, detail) VALUES (?,?,?,?)",
                        (user_id, _now(), kind, detail[:500]))
    except DatabaseError:
        pass


def recent_events(user_id: int, limit: int = 20) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT ts, kind, detail FROM events WHERE user_id = ? ORDER BY ts DESC LIMIT ?",
            (user_id, limit)).fetchall()
    return [{k: r[k] for k in r.keys()} for r in rows]


# --- health ------------------------------------------------------------------

def available() -> bool:
    """True when the database can be opened and read."""
    return bool(health().get("ok"))


def health() -> dict:
    """Used by the status strip: is the database there, and how much is in it?"""
    try:
        with _conn() as con:
            users = con.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
            profiles = con.execute("SELECT COUNT(*) AS n FROM profiles").fetchone()["n"]
            decisions = con.execute("SELECT COUNT(*) AS n FROM decisions").fetchone()["n"]
        return {"ok": True, "users": users, "profiles": profiles, "decisions": decisions,
                "path": str(USER_DB)}
    except DatabaseError as exc:
        return {"ok": False, "error": str(exc), "path": str(USER_DB)}
