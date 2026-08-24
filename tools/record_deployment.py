#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Stage and promote successful deployments as a bounded public history."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PUBLIC_OUTPUT = ROOT / "public_html/data/deployments.json"
DEFAULT_HISTORY = Path.home() / ".toolhub-evolved-deploy-history.json"
MAX_DEPLOYMENTS = 50
MARKETING_FILES = {
    "technical": ROOT / "docs/CHANGELOG-TECHNICAL-MARKETING.md",
    "user": ROOT / "docs/CHANGELOG-USER.md",
}
RELEASE_ID_RE = re.compile(r"<!--\s*Release id:\s*(?P<value>[a-z0-9][a-z0-9-]*)\s*-->")
RELEASE_TITLE_RE = re.compile(r"<!--\s*Release title:\s*(?P<value>[^<]+?)\s*-->")


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


def release_metadata() -> dict[str, str]:
    """Read the stable public release identity shared by both note layers."""
    found: list[dict[str, str]] = []
    for path in MARKETING_FILES.values():
        value = path.read_text(encoding="utf-8")
        release_id = RELEASE_ID_RE.search(value)
        title = RELEASE_TITLE_RE.search(value)
        if not release_id or not title:
            raise RuntimeError(f"{path.name} must declare Release id and Release title headers")
        found.append({"id": release_id.group("value"), "title": title.group("value").strip()})
    if any(item != found[0] for item in found[1:]):
        raise RuntimeError("user and technical changelogs must describe the same public release")
    return found[0]


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
    # Schema-v2 rows represented deployments, not curated product releases.
    # Retire them once rather than surfacing every historical fix as a version.
    history = [item for item in load_history(history_path) if item.get("releaseId")]
    marketing = marketing_notes()
    release = release_metadata()
    validate_marketing(marketing)
    deployed_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    existing = next((item for item in history if item.get("releaseId") == release["id"]), None)
    if existing is None and any(item.get("marketing") == marketing for item in history):
        raise RuntimeError("a new release id reuses previous release notes; review and summarize the release")
    record = {
        "id": release["id"],
        "releaseId": release["id"],
        "title": release["title"],
        "sha": head,
        "deployedAt": deployed_at,
        "releasedAt": existing.get("releasedAt", existing.get("deployedAt")) if existing else deployed_at,
        "marketing": marketing,
    }
    history = [record, *(item for item in history if item.get("releaseId") != release["id"])]
    return history[:MAX_DEPLOYMENTS]


def prepare(public_output: Path, history_path: Path) -> None:
    """Write a candidate manifest without claiming the deployment succeeded."""
    history = staged_history(history_path)
    write_json(public_output, {"schemaVersion": 3, "deployments": history})
    print(f"releases: staged {public_output} ({len(history)} curated releases)")


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


def check() -> None:
    """Run every notes rule this module enforces, writing nothing.

    The rules below are what deploy.sh discovers, and it discovers them after
    the host has already fast-forwarded: a nine-bullet technical file aborted a
    release between `git pull` and the dist build, leaving the tool serving the
    previous build from the new checkout. Nothing here is new -- it is the same
    three calls `staged_history` makes -- so that a push can fail on the rule
    instead of a deployment failing on it.
    """
    try:
        notes = marketing_notes()
        release_metadata()
        validate_marketing(notes)
    except RuntimeError as error:
        # A traceback here would point at this module, but the fix is always in
        # the two notes files, so report the rule and where to apply it.
        print(f"release manifest: {error}", file=sys.stderr)
        print(f"edit {', '.join(sorted(path.name for path in MARKETING_FILES.values()))} and push again", file=sys.stderr)
        raise SystemExit(1) from None
    print("release manifest: notes parse, declare one release, and are within the bullet cap")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-output", type=Path, default=DEFAULT_PUBLIC_OUTPUT)
    parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY)
    parser.add_argument("--check", action="store_true", help="validate the checked-in notes and write nothing")
    parser.add_argument("--prepare", action="store_true", help="write a candidate manifest without updating history")
    parser.add_argument("--promote", type=Path, help="promote a prepared manifest after a successful smoke check")
    args = parser.parse_args()
    if args.check:
        check()
    elif args.promote:
        promote(args.promote, args.history)
    elif args.prepare:
        prepare(args.public_output, args.history)
    else:
        record(args.public_output, args.history)


if __name__ == "__main__":
    main()
