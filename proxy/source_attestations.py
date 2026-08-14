# SPDX-License-Identifier: GPL-3.0-or-later
"""Rebuild generic toolinfo source identity attestations from local projections."""

from __future__ import annotations

import argparse

from backend import db, job_runner, source_attestations


def main(argv: list[str] | None = None) -> int:
    """Refresh all source bindings and derived relationships without network reads."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true", help="force a periodic full source audit")
    args = parser.parse_args(argv)

    def body() -> dict:
        if args.full:
            return source_attestations.refresh_full_batched()
        with db.advisory_lock(source_attestations.SOURCE_WRITER_LOCK) as acquired:
            if not acquired:
                return {"locked": True}
            with db.session_scope() as session:
                return source_attestations.refresh_incremental(session)

    return job_runner.run_job("source-attestations", body, lock=True)


if __name__ == "__main__":  # pragma: no cover - operator entrypoint
    raise SystemExit(main())
