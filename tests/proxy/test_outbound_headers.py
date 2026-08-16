# SPDX-License-Identifier: GPL-3.0-or-later
"""Outbound header validation for configuration-sourced values."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend.http_headers import clean_header_value, clean_secret_header_value  # noqa: E402

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
