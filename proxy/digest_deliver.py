# SPDX-License-Identifier: GPL-3.0-or-later
"""Backfill and drain the restart-safe digest delivery outbox."""

import os

from backend import digest_delivery, job_runner

DEFAULT_LIMIT = 100
MAX_LIMIT = 500


def _limit() -> int:
    try:
        return max(1, min(MAX_LIMIT, int(os.environ.get("DIGEST_DELIVERY_LIMIT", DEFAULT_LIMIT))))
    except (TypeError, ValueError):
        return DEFAULT_LIMIT


def run() -> dict[str, object]:
    """Repair missing outbox rows before draining a bounded due batch."""
    queued = digest_delivery.queue_published_editions()
    delivery = digest_delivery.deliver_pending(limit=_limit())
    return {"queued": queued, "delivery": delivery}


def main() -> int:
    return job_runner.run_job("digest-deliver", run, lock=True)


if __name__ == "__main__":  # pragma: no cover - Toolforge entrypoint
    raise SystemExit(main())
