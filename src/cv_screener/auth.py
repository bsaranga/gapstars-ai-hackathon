from __future__ import annotations

import os
import secrets
from html import escape

from fastapi import HTTPException, Request


def _expected_password() -> str | None:
    pw = os.getenv("CV_SCREENER_PASSWORD")
    return pw or None


def _expected_username() -> str:
    return os.getenv("CV_SCREENER_USERNAME", "admin")


def is_configured() -> bool:
    return _expected_password() is not None


def credentials_valid(username: str, password: str) -> bool:
    expected_pw = _expected_password()
    if expected_pw is None:
        return False
    ok_user = secrets.compare_digest(username, _expected_username())
    ok_pass = secrets.compare_digest(password, expected_pw)
    return ok_user and ok_pass


def session_secret() -> str:
    """Read CV_SCREENER_SECRET_KEY, falling back to a random per-process key.

    A random fallback means sessions don't survive a server restart. Set the
    env var for persistent sessions across restarts.
    """
    return os.getenv("CV_SCREENER_SECRET_KEY") or secrets.token_urlsafe(32)


def require_auth(request: Request) -> str:
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="not authenticated")
    return user


_LOGIN_TMPL = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>CV Screener — Sign in</title>
  <style>
    :root {
      --bg: #0b0d12; --panel: #141821; --card: #1a1f2c;
      --border: #2a3142; --border-2: #353d52;
      --text: #e6e8ec; --muted: #8b93a6;
      --accent: #6366f1; --failed: #ef4444;
    }
    * { box-sizing: border-box; }
    html, body { margin: 0; height: 100%; background: var(--bg); color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, system-ui, sans-serif; }
    body { display: flex; align-items: center; justify-content: center; padding: 24px; }
    .card {
      background: var(--panel); border: 1px solid var(--border);
      border-radius: 12px; padding: 32px 28px; width: 360px; max-width: 100%;
      box-shadow: 0 18px 48px rgba(0,0,0,0.5);
    }
    h1 { margin: 0 0 6px; font-size: 18px; }
    .sub { color: var(--muted); font-size: 13px; margin-bottom: 22px; }
    label { display: block; font-size: 11px; color: var(--muted);
      text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 6px; }
    input {
      width: 100%; padding: 10px 12px; font-size: 14px;
      background: var(--card); border: 1px solid var(--border);
      color: var(--text); border-radius: 6px; outline: none;
      margin-bottom: 14px; font-family: inherit;
      transition: border-color 0.15s;
    }
    input:focus { border-color: var(--accent); }
    button {
      width: 100%; padding: 10px; font-size: 14px; font-weight: 500;
      background: var(--accent); color: white; border: 0;
      border-radius: 6px; cursor: pointer; margin-top: 4px;
    }
    button:hover { opacity: 0.9; }
    .error {
      color: var(--failed); font-size: 12px; margin-bottom: 12px;
      padding: 8px 10px; border: 1px solid rgba(239, 68, 68, 0.4);
      border-radius: 6px; background: rgba(239, 68, 68, 0.08);
    }
  </style>
</head>
<body>
  <form class="card" method="POST" action="/login">
    <h1>CV Screener</h1>
    <div class="sub">Sign in to continue.</div>
    __ERROR__
    <label for="username">Username</label>
    <input id="username" name="username" type="text" autocomplete="username" required autofocus />
    <label for="password">Password</label>
    <input id="password" name="password" type="password" autocomplete="current-password" required />
    <button type="submit">Sign in</button>
  </form>
</body>
</html>
"""


def render_login_html(error: str | None = None) -> str:
    block = f'<div class="error">{escape(error)}</div>' if error else ""
    return _LOGIN_TMPL.replace("__ERROR__", block)
