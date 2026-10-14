# SPDX-License-Identifier: GPL-3.0-or-later
"""Validation boundary for canonical Toolhub records with Evolved metadata."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator, Draft202012Validator, FormatChecker
from referencing import Registry, Resource

CANONICAL_SCHEMA_URI = (
    "https://raw.githubusercontent.com/wikimedia/wikimedia-toolhub/main/jsonschema/toolinfo/1.2.2.json"
)
_SCHEMA_ROOT = Path(__file__).resolve().parents[2] / "schemas"


class ToolinfoValidationError(ValueError):
    """A canonical Toolhub record or Evolved extension is invalid."""


@lru_cache(maxsize=1)
def _validators() -> tuple[Draft7Validator, Draft202012Validator]:
    canonical = json.loads((_SCHEMA_ROOT / "toolinfo-1.2.2.schema.json").read_text(encoding="utf-8"))
    evolved = json.loads((_SCHEMA_ROOT / "toolinfo-evolved-extension-1.0.0.schema.json").read_text(encoding="utf-8"))
    Draft7Validator.check_schema(canonical)
    Draft202012Validator.check_schema(evolved)
    registry = Registry().with_resource(CANONICAL_SCHEMA_URI, Resource.from_contents(canonical))
    format_checker = FormatChecker()
    return (
        Draft7Validator(canonical, format_checker=format_checker),
        Draft202012Validator(evolved, registry=registry, format_checker=format_checker),
    )


def _raise_first_error(validator: Any, document: object, label: str) -> None:  # noqa: ANN401 - jsonschema validator dialects differ
    error = next(validator.iter_errors(document), None)
    if error is None:
        return
    path = "/".join(str(part) for part in error.absolute_path) or "$"
    message = f"{label} validation failed at {path}: {error.message}"
    raise ToolinfoValidationError(message)


def validate_canonical_document(document: object) -> None:
    """Validate the canonical record or record array with Toolhub 1.2.2."""
    canonical_validator, _ = _validators()
    _raise_first_error(canonical_validator, document, "Canonical Toolhub 1.2.2")


def validate_toolinfo_document(document: object) -> None:
    """Validate the canonical base, Evolved extension, and analysis binding."""
    validate_canonical_document(document)
    _, evolved_validator = _validators()
    _raise_first_error(evolved_validator, document, "Toolhub Evolved 1.0.0")
    records = [document] if isinstance(document, dict) else document
    if not isinstance(records, list):
        return
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        evolved = record.get("evolved")
        if not isinstance(evolved, dict):
            continue
        analysis = evolved["analysis"]
        if analysis["revision"] != evolved["revision"]:
            message = f"Evolved analysis revision does not match artifact revision at record {index}"
            raise ToolinfoValidationError(message)
        if analysis["content_sha256"] != evolved["content_sha256"]:
            message = f"Evolved analysis digest does not match artifact digest at record {index}"
            raise ToolinfoValidationError(message)
