"""Simple Streamlit login and per-session AI usage guard.

Not a global rate limiter. For private, low-traffic apps only.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from datetime import datetime, timezone

import streamlit as st

HOURLY_LIMIT = 3
DAILY_LIMIT = 10
COOLDOWN_SECONDS = 30


def _password_digest(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def require_login() -> None:
    """Stop rendering until a valid password has been entered."""
    try:
        expected_hash = st.secrets.get('APP_PASSWORD_SHA256', '')
    except Exception:
        expected_hash = ''
    if not expected_hash or len(expected_hash) != 64:
        st.error('APP_PASSWORD_SHA256 fehlt oder ist ungültig. Bitte Streamlit Secrets konfigurieren.')
        st.stop()

    if st.session_state.get('_authenticated', False):
        with st.sidebar:
            if st.button('🔒 Abmelden', key='logout_button'):
                st.session_state.clear()
                st.rerun()
        return

    st.title('🔒 Investment Scout – Anmeldung')
    with st.form('login_form'):
        password = st.text_input('Passwort', type='password')
        submitted = st.form_submit_button('Anmelden')
    if submitted:
        provided_hash = _password_digest(password)
        if hmac.compare_digest(provided_hash, expected_hash):
            st.session_state['_authenticated'] = True
            st.rerun()
        else:
            st.error('Passwort nicht korrekt.')
    st.stop()


def check_ai_limit() -> tuple[bool, str]:
    """Check per-session quotas; no request is consumed until register_ai_request()."""
    now = time.time()
    history = st.session_state.get('_ai_requests', [])
    history = [ts for ts in history if now - ts < 86400]
    st.session_state['_ai_requests'] = history
    hourly = sum(now - ts < 3600 for ts in history)
    if history and now - history[-1] < COOLDOWN_SECONDS:
        remaining = int(COOLDOWN_SECONDS - (now - history[-1])) + 1
        return False, f'Bitte noch {remaining} Sekunden warten.'
    if hourly >= HOURLY_LIMIT:
        return False, 'Stundenlimit erreicht (3 Analysen pro Sitzung).'
    if len(history) >= DAILY_LIMIT:
        return False, 'Tageslimit erreicht (10 Analysen pro Sitzung).'
    return True, f'Noch {HOURLY_LIMIT - hourly} Analysen in dieser Stunde und {DAILY_LIMIT - len(history)} heute (je Sitzung).'


def register_ai_request() -> None:
    """Count before API call, including failed attempts, to bound retries."""
    st.session_state.setdefault('_ai_requests', []).append(time.time())
