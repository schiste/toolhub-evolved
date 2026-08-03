#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the public, deterministic changelog artifact from Git history."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "public_html/data/changelog.json"
FIELD_SEPARATOR = "\x1f"
MAX_COMMITS = 40
CONVENTIONAL_SUBJECT = re.compile(r"^(?P<kind>[a-z]+)(?:\((?P<scope>[^)]+)\))?(?P<breaking>!)?:\s*(?P<summary>.+)$")


def git(*args: str) -> str:
	return subprocess.run(
		["git", *args], cwd=ROOT, check=True, capture_output=True, text=True, timeout=10
	).stdout


def classify(subject: str) -> tuple[str, str, bool, str]:
	match = CONVENTIONAL_SUBJECT.match(subject.strip())
	if not match:
		return "other", "", False, subject.strip()
	return (
		match.group("kind"),
		match.group("scope") or "",
		bool(match.group("breaking")),
		match.group("summary").strip(),
	)


def commits() -> list[dict[str, object]]:
	format_string = "%H%x1f%h%x1f%aI%x1f%an%x1f%s%x1e"
	rows = git("log", f"--max-count={MAX_COMMITS}", f"--pretty=format:{format_string}").split("\x1e")
	items: list[dict[str, object]] = []
	for row in rows:
		parts = row.strip("\n").split(FIELD_SEPARATOR)
		if len(parts) != 5 or not parts[0]:
			continue
		sha, short_sha, authored_at, author, subject = parts
		kind, scope, breaking, summary = classify(subject)
		items.append(
			{
				"sha": sha,
				"shortSha": short_sha,
				"authoredAt": authored_at,
				"author": author,
				"subject": subject,
				"summary": summary,
				"kind": kind,
				"scope": scope,
				"breaking": breaking,
			}
		)
	return items


def artifact() -> dict[str, object]:
	return {
		"schemaVersion": 1,
		"generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
		"repository": "https://github.com/schiste/toolhub-evolved",
		"commits": commits(),
	}


def write(output: Path) -> None:
	output.parent.mkdir(parents=True, exist_ok=True)
	output.write_text(json.dumps(artifact(), indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
	print(f"changelog: wrote {output}")


def main() -> None:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
	args = parser.parse_args()
	write(args.output)


if __name__ == "__main__":
	main()
