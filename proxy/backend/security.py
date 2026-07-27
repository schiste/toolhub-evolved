# SPDX-License-Identifier: GPL-3.0-or-later
"""Session, CSRF and rate-limit guards for the write API."""

import secrets
import time
from collections import deque
from collections.abc import Callable
from functools import wraps
from typing import Any

from flask import Response, jsonify, request, session

WRITE_LIMIT = 60  # writes per user…
WRITE_WINDOW_SECONDS = 60.0  # …per rolling minute
_write_times: dict[int, deque[float]] = {}

HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_TOO_MANY = 429


def current_user_id() -> int | None:
    """Return the signed-in user's id from the session cookie, else None."""
    uid = session.get("uid")
    return uid if isinstance(uid, int) else None


def _reject(status: int, error: str) -> Response:
    resp = jsonify({"error": error})
    resp.status_code = status
    return resp


def clear_rate_limits() -> None:
    """Reset the in-memory write counters (tests; harmless in prod restarts)."""
    _write_times.clear()


def _rate_limited(uid: int) -> bool:
    now = time.monotonic()
    times = _write_times.setdefault(uid, deque())
    while times and now - times[0] > WRITE_WINDOW_SECONDS:
        times.popleft()
    if len(times) >= WRITE_LIMIT:
        return True
    times.append(now)
    return False


def _csrf_ok(token: str) -> bool:
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
        if not _csrf_ok(request.headers.get("X-CSRF-Token", "")):
            return _reject(HTTP_FORBIDDEN, "bad CSRF token")
        if _rate_limited(uid):
            return _reject(HTTP_TOO_MANY, "rate limit exceeded")
        return fn(*args, **kwargs)

    return wrapper
