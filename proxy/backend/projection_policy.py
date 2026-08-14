# SPDX-License-Identifier: GPL-3.0-or-later
"""Content-addressed versions for rebuildable projection policies."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType


def module_fingerprint(*modules: ModuleType, namespace: str) -> str:
    """Hash policy source so deployments cannot reuse projections from old code."""
    digest = hashlib.sha256(namespace.encode())
    for module in sorted(modules, key=lambda item: item.__name__):
        source_path = Path(str(module.__file__ or ""))
        digest.update(module.__name__.encode())
        digest.update(source_path.read_bytes())
    return f"sha256:{digest.hexdigest()}"
