# SPDX-License-Identifier: GPL-3.0-or-later
"""Session, CSRF and rate-limit guards for the write API."""

import secrets
import time
from collections import deque
from collections.abc import Callable
from functools import wraps
from typing import Any

from flask import Response, g, jsonify, request, session

from backend import db
from backend.models import User

WRITE_LIMIT = 60  # writes per user…
WRITE_WINDOW_SECONDS = 60.0  # …per rolling minute
_write_times: dict[int, deque[float]] = {}
_last_sweep = 0.0

HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_TOO_MANY = 429


def _session_epoch_current(uid: int) -> bool:
    """Check the cookie's epoch against the user row, once per request.

    Flask sessions are signed client-side cookies: the server keeps no record
    of them, so "sign out" alone cannot stop a cookie that was copied earlier —
    it stays valid for its full 30-day lifetime. Sign-out bumps users.session_epoch
    instead, which strands every cookie issued before it. Cached on `g` so the
    several current_user_id() calls in one request cost one lookup.
    """
    cached = g.get("_session_epoch_ok")
    if cached is not None:
        return bool(cached)
    with db.session_scope() as s:
        user = s.get(User, uid)
        ok = user is not None and session.get("epoch") == user.session_epoch
    g._session_epoch_ok = ok  # noqa: SLF001 — flask.g is the documented request-scoped namespace
    return ok


def current_user_id() -> int | None:
    """Return the signed-in user's id from the session cookie, else None."""
    uid = session.get("uid")
    if not isinstance(uid, int):
        return None
    return uid if _session_epoch_current(uid) else None


def _reject(status: int, error: str) -> Response:
    resp = jsonify({"error": error})
    resp.status_code = status
    return resp


def clear_rate_limits() -> None:
    """Reset the in-memory write counters (tests; harmless in prod restarts)."""
    global _last_sweep  # noqa: PLW0603 — module-level counter state by design
    _write_times.clear()
    _last_sweep = 0.0


def _sweep(now: float) -> None:
    """Drop users whose whole window has expired.

    Without this the table keeps one entry per user id that has ever written,
    for the life of the process — a slow leak that a stream of distinct signed-in
    users turns into unbounded growth. Sweeping is amortized to once per window
    so the common path stays O(1) rather than O(users) per write.
    """
    global _last_sweep  # noqa: PLW0603 — module-level counter state by design
    if now - _last_sweep < WRITE_WINDOW_SECONDS:
        return
    _last_sweep = now
    for uid in [u for u, times in _write_times.items() if not times or now - times[-1] > WRITE_WINDOW_SECONDS]:
        del _write_times[uid]


def _rate_limited(uid: int) -> bool:
    now = time.monotonic()
    _sweep(now)
    times = _write_times.setdefault(uid, deque())
    while times and now - times[0] > WRITE_WINDOW_SECONDS:
        times.popleft()
    if len(times) >= WRITE_LIMIT:
        return True
    times.append(now)
    return False


def csrf_ok(token: str) -> bool:
    """Compare the submitted CSRF token to the session's in constant time.

    `==` on the token leaks how many leading characters matched through timing.
    That is a narrow oracle, but the token is the only thing standing between a
    cross-origin page and an authenticated write, so it is compared with
    compare_digest rather than reasoned about.
    """
    expected = session.get("csrf")
    if not token or not isinstance(expected, str) or not expected:
        return False
    return secrets.compare_digest(token, expected)


def login_required(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Require a signed-in session (401 otherwise)."""

    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401 — Flask view passthrough
        if current_user_id() is None:
            return _reject(HTTP_UNAUTHORIZED, "sign in required")
        return fn(*args, **kwargs)

    return wrapper


def write_guard(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Require session + CSRF header + rate-limit headroom for a write view."""

    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401 — Flask view passthrough
        uid = current_user_id()
        if uid is None:
            return _reject(HTTP_UNAUTHORIZED, "sign in required")
        if not csrf_ok(request.headers.get("X-CSRF-Token", "")):
            return _reject(HTTP_FORBIDDEN, "bad CSRF token")
        if _rate_limited(uid):
            return _reject(HTTP_TOO_MANY, "rate limit exceeded")
        return fn(*args, **kwargs)

    return wrapper
