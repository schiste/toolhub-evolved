# SPDX-License-Identifier: GPL-3.0-or-later
"""Session, CSRF and rate-limit guards for the write API."""

import secrets
import time
from collections import deque
from collections.abc import Callable
from functools import wraps
from threading import Lock
from typing import Any

from flask import Response, g, jsonify, request, session

from backend import db
from backend.models import User

WRITE_LIMIT = 60  # writes per user…
WRITE_WINDOW_SECONDS = 60.0  # …per rolling minute
# Anonymous proxy reads, per client address per rolling minute. Every /api/ hit
# that misses the cache becomes a request to toolhub.wikimedia.org, so an
# unthrottled proxy is a traffic amplifier pointed at Wikimedia infrastructure
# as much as it is our own availability problem. Generous enough that a real
# page load (a handful of parallel calls, then mostly cache hits) never notices.
READ_LIMIT = 120

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


class RollingLimit:
    """Fixed-count-per-rolling-window limiter, keyed by user id or client address.

    In-memory and therefore per worker process: with N workers the effective
    ceiling is N times the configured limit. That is accepted here — these
    limits exist to stop runaway clients and to keep the proxy from becoming an
    amplifier, not to enforce an exact quota.

    Locked because the webservice serves requests on threads: `exceeded` is a
    read-modify-write over shared state, so concurrent callers could otherwise
    interleave between the length check and the append and slip past the limit.
    The lock is uncontended in the normal case and held only for dict/deque work.
    """

    def __init__(self, limit: int, window: float = WRITE_WINDOW_SECONDS) -> None:
        """Create an empty limiter."""
        self.limit = limit
        self.window = window
        self.times: dict[Any, deque[float]] = {}
        self.last_sweep = 0.0
        self._lock = Lock()

    def clear(self) -> None:
        """Forget every tracked key."""
        with self._lock:
            self.times.clear()
            self.last_sweep = 0.0

    def _sweep(self, now: float) -> None:
        """Drop keys whose whole window has expired. Caller holds the lock.

        Without this the table keeps one entry per key ever seen, for the life of
        the process — a slow leak that a stream of distinct users or addresses
        turns into unbounded growth. Amortized to once per window so the common
        path stays O(1) rather than O(keys) per request.
        """
        if now - self.last_sweep < self.window:
            return
        self.last_sweep = now
        for key in [k for k, times in self.times.items() if not times or now - times[-1] > self.window]:
            del self.times[key]

    def exceeded(self, key: Any) -> bool:  # noqa: ANN401 — int uid or str address
        """Record one hit for `key` and report whether it is over the limit."""
        now = time.monotonic()
        with self._lock:
            self._sweep(now)
            times = self.times.setdefault(key, deque())
            while times and now - times[0] > self.window:
                times.popleft()
            if len(times) >= self.limit:
                return True
            times.append(now)
            return False


# Per-user limit for the expensive resolver read (/v1/me/tools/). One call fans
# out to several upstream Toolhub searches and takes seconds, so a client
# looping on it needs no volume at all to occupy every worker — a steady 1.5
# requests a second was enough to make the whole site return 503, including
# static pages. Keyed by user, not address, because every request arrives from
# the cluster ingress.
#
# This is a backstop, not the fix: the loop that caused that was a client-side
# render cycle (see scheduleApiRefreshRender in main.js). It still has to hold
# on its own, because shipping the client fix does not stop a browser tab that
# already loaded the old code — only reloading it does.
#
# Sized against duration, not intuition: a call takes ~5s, so six a minute is
# about half a worker. Browsing makes one call per page visit and never comes
# close.
RESOLVER_LIMIT = 6

_writes = RollingLimit(WRITE_LIMIT)
_reads = RollingLimit(READ_LIMIT)
_resolver = RollingLimit(RESOLVER_LIMIT)


def clear_rate_limits() -> None:
    """Reset the in-memory counters (tests; harmless in prod restarts)."""
    _writes.clear()
    _reads.clear()
    _resolver.clear()


def resolver_rate_limited(user_id: int | None) -> bool:
    """Record one expensive resolver read and report whether the user is over the limit."""
    return _resolver.exceeded(user_id if user_id is not None else "unknown")


def read_rate_limited(client_addr: str | None) -> bool:
    """Record one anonymous proxy read and report whether the caller is over the limit."""
    return _reads.exceeded(client_addr or "unknown")


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


GUARD_ATTR = "__toolhub_guard__"


def login_required(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Require a signed-in session (401 otherwise)."""

    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401 — Flask view passthrough
        if current_user_id() is None:
            return _reject(HTTP_UNAUTHORIZED, "sign in required")
        return fn(*args, **kwargs)

    # Machine-readable so tests can assert every /v1 route is guarded or is on an
    # explicit public allowlist. See test_every_v1_route_is_guarded_or_allowlisted.
    setattr(wrapper, GUARD_ATTR, "login_required")
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
        if _writes.exceeded(uid):
            return _reject(HTTP_TOO_MANY, "rate limit exceeded")
        return fn(*args, **kwargs)

    setattr(wrapper, GUARD_ATTR, "write_guard")
    return wrapper
