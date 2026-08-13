# SPDX-License-Identifier: GPL-3.0-or-later
"""Rebuild generic toolinfo source identity attestations from local projections."""

from __future__ import annotations

import argparse
import json
import os
import sys

from backend import DEFAULT_DB_URL, db, source_attestations


def main(argv: list[str] | None = None) -> int:
    """Refresh all source bindings and derived relationships without network reads."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true", help="force a periodic full source audit")
    args = parser.parse_args(argv)
    db.configure(os.environ.get("TOOLHUB_DB_URL") or DEFAULT_DB_URL)
    db.init_schema()
    with db.advisory_lock("toolhub-evolved:source-attestations") as acquired:
        if not acquired:
            sys.stdout.write(json.dumps({"locked": True}, sort_keys=True) + "\n")
            return 0
        with db.session_scope() as session:
            summary = (
                source_attestations.refresh_full(session)
                if args.full
                else source_attestations.refresh_incremental(session)
            )
    sys.stdout.write("source-attestations: " + json.dumps(summary, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - operator entrypoint
    raise SystemExit(main())
