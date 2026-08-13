# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: INP001
"""Append one structured deployment-stage diagnostic to a durable JSONL log."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _timestamp(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _metrics(path: str) -> dict[str, Any]:
    if not path:
        return {}
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}
    tail = lines[-1].strip() if lines else ""
    candidate = tail.partition(":")[2].strip() if ":" in tail else tail
    try:
        decoded = json.loads(candidate)
    except json.JSONDecodeError:
        decoded = None
    if isinstance(decoded, dict):
        return decoded
    pairs: dict[str, Any] = {}
    for token in candidate.split():
        key, separator, value = token.partition("=")
        if separator and key:
            pairs[key] = value
    return pairs or ({"summary": tail[:1000]} if tail else {})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--deployment", required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--status", choices=("completed", "failed", "recovered"), required=True)
    parser.add_argument("--started", type=float, required=True)
    parser.add_argument("--finished", type=float, required=True)
    parser.add_argument("--metrics-file", default="")
    parser.add_argument("--failure-phase", default="")
    args = parser.parse_args(argv)
    record = {
        "deployment": args.deployment,
        "stage": args.stage,
        "status": args.status,
        "startedAt": _timestamp(args.started),
        "finishedAt": _timestamp(args.finished),
        "durationMs": round(max(0, args.finished - args.started) * 1000),
        "metrics": _metrics(args.metrics_file),
        "failurePhase": args.failure_phase or None,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - operator utility
    raise SystemExit(main())
