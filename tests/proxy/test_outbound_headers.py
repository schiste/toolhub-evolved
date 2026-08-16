# SPDX-License-Identifier: GPL-3.0-or-later
"""Outbound header validation for configuration-sourced values."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import requests  # noqa: E402

from backend import wikimedia_delivery  # noqa: E402
from backend.http_headers import clean_header_value, clean_secret_header_value  # noqa: E402
from backend.wikimedia_delivery import WikimediaAPIError, WikimediaClient  # noqa: E402

# The exact shape a wrapped Toolforge envvar produces: the newline is interior,
# so str.strip() leaves it in place and requests rejects the header.
WRAPPED_USER_AGENT = "ToolhubDigest/1.0 (https://toolhub-evolved.toolforge.org/digests;\n mailto:ops@example.org)"


def test_interior_newline_folds_to_one_space() -> None:
    assert clean_header_value("WIKIMEDIA_USER_AGENT", WRAPPED_USER_AGENT) == (
        "ToolhubDigest/1.0 (https://toolhub-evolved.toolforge.org/digests; mailto:ops@example.org)"
    )


@pytest.mark.parametrize("raw", ["a\r\nb", "a\tb", "a\n\n  b", "  a  b  "])
def test_every_whitespace_run_collapses(raw: str) -> None:
    cleaned = clean_header_value("HEADER", raw)
    assert "\n" not in cleaned
    assert "\r" not in cleaned
    assert "\t" not in cleaned
    assert "  " not in cleaned


def test_control_characters_are_refused_without_quoting_the_value() -> None:
    with pytest.raises(ValueError) as excinfo:
        clean_header_value("WIKIMEDIA_USER_AGENT", "Toolhub\x00Digest")
    assert "WIKIMEDIA_USER_AGENT" in str(excinfo.value)
    assert "Toolhub" not in str(excinfo.value)


def test_secret_keeps_outer_whitespace_stripped() -> None:
    # A trailing newline from a heredoc is not part of the secret.
    assert clean_secret_header_value("WIKIMEDIA_ACCESS_TOKEN", "  token-value\n") == "token-value"


def test_secret_is_never_repaired_by_folding() -> None:
    with pytest.raises(ValueError):
        clean_secret_header_value("WIKIMEDIA_ACCESS_TOKEN", "first-half\nsecond-half")


def test_secret_error_never_quotes_the_credential() -> None:
    with pytest.raises(ValueError) as excinfo:
        clean_secret_header_value("WIKIMEDIA_ACCESS_TOKEN", "super\nsecret")
    message = str(excinfo.value)
    assert "WIKIMEDIA_ACCESS_TOKEN" in message
    assert "super" not in message
    assert "secret" not in message


def test_empty_secret_stays_empty() -> None:
    assert clean_secret_header_value("WIKIMEDIA_ACCESS_TOKEN", "   ") == ""


def test_client_repairs_a_wrapped_user_agent_envvar(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WIKIMEDIA_USER_AGENT", WRAPPED_USER_AGENT)
    monkeypatch.delenv("WIKIMEDIA_ACCESS_TOKEN", raising=False)
    client = WikimediaClient()
    assert "\n" not in client.user_agent
    # The repaired value is transmittable: requests validates headers on send.
    requests.models.PreparedRequest().prepare_headers({"User-Agent": client.user_agent})


def test_client_refuses_a_wrapped_access_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WIKIMEDIA_ACCESS_TOKEN", "first-half\nsecond-half")
    with pytest.raises(ValueError) as excinfo:
        WikimediaClient()
    assert "first-half" not in str(excinfo.value)


def test_wrapped_liftwing_user_agent_degrades_instead_of_stopping_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Editorial generation records a diagnostic and falls back; it must not raise."""
    from backend import digests

    monkeypatch.setenv("LIFTWING_API_URL", "https://api.wikimedia.org/service/lw/inference/v1/models/x:predict")
    # os.environ itself refuses a NUL, so use another non-whitespace control character.
    monkeypatch.setenv("LIFTWING_USER_AGENT", "toolhub\x01evolved")
    # A non-empty fact list: _fallback_editorial indexes titles[0] unconditionally,
    # and empty periods never reach generation because they produce no edition.
    facts = [{"name": "example-tool", "title": "Example Tool"}]
    _editorial, _model, fell_back, payload = digests.generate_editorial(facts, "daily")
    assert fell_back is True
    assert isinstance(payload, dict)
    assert "LIFTWING_USER_AGENT" in str(payload.get("_toolhub_generation_error"))


def test_transport_errors_never_carry_the_access_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """A transport exception that quotes the Authorization header must not reach a caller intact."""
    token = "super-secret-token"  # noqa: S105 - test fixture, not a real credential
    client = WikimediaClient(access_token=token, user_agent="Test/1.0")

    def explode(*_args: object, **_kwargs: object) -> object:
        # requests.InvalidHeader quotes the offending header value verbatim.
        message = f"Invalid return character in header value: 'Bearer {token}'"
        raise requests.RequestException(message)

    monkeypatch.setattr(wikimedia_delivery.requests, "request", explode)
    with pytest.raises(WikimediaAPIError) as excinfo:
        client.request("meta.wikimedia.org", "GET", {"action": "query"})
    assert token not in str(excinfo.value)
    assert wikimedia_delivery.REDACTED in str(excinfo.value)
