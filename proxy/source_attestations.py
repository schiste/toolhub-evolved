# SPDX-License-Identifier: GPL-3.0-or-later
"""Rebuild generic toolinfo source identity attestations from local projections."""

from __future__ import annotations

import json
import os
import sys

from backend import DEFAULT_DB_URL, db, source_attestations


def main() -> int:
    """Refresh all source bindings and derived relationships without network reads."""
    db.configure(os.environ.get("TOOLHUB_DB_URL") or DEFAULT_DB_URL)
    db.init_schema()
    with db.advisory_lock("toolhub-evolved:source-attestations") as acquired:
        if not acquired:
            sys.stdout.write(json.dumps({"locked": True}, sort_keys=True) + "\n")
            return 0
        with db.session_scope() as session:
            summary = source_attestations.refresh_all(session)
    sys.stdout.write("source-attestations: " + json.dumps(summary, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - operator entrypoint
    raise SystemExit(main())
