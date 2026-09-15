# SPDX-License-Identifier: GPL-3.0-or-later
"""Compatibility access for dependencies historically patched on v1.

Tests and extensions have long replaced provider singletons on
``backend.v1``. Route blueprints use this narrow adapter so the aggregator is
not bound directly throughout the resource modules, while those integrations
keep their existing patch points until they can move to explicit dependency
wiring.
"""

from typing import Any

from backend import v1 as legacy_v1


def value(name: str, default: Any = None) -> Any:  # noqa: ANN401
    """Read a legacy v1 dependency only when a request actually needs it."""
    return getattr(legacy_v1, name, default)
