"""Sign-in gate.

Each prosumer sees their own installation, their own answers to the
questionnaire and their own plan, so the app needs to know who is looking.
Accounts live in the SQLite database (services/db.py); there is also a demo
account for the jury and a no-account mode for a quick look around.
"""

from __future__ import annotations

import streamlit as st

from components.errors import error_card
from components.theme import footer, setup_page
from services import db, store

DEMO_EMAIL, DEMO_PASSWORD = "demo@ppc.ro", "demo1234"


@st.cache_resource(show_spinner=False)
def db_state() -> dict:
    """Creates the tables once per app start. Returns the database's state."""
    try:
        db.init()
        return {"ok": True, "error": ""}
    except db.DatabaseError as exc:
        return {"ok": False, "error": str(exc)}


def current_user() -> dict | None:
    return st.session_state.get("user")


def _sign_in(user: dict) -> None:
    st.session_state["user"] = user
    for key in ("profile", "decisions"):
        st.session_state.pop(key, None)  # reload from the database for this user
    if user.get("site_id"):
        st.session_state["site_id"] = user["site_id"]
    st.rerun()


def logout() -> None:
    store.forget_session()
    st.rerun()


def require_user() -> dict:
    """Returns the signed-in user, or draws the sign-in page and stops the script."""
    user = current_user()
    if user:
        return user
    _login_page()
    st.stop()
    raise SystemExit  # never reached, keeps type checkers happy


def _login_page() -> None:
    setup_page("Sign in")
    state = db_state()

    _, mid, _ = st.columns([1, 1.25, 1])
    with mid:
        st.markdown(
            '<div class="ev-auth-head"><h2>One Energy View</h2>'
            '<p>Your production, consumption and storage in one place.</p></div>',
            unsafe_allow_html=True)

        if not state["ok"]:
            error_card(
                "The accounts database is not available",
                state["error"],
                "You can still look around without an account - your answers will only "
                "be kept until you close the tab.",
                tone="warn")
        else:
            tab_in, tab_up = st.tabs(["Sign in", "Create account"])
            with tab_in:
                _sign_in_form()
            with tab_up:
                _sign_up_form()
            st.markdown(
                f'<div class="ev-demo">Demo account for the jury: <b>{DEMO_EMAIL}</b> '
                f'/ <b>{DEMO_PASSWORD}</b> &middot; an O&amp;M operator account also exists '
                f'(<b>om@ppc.ro</b>).</div>', unsafe_allow_html=True)

        st.write("")
        if st.button("Look around without an account", width="stretch",
                     icon=":material/visibility:"):
            _sign_in({"user_id": None, "email": "guest", "name": "Guest",
                      "role": "customer", "site_id": None, "guest": True})
    footer()


def _sign_in_form() -> None:
    with st.form("sign_in", border=False):
        email = st.text_input("Email", placeholder="you@example.com", key="in_email")
        password = st.text_input("Password", type="password", key="in_pw")
        c1, c2 = st.columns([2, 3])
        submitted = c1.form_submit_button("Sign in", type="primary", width="stretch")
        demo = c2.form_submit_button("Use the demo account", width="stretch")

    if demo:
        email, password = DEMO_EMAIL, DEMO_PASSWORD
        submitted = True
    if not submitted:
        return
    if not email or not password:
        error_card("Fill in both fields", "We need an email address and a password.",
                   tone="warn")
        return
    try:
        user = db.authenticate(email, password)
    except db.DatabaseError as exc:
        error_card("Could not check your details", str(exc),
                   "Try again in a moment, or look around without an account.")
        return
    if user is None:
        error_card("Wrong email or password",
                   "No account matches these details.",
                   f"Creating an account takes a few seconds, or sign in with {DEMO_EMAIL}.",
                   tone="warn")
        return
    _sign_in(user)


def _sign_up_form() -> None:
    with st.form("sign_up", border=False):
        name = st.text_input("Your name", placeholder="Ana Popescu")
        email = st.text_input("Email", placeholder="you@example.com", key="up_email")
        password = st.text_input("Password", type="password", key="up_pw",
                                 help="At least 6 characters.")
        site = st.text_input("Installation code (optional)", placeholder="S01",
                             help="The code on your PPC contract. You can pick the "
                                  "installation later as well.")
        submitted = st.form_submit_button("Create account", type="primary", width="stretch")

    if not submitted:
        return
    try:
        user = db.create_user(email, name, password, site_id=(site or "").strip().upper() or None)
    except db.WeakPassword as exc:
        error_card("Password too short", str(exc), tone="warn")
        return
    except db.EmailTaken as exc:
        error_card("Account already exists", str(exc),
                   "Use the Sign in tab instead.", tone="warn")
        return
    except db.DatabaseError as exc:
        error_card("Could not create the account", str(exc),
                   "Look around without an account in the meantime.")
        return
    st.success("Account created. Welcome!")
    _sign_in(user)


def account_chip(user: dict) -> str:
    """The small 'signed in as ...' pill for the page toolbar."""
    if user.get("guest"):
        return ('<div class="ev-item"><span class="ev-dot warn"></span>Guest'
                '<em>&middot; answers kept for this session only</em></div>')
    role = "O&M operator" if user.get("role") == "operator" else "Prosumer"
    saved = "saved to your account" if store.persistent() else "not being saved"
    return (f'<div class="ev-item"><span class="ev-dot ok"></span>'
            f'{user.get("name") or user.get("email")}<em>&middot; {role} &middot; {saved}</em></div>')
