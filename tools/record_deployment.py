#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Record the last two successful deploys as a small public JSON artifact."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PUBLIC_OUTPUT = ROOT / "public_html/data/deployments.json"
DEFAULT_HISTORY = Path.home() / ".toolhub-evolved-deploy-history.json"
FIELD_SEPARATOR = "\x1f"
MARKETING_FILES = {
	"technical": ROOT / "docs/CHANGELOG-TECHNICAL-MARKETING.md",
	"user": ROOT / "docs/CHANGELOG-USER.md",
}


def git(*args: str) -> str:
	return subprocess.run(
		["git", *args], cwd=ROOT, check=True, capture_output=True, text=True, timeout=10
	).stdout


def commit_rows(revision_range: str | None = None, max_count: int = 40) -> list[dict[str, str]]:
	format_string = "%H%x1f%h%x1f%aI%x1f%s%x1e"
	args = ["log", f"--max-count={max_count}", f"--pretty=format:{format_string}"]
	if revision_range:
		args.insert(1, revision_range)
	rows = git(*args).split("\x1e")
	items: list[dict[str, str]] = []
	for row in rows:
		parts = row.strip("\n").split(FIELD_SEPARATOR)
		if len(parts) != 4 or not parts[0]:
			continue
		sha, short_sha, authored_at, subject = parts
		items.append({"sha": sha, "shortSha": short_sha, "authoredAt": authored_at, "subject": subject})
	return items


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


def record(public_output: Path, history_path: Path) -> None:
	head = git("rev-parse", "HEAD").strip()
	short_head = git("rev-parse", "--short=12", "HEAD").strip()
	history = load_history(history_path)
	marketing = marketing_notes()
	if not history or history[0].get("sha") != head:
		previous = str(history[0].get("sha")) if history else ""
		try:
			changes = commit_rows(f"{previous}..{head}" if previous else None)
		except subprocess.CalledProcessError:
			changes = commit_rows()
		record = {
			"id": short_head,
			"sha": head,
			"deployedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
			"changes": changes,
		}
		record["marketing"] = marketing
		history = [record, *history[:1]]
	elif history[0].get("marketing") != marketing:
		history[0]["marketing"] = marketing
	history_path.parent.mkdir(parents=True, exist_ok=True)
	write_json(history_path, history)
	write_json(public_output, {"schemaVersion": 1, "deployments": history[:2]})
	print(f"deployments: wrote {public_output} ({len(history[:2])} deploys)")


def main() -> None:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--public-output", type=Path, default=DEFAULT_PUBLIC_OUTPUT)
	parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY)
	args = parser.parse_args()
	record(args.public_output, args.history)


if __name__ == "__main__":
	main()
