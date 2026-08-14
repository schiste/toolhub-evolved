# SPDX-License-Identifier: GPL-3.0-or-later
"""Validate live LiftWing digest output against public production edition facts without database writes."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any
from urllib.parse import quote, urlparse

import requests

from backend import digests, outbound
from digest_regenerate import edition_argument

DEFAULT_PUBLIC_BASE = "https://toolhub-evolved.toolforge.org"
MAX_SOURCE_BYTES = 8 * 1024 * 1024
SOURCE_TIMEOUT_SECONDS = 30
SOURCE_POLICY = outbound.FetchPolicy(
    schemes=frozenset({"https"}),
    max_body_bytes=MAX_SOURCE_BYTES,
    follow_redirects=True,
    max_redirects=3,
    timeout=SOURCE_TIMEOUT_SECONDS,
)
SOURCE_CALLER = outbound.Caller(
    user_agent="toolhub-evolved/0.2 (LiftWing digest preflight)",
    accept="application/json",
    scheme_error="digest source must use HTTPS",
)


def clean_public_base(value: str) -> str:
    """Accept one credential-free HTTPS origin for the read-only source API."""
    candidate = value.strip().rstrip("/")
    parsed = urlparse(candidate)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        message = "public base must be a credential-free HTTPS origin"
        raise ValueError(message)
    return candidate


def fetch_edition_facts(
    period: digests.Period,
    *,
    public_base: str = DEFAULT_PUBLIC_BASE,
    session: requests.Session | None = None,
) -> list[dict[str, Any]]:
    """Fetch one immutable public edition's frozen facts with a response bound."""
    client = session or requests.Session()
    url = f"{clean_public_base(public_base)}/v1/digests/{period.cadence}/{quote(period.key, safe='-')}/"
    body = outbound.fetch_bounded(client, url, policy=SOURCE_POLICY, caller=SOURCE_CALLER)
    payload = json.loads(body)
    tools = payload.get("tools") if isinstance(payload, dict) else None
    if not isinstance(tools, list) or not tools:
        message = f"public digest {period.cadence}:{period.key} contained no tools"
        raise ValueError(message)
    facts = [item.get("facts") for item in tools if isinstance(item, dict)]
    if len(facts) != len(tools) or not all(isinstance(fact, dict) and fact.get("name") for fact in facts):
        message = f"public digest {period.cadence}:{period.key} contained malformed frozen facts"
        raise ValueError(message)
    return facts


def run(periods: list[digests.Period], *, public_base: str = DEFAULT_PUBLIC_BASE) -> dict[str, object]:
    """Exercise live inference, validation, and rendering without durable writes."""
    results: list[dict[str, object]] = []
    with requests.Session() as session:
        for period in periods:
            facts = fetch_edition_facts(period, public_base=public_base, session=session)
            editorial, model, used_fallback, response_payload = digests.generate_editorial(facts, period.cadence)
            if used_fallback:
                detail = (
                    response_payload.get("_toolhub_generation_error") if isinstance(response_payload, dict) else None
                ) or "unknown generation failure"
                message = f"LiftWing preflight failed for {period.cadence}:{period.key}: {detail}"
                raise RuntimeError(message)
            rendered = digests.render_editorial(period, editorial, facts, used_fallback=False)
            results.append(
                {
                    "edition": f"{period.cadence}:{period.key}",
                    "toolCount": len(facts),
                    "selectedToolCount": len(editorial["highlights"]),
                    "selectedTools": [item["tool_name"] for item in editorial["highlights"]],
                    "model": model,
                    "renderedBytes": {
                        "html": len(rendered[0].encode()),
                        "wikitext": len(rendered[1].encode()),
                        "text": len(rendered[2].encode()),
                    },
                }
            )
    return {"safe": True, "databaseWrites": False, "editions": results}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--edition", action="append", type=edition_argument, required=True)
    parser.add_argument("--public-base", default=DEFAULT_PUBLIC_BASE)
    args = parser.parse_args()
    json.dump(run(args.edition, public_base=args.public_base), fp=sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - operator entrypoint
    raise SystemExit(main())
