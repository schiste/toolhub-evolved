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
CONVENTIONAL_SUBJECT = re.compile(
	r"^(?P<kind>[a-z][a-z0-9-]*)(?:\((?P<scope>[^)]+)\))?(?P<breaking>!)?:\s*(?P<summary>.+)$"
)
CATEGORY_LABELS = {
	"feat": "Features",
	"fix": "Fixes",
	"perf": "Performance",
	"docs": "Documentation",
	"test": "Tests",
	"chore": "Maintenance",
	"ci": "Maintenance",
	"ops": "Operations",
	"refactor": "Refactoring",
	"style": "Interface and accessibility",
}
CATEGORY_ORDER = (
	"Features",
	"Fixes",
	"Performance",
	"Interface and accessibility",
	"Documentation",
	"Operations",
	"Refactoring",
	"Tests",
	"Maintenance",
	"Other",
)
GENERATED_CHANGELOG_SUBJECT = "docs: regenerate changelog from git history"


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


def commits(
	max_count: int | None = MAX_COMMITS, revision_range: str | None = None
) -> list[dict[str, object]]:
	format_string = "%H%x1f%h%x1f%aI%x1f%an%x1f%s%x1e"
	args = ["log"]
	if revision_range:
		args.append(revision_range)
	if max_count is not None:
		args.append(f"--max-count={max_count}")
	args.append(f"--pretty=format:{format_string}")
	rows = git(*args).split("\x1e")
	items: list[dict[str, object]] = []
	for row in rows:
		parts = row.strip("\n").split(FIELD_SEPARATOR)
		if len(parts) != 5 or not parts[0]:
			continue
		sha, short_sha, authored_at, author, subject = parts
		if subject.strip() == GENERATED_CHANGELOG_SUBJECT:
			continue
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


def artifact(revision_range: str | None = None) -> dict[str, object]:
	return {
		"schemaVersion": 1,
		"generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
		"repository": "https://github.com/schiste/toolhub-evolved",
		"commits": commits(revision_range=revision_range),
	}


def markdown_escape(value: str) -> str:
	return value.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def render_markdown() -> str:
	all_commits = commits(None)
	by_date: dict[str, dict[str, list[dict[str, object]]]] = {}
	for commit in all_commits:
		date = str(commit["authoredAt"])[:10] or "Undated"
		kind = str(commit["kind"])
		category = CATEGORY_LABELS.get(kind, "Other")
		by_date.setdefault(date, {}).setdefault(category, []).append(commit)

	lines = [
		"# Changelog",
		"",
		"All notable Toolhub Evolved changes, grouped from the repository's Git history.",
		"This file is generated with `npm run changelog:generate`; do not edit it by hand.",
		"",
	]
	for date, categories in by_date.items():
		lines.extend([f"## {date}", ""])
		for category in CATEGORY_ORDER:
			items = categories.get(category, [])
			if not items:
				continue
			lines.extend([f"### {category}", ""])
			for commit in items:
				sha = str(commit["sha"])
				short_sha = str(commit["shortSha"])
				summary = markdown_escape(str(commit["summary"]))
				lines.append(
					f"- {summary} ([{short_sha}](https://github.com/schiste/toolhub-evolved/commit/{sha}))"
				)
			lines.append("")
	return "\n".join(lines).rstrip() + "\n"


def write(output: Path, revision_range: str | None = None) -> None:
	output.parent.mkdir(parents=True, exist_ok=True)
	output.write_text(
		json.dumps(artifact(revision_range), indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
	)
	print(f"changelog: wrote {output}")


def write_markdown(output: Path) -> None:
	output.write_text(render_markdown(), encoding="utf-8")
	print(f"changelog: wrote {output}")


def main() -> None:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
	parser.add_argument("--markdown-output", type=Path)
	parser.add_argument("--range", dest="revision_range", help="Git revision range to include")
	args = parser.parse_args()
	write(args.output, args.revision_range)
	if args.markdown_output:
		args.markdown_output.write_text(render_markdown(), encoding="utf-8")
		print(f"changelog: wrote {args.markdown_output}")


if __name__ == "__main__":
	main()
