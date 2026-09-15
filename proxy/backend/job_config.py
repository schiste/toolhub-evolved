# SPDX-License-Identifier: GPL-3.0-or-later
"""Small, dependency-free helpers for environment-backed job settings."""

from __future__ import annotations

import os


def env_int(name: str, default: int) -> int:
    """Return an integer environment setting, falling back on invalid input."""
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    """Return a float environment setting, falling back on invalid input."""
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default
