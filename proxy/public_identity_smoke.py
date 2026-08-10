# SPDX-License-Identifier: GPL-3.0-or-later
"""Fail fast when Wikimedia LDAP no longer exposes the public identity bridge."""

from __future__ import annotations

import json
import sys

from backend.public_identity import ToolforgeIdentityProvider


def main() -> int:
    available = ToolforgeIdentityProvider().probe_schema()
    sys.stdout.write(json.dumps({"toolforgeIdentitySchema": "ready" if available else "unavailable"}) + "\n")
    return 0 if available else 1


if __name__ == "__main__":  # pragma: no cover - operator entrypoint
    raise SystemExit(main())
