# SPDX-License-Identifier: GPL-3.0-or-later
"""Generate missed closed UTC editions and publish them to Meta-Wiki."""

from __future__ import annotations

import argparse

from backend import digests, job_runner


def run(*, limit: int | None = None) -> dict[str, object]:
    """Generate and publish in one locked, restart-safe coordinator pass.

    Generation is capped so publication is always reached. Anything left over is
    reported as `remaining` and picked up by the next pass, which keeps a large
    first backfill restart-safe instead of losing a whole run to the timeout.
    """
    generated = digests.generate_due_editions(limit=limit)
    publication = digests.publish_pending()
    return {"generated": generated, "publication": publication}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-editions",
        type=int,
        default=None,
        help=(
            "editions to generate in this pass "
            f"(default {digests.DEFAULT_MAX_EDITIONS_PER_RUN}); raise it for a supervised backfill"
        ),
    )
    args = parser.parse_args()
    if args.max_editions is not None and args.max_editions < 1:
        parser.error("--max-editions must be at least 1")
    return job_runner.run_job("digest-publish", lambda: run(limit=args.max_editions), lock=True)


if __name__ == "__main__":  # pragma: no cover - Toolforge entrypoint
    raise SystemExit(main())
