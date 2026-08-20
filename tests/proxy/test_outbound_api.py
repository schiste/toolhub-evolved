# SPDX-License-Identifier: GPL-3.0-or-later
"""Credential handling and status reporting for source-host API fetches.

The interesting property here is negative: the token must not survive a
redirect that leaves the host it was issued for. A provider we query is also a
party that can answer with a Location header, so "follow redirects" and "send
the credential" have to be two separate decisions.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import outbound  # noqa: E402

CALLER = outbound.Caller(
    user_agent="toolhub-evolved-tests/1.0 (https://example.org)",
    accept="application/vnd.github+json",
    scheme_error="only source-host APIs are fetched",
)
TOKEN = "ghp-not-a-real-token"


# requests.Response computes is_redirect as "a redirect status AND a Location
# header", which is what keeps 304 -- also a 3xx -- out of the redirect path.
# The fake mirrors that rather than testing 300 <= status < 400, so the
# missing-Location case below stays a real assertion about fetch_api.
REDIRECT_STATI = (301, 302, 303, 307, 308)


class FakeApiResp:
    def __init__(self, status=200, headers=None, body=b""):
        self.status_code = status
        self.headers = dict(headers or {})
        located = "Location" in self.headers or "location" in self.headers
        self.is_redirect = status in REDIRECT_STATI and located
        self.is_permanent_redirect = status in (301, 308) and located
        self._body = body

    def iter_content(self, _chunk):
        yield self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeApiSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs["headers"]))
        return self.responses.pop(0)


@pytest.fixture(autouse=True)
def _no_guard(monkeypatch):
    # require_allowed has its own tests; these cover what fetch_api adds on top.
    monkeypatch.setattr(outbound, "require_allowed", lambda *_a, **_k: None)


def test_a_successful_fetch_returns_status_body_and_allowlisted_headers():
    session = FakeApiSession(
        [
            FakeApiResp(
                headers={
                    "ETag": 'W/"abc123"',
                    "X-RateLimit-Remaining": "4987",
                    "Set-Cookie": "session=secret",
                    "X-Request-Id": "trace-me",
                },
                body=b'{"archived": false}',
            )
        ]
    )

    result = outbound.fetch_api(session, "https://api.github.com/repos/o/r", caller=CALLER, token=TOKEN)

    assert result.status_code == 200
    assert result.body == b'{"archived": false}'
    assert result.headers == {"etag": 'W/"abc123"', "x-ratelimit-remaining": "4987"}
    assert result.not_modified is False


def test_the_token_is_sent_as_a_bearer_credential():
    session = FakeApiSession([FakeApiResp()])

    outbound.fetch_api(session, "https://api.github.com/repos/o/r", caller=CALLER, token=TOKEN)

    _url, headers = session.calls[0]
    assert headers["Authorization"] == f"Bearer {TOKEN}"
    assert "If-None-Match" not in headers


def test_an_unauthenticated_fetch_sends_no_authorization_header():
    session = FakeApiSession([FakeApiResp()])

    outbound.fetch_api(session, "https://codeberg.org/api/v1/repos/o/r", caller=CALLER)

    _url, headers = session.calls[0]
    assert "Authorization" not in headers


def test_a_stored_etag_is_sent_as_a_conditional_request():
    session = FakeApiSession([FakeApiResp(status=304, headers={"ETag": 'W/"abc123"'})])

    result = outbound.fetch_api(
        session, "https://api.github.com/repos/o/r", caller=CALLER, token=TOKEN, etag='W/"abc123"'
    )

    _url, headers = session.calls[0]
    assert headers["If-None-Match"] == 'W/"abc123"'
    # A 304 is the cheapest useful answer, and it carries no body to read.
    assert result.not_modified is True
    assert result.body == b""


def test_the_token_survives_a_redirect_that_stays_on_the_same_host():
    # A renamed GitHub repository 301s to its new name; that is a fact worth
    # having, and the credential is still going where it was issued.
    session = FakeApiSession(
        [
            FakeApiResp(status=301, headers={"Location": "https://api.github.com/repos/o/renamed"}),
            FakeApiResp(body=b"{}"),
        ]
    )

    result = outbound.fetch_api(session, "https://api.github.com/repos/o/r", caller=CALLER, token=TOKEN)

    assert result.url == "https://api.github.com/repos/o/renamed"
    assert all("Authorization" in headers for _url, headers in session.calls)


def test_the_token_is_dropped_the_moment_a_redirect_leaves_its_host():
    session = FakeApiSession(
        [
            FakeApiResp(status=302, headers={"Location": "https://collector.example/steal"}),
            FakeApiResp(body=b"{}"),
        ]
    )

    result = outbound.fetch_api(session, "https://api.github.com/repos/o/r", caller=CALLER, token=TOKEN)

    first, second = session.calls
    assert "Authorization" in first[1]
    assert "Authorization" not in second[1]
    # The rest of the request is unchanged: only the credential is withheld.
    assert second[1]["User-Agent"] == CALLER.user_agent
    assert result.url == "https://collector.example/steal"


def test_an_error_status_is_returned_as_data_rather_than_raised():
    # 404 means the project is gone and 403 can mean the budget is spent. Both
    # are recorded by the lane, so neither may become an exception here.
    for status in (403, 404, 500):
        session = FakeApiSession([FakeApiResp(status=status, body=b'{"message": "nope"}')])
        result = outbound.fetch_api(session, "https://api.github.com/repos/o/r", caller=CALLER)
        assert result.status_code == status


def test_a_redirect_without_a_location_is_an_error():
    # An empty Location is the case a real server actually produces; requests
    # would not flag a header-less 302 as a redirect at all.
    session = FakeApiSession([FakeApiResp(status=302, headers={"Location": ""})])

    with pytest.raises(ValueError, match="redirect missing Location header"):
        outbound.fetch_api(session, "https://api.github.com/repos/o/r", caller=CALLER)


def test_a_redirect_chain_is_bounded():
    session = FakeApiSession(
        [FakeApiResp(status=302, headers={"Location": f"/hop{index}"}) for index in range(10)]
    )

    with pytest.raises(ValueError, match="too many redirects"):
        outbound.fetch_api(session, "https://api.github.com/repos/o/r", caller=CALLER)


def test_an_oversized_body_is_refused_rather_than_buffered():
    session = FakeApiSession([FakeApiResp(body=b"x" * (outbound.PROVIDER_API.max_body_bytes + 1))])

    with pytest.raises(ValueError, match="larger than"):
        outbound.fetch_api(session, "https://api.github.com/repos/o/r", caller=CALLER)


def test_a_response_without_usable_headers_yields_no_headers():
    assert outbound._safe_headers(None) == {}


def test_a_header_value_cannot_grow_without_bound():
    assert len(outbound._safe_headers({"Link": "y" * 5000})["link"]) == 1024
