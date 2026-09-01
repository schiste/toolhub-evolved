# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: INP001, PLR2004, S101, S105, SLF001, TC003 - focused mutation assertions exercise internals
"""Behavioral assertions chosen from critical-path mutation survivors."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from flask import Flask, g

from backend import authz, outbound, security, sync, token_crypto


def test_auth_configuration_and_owner_precedence_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(authz.ADMIN_USERS_ENV, raising=False)
    monkeypatch.delenv(authz.REVIEWER_USERS_ENV, raising=False)
    assert authz.configured_login_role("XXXX", "nobody") == authz.ROLE_USER

    user = SimpleNamespace(id=7, role=authz.ROLE_USER)
    resource = SimpleNamespace(owner_user_id=8, user_id=7, created_by_user_id=7)
    assert authz.can(user, authz.ACTION_PRIVATE_WRITE, resource) is False
    assert authz.can(user, authz.ACTION_PRIVATE_WRITE, SimpleNamespace(user_id=7)) is True


def test_guard_metadata_and_cached_session_epoch_are_exact(monkeypatch: pytest.MonkeyPatch) -> None:
    assert getattr(security.login_required(lambda: "ok"), security.GUARD_ATTR) == "login_required"
    assert getattr(security.write_guard(lambda: "ok"), security.GUARD_ATTR) == "write_guard"

    app = Flask(__name__)
    app.secret_key = "mutation-test"

    @contextmanager
    def fail_if_opened() -> Iterator[None]:
        pytest.fail("cached session epoch unexpectedly queried the database")
        yield

    monkeypatch.setattr(security.db, "session_scope", fail_if_opened)
    with app.test_request_context("/"):
        g._session_epoch_ok = True
        assert security._session_epoch_current(7) is True


def test_rolling_limit_keeps_exact_constructor_and_boundary_state(monkeypatch: pytest.MonkeyPatch) -> None:
    limiter = security.RollingLimit(2, 3.5)
    assert limiter.limit == 2
    assert limiter.window == 3.5
    monkeypatch.setattr(security.time, "monotonic", lambda: 10.0)
    assert limiter.exceeded("client") is False
    assert limiter.exceeded("client") is False
    assert limiter.exceeded("client") is True
    limiter.clear()
    assert limiter.times == {}
    assert limiter.last_sweep == 0.0


def test_token_cipher_contract_and_errors_are_stable(monkeypatch: pytest.MonkeyPatch) -> None:
    assert token_crypto._derive_key("mutation-secret") == b"NdDMWuAi3izf08DUtxoslIoKoRngknl-Vkx04AOfOvI="
    monkeypatch.setattr(token_crypto, "_fernet", None)
    with pytest.raises(RuntimeError, match=r"^backend\.token_crypto\.configure\(\) has not been called$"):
        token_crypto.encrypt("grant")

    token_crypto.configure("mutation-secret")
    with pytest.raises(
        token_crypto.GrantDecryptionError, match=r"^stored Toolhub grant could not be decrypted$"
    ) as error:
        token_crypto.decrypt("v1:not-a-fernet-token")
    assert error.value.__cause__ is not None


def test_sync_normalizers_preserve_empty_ids_and_exact_error_cap() -> None:
    assert sync.clean_int(None) is None
    assert sync.clean_int("") is None
    assert sync.clean_int("0") == 0
    assert sync.clean_error(f"  {'x' * 2001}  ") == "x" * 2000


@pytest.mark.parametrize(
    ("url", "expected_host", "expected_port"),
    [
        ("https://public.example/path", "public.example", 443),
        ("http://public.example/path", "public.example", 80),
        ("https://public.example:8443/path", "public.example", 8443),
    ],
)
def test_outbound_validation_resolves_the_exact_destination(
    monkeypatch: pytest.MonkeyPatch, url: str, expected_host: str, expected_port: int
) -> None:
    calls: list[tuple[Any, ...]] = []

    def resolve(*args: Any, **kwargs: Any) -> list[tuple[Any, ...]]:  # noqa: ANN401 - socket-compatible fake
        calls.append((*args, kwargs))
        return [(None, None, None, None, ("93.184.216.34", expected_port))]

    monkeypatch.setattr(outbound.socket, "getaddrinfo", resolve)
    outbound.require_allowed(url, outbound.WIKIMEDIA_FEED, scheme_error="public URL required")
    assert calls == [(expected_host, expected_port, {"proto": outbound.socket.IPPROTO_TCP})]


def test_outbound_validation_rejects_a_missing_host_before_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        outbound.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: pytest.fail("hostless URL reached DNS"),
    )
    with pytest.raises(ValueError, match="public URL required"):
        outbound.require_allowed("https:///path", outbound.STRICT_PUBLIC, scheme_error="public URL required")


class _StreamResponse:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    def iter_content(self, chunk_size: int) -> Iterator[bytes]:
        assert chunk_size == outbound.CHUNK_BYTES
        yield from self._chunks


def test_outbound_body_cap_accepts_exact_limit_and_rejects_one_byte_over() -> None:
    assert outbound._read_capped(_StreamResponse([b"ab", b"cd"]), "https://public.example", 4) == b"abcd"
    with pytest.raises(ValueError, match="response larger than 4 bytes"):
        outbound._read_capped(_StreamResponse([b"abcd", b"e"]), "https://public.example", 4)
