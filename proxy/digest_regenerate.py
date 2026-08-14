# SPDX-License-Identifier: GPL-3.0-or-later
"""Regenerate explicitly named website-only digest examples with LiftWing Qwen."""

from __future__ import annotations

import argparse

from backend import digests, job_runner


def edition_argument(value: str) -> digests.Period:
    """Parse CADENCE:KEY while retaining argparse's actionable error output."""
    cadence, separator, key = value.partition(":")
    if not separator:
        message = "edition must be CADENCE:KEY"
        raise argparse.ArgumentTypeError(message)
    try:
        return digests.period_from_key(cadence.strip().casefold(), key.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def run(periods: list[digests.Period]) -> dict[str, object]:
    """Replace all requested examples atomically after every Qwen draft validates."""
    editions = digests.regenerate_website_editions(periods)
    return {
        "regenerated": [f"{edition.cadence}:{edition.edition_key}" for edition in editions],
        "count": len(editions),
        "publicationScope": "website-only",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--edition",
        action="append",
        type=edition_argument,
        required=True,
        help="exact website-only edition as daily:YYYY-MM-DD, weekly:YYYY-Www, or monthly:YYYY-MM",
    )
    args = parser.parse_args()
    return job_runner.run_job("digest-regenerate", lambda: run(args.edition), lock=True)


if __name__ == "__main__":  # pragma: no cover - Toolforge operator entrypoint
    raise SystemExit(main())
