#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Stage and promote successful deployments as a bounded public history."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PUBLIC_OUTPUT = ROOT / "public_html/data/deployments.json"
DEFAULT_HISTORY = Path.home() / ".toolhub-evolved-deploy-history.json"
MAX_DEPLOYMENTS = 50
MARKETING_FILES = {
    "technical": ROOT / "docs/CHANGELOG-TECHNICAL-MARKETING.md",
    "user": ROOT / "docs/CHANGELOG-USER.md",
}


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True, timeout=10).stdout


def load_history(path: Path) -> list[dict[str, object]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    return value if isinstance(value, list) else []


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def clean_marketing(value: str) -> str:
    lines = [line for line in value.splitlines() if not line.startswith("<!--") and not line.startswith("# ")]
    return "\n".join(lines).strip()


def marketing_notes() -> dict[str, str]:
    notes: dict[str, str] = {}
    for name, path in MARKETING_FILES.items():
        try:
            value = path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            continue
        value = clean_marketing(value)
        if value:
            notes[name] = value
    missing = [name for name in MARKETING_FILES if not notes.get(name)]
    if missing:
        raise RuntimeError(f"missing required marketing changelog content: {', '.join(missing)}")
    return notes


def validate_marketing(notes: dict[str, str]) -> None:
    """Require concise reviewed bullets; never synthesize user copy from commits."""
    for audience, value in notes.items():
        lines = [line.strip() for line in value.splitlines() if line.strip()]
        if not all(line.startswith("- ") for line in lines):
            raise RuntimeError(f"{audience} marketing notes must contain bullet lines only")
        if not 3 <= len(lines) <= 8:
            raise RuntimeError(f"{audience} marketing notes must contain 3 to 8 bundled entries, found {len(lines)}")


def staged_history(history_path: Path) -> list[dict[str, object]]:
    head = git("rev-parse", "HEAD").strip()
    short_head = git("rev-parse", "--short=12", "HEAD").strip()
    history = load_history(history_path)
    marketing = marketing_notes()
    validate_marketing(marketing)
    if not history or history[0].get("sha") != head:
        if history and history[0].get("marketing") == marketing:
            raise RuntimeError("new deployment reuses the previous release notes; review and summarize this release")
        record = {
            "id": short_head,
            "sha": head,
            "deployedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "marketing": marketing,
        }
        history = [record, *history]
    else:
        if history[0].get("marketing") != marketing:
            history[0]["marketing"] = marketing
    return history[:MAX_DEPLOYMENTS]


def prepare(public_output: Path, history_path: Path) -> None:
    """Write a candidate manifest without claiming the deployment succeeded."""
    history = staged_history(history_path)
    write_json(public_output, {"schemaVersion": 2, "deployments": history})
    print(f"deployments: staged {public_output} ({len(history)} deploys)")


def promote(prepared_path: Path, history_path: Path) -> None:
    """Persist the exact manifest that passed the production smoke check."""
    value = json.loads(prepared_path.read_text(encoding="utf-8"))
    deployments = value.get("deployments") if isinstance(value, dict) else None
    if not isinstance(deployments, list) or not deployments:
        raise RuntimeError("prepared deployment manifest is empty or invalid")
    head = git("rev-parse", "HEAD").strip()
    if deployments[0].get("sha") != head:
        raise RuntimeError("prepared deployment manifest does not match the current checkout")
    write_json(history_path, deployments[:MAX_DEPLOYMENTS])
    print(f"deployments: promoted {head[:12]} after successful smoke check")


def record(public_output: Path, history_path: Path) -> None:
    """Compatibility entry point: stage and immediately promote."""
    prepare(public_output, history_path)
    promote(public_output, history_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-output", type=Path, default=DEFAULT_PUBLIC_OUTPUT)
    parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY)
    parser.add_argument("--prepare", action="store_true", help="write a candidate manifest without updating history")
    parser.add_argument("--promote", type=Path, help="promote a prepared manifest after a successful smoke check")
    args = parser.parse_args()
    if args.promote:
        promote(args.promote, args.history)
    elif args.prepare:
        prepare(args.public_output, args.history)
    else:
        record(args.public_output, args.history)


if __name__ == "__main__":
    main()
