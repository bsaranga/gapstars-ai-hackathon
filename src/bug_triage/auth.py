"""Simple session-cookie auth backed by a hard-coded user from .env.

Single-user, in-memory session set. Sessions don't survive a server
restart — that's fine here since the only user is the operator and a
re-login is cheap.
"""

from __future__ import annotations

import os
import secrets

USERNAME: str = os.getenv("BUG_TRIAGE_USERNAME", "admin")
PASSWORD: str = os.getenv("BUG_TRIAGE_PASSWORD", "admin")

COOKIE_NAME = "bt_session"

_SESSIONS: set[str] = set()


def authenticate(username: str, password: str) -> bool:
    return username == USERNAME and password == PASSWORD


def create_session() -> str:
    token = secrets.token_urlsafe(32)
    _SESSIONS.add(token)
    return token


def is_authenticated(token: str | None) -> bool:
    return bool(token) and token in _SESSIONS


def destroy_session(token: str | None) -> None:
    if token:
        _SESSIONS.discard(token)
