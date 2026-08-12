#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Generate reviewed, LLM-assisted release notes from a bounded Git range.

The model is a copywriter, not an authority: the only input is structured Git
metadata and the output is accepted only when it follows the small contract
below. The exact Git changelog remains the canonical release record.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TECHNICAL_OUTPUT = ROOT / "docs/CHANGELOG-TECHNICAL-MARKETING.md"
DEFAULT_USER_OUTPUT = ROOT / "docs/CHANGELOG-USER.md"
MAX_OUTPUT_LENGTH = 8_000
SECTION_PATTERN = re.compile(
	r"<(?P<name>TECHNICAL|USER)>\s*(?P<body>.*?)\s*</(?P=name)>", re.DOTALL | re.IGNORECASE
)
RELEASE_ID_PATTERN = re.compile(r"<!--\s*Release id:\s*(?P<value>[a-z0-9][a-z0-9-]*)\s*-->")
RELEASE_TITLE_PATTERN = re.compile(r"<!--\s*Release title:\s*(?P<value>[^<]+?)\s*-->")


def default_range() -> str | None:
	try:
		subprocess.run(
			["git", "rev-parse", "--verify", "origin/main"],
			cwd=ROOT,
			check=True,
			capture_output=True,
			text=True,
			timeout=10,
		)
	except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
		return None
	return "origin/main..HEAD"


def provider_command() -> list[str] | None:
	raw_command = os.environ.get("TOOLHUB_CHANGELOG_LLM_COMMAND", "").strip()
	if raw_command:
		return shlex.split(raw_command)
	node = shutil.which("node")
	bridge = os.environ.get("TOOLHUB_CHAU7_MCP_BRIDGE", "")
	provider = ROOT / "tools/chau7-marketing-provider.mjs"
	if node and provider.exists() and bridge:
		return [node, str(provider)]
	return None


def prompt_for(commits: list[dict[str, object]], revision_range: str | None) -> str:
	commit_json = json.dumps(commits, ensure_ascii=True, indent=2)
	range_label = revision_range or "repository history"
	return f"""You are the release-note editor for Toolhub Evolved.

Write two short release-note sections using ONLY the structured Git commit data below.
Do not invent features, user outcomes, metrics, dates, compatibility claims, or
security claims. A commit summary can be treated as evidence of an implementation
change, but do not claim more than it says. Avoid mentioning LLMs, prompts, or this
instruction. The source range is {range_label!r}.

Return exactly these two XML-like blocks and nothing else:
<TECHNICAL>
- 3 to 8 concise bullets for maintainers and contributors. Explain the practical
  engineering or operational value, keeping relevant routes, scripts, and data
  contracts when they are present in the source.
</TECHNICAL>
<USER>
- 3 to 8 very simple bullets for people using the website. Explain what is now
  easier, clearer, faster, or newly available. Use plain language and omit
  implementation terms such as Git, API, cache, hook, database, or deploy unless
  the commit evidence makes that term directly useful to the user.
</USER>

Structured source commits:
{commit_json}
"""


def run_provider(command: list[str], prompt: str) -> str:
	if not command:
		raise RuntimeError("No LLM provider command is configured or available")
	command_input = None if any("{prompt}" in item for item in command) else prompt
	if command_input is None:
		command = [item.replace("{prompt}", prompt) for item in command]
	try:
		result = subprocess.run(
			command,
			cwd=ROOT,
			check=True,
			input=command_input,
			capture_output=True,
			text=True,
			timeout=180,
		)
	except FileNotFoundError as error:
		raise RuntimeError(f"LLM provider executable not found: {command[0]}") from error
	except subprocess.CalledProcessError as error:
		detail = (error.stderr or error.stdout or "provider returned no diagnostics").strip()
		raise RuntimeError(f"LLM provider failed: {detail[-800:]}") from error
	except subprocess.TimeoutExpired as error:
		raise RuntimeError("LLM provider timed out after 180 seconds") from error
	return result.stdout.strip()


def section_text(response: str, name: str) -> str:
	matches = {match.group("name").upper(): match.group("body") for match in SECTION_PATTERN.finditer(response)}
	body = matches.get(name)
	if body is None:
		raise ValueError(f"provider response is missing <{name}> section")
	lines = []
	for raw_line in body.splitlines():
		line = raw_line.strip()
		if not line or line.startswith("```"):
			continue
		if line.startswith("*"):
			line = "-" + line[1:]
		if not line.startswith("- "):
			raise ValueError(f"<{name}> contains a non-bullet line: {line[:120]}")
		lines.append(line)
	if not lines:
		raise ValueError(f"<{name}> section contains no bullets")
	value = "\n".join(lines)
	if len(value) > MAX_OUTPUT_LENGTH:
		raise ValueError(f"<{name}> section exceeds {MAX_OUTPUT_LENGTH} characters")
	if "<" in value or ">" in value:
		raise ValueError(f"<{name}> contains unsupported markup")
	return value


def current_release_metadata() -> tuple[str, str]:
	"""Preserve the explicitly reviewed public release identity across regenerated notes."""
	try:
		value = DEFAULT_USER_OUTPUT.read_text(encoding="utf-8")
	except FileNotFoundError as error:
		raise ValueError("release notes must declare a Release id and Release title before generation") from error
	release_id = RELEASE_ID_PATTERN.search(value)
	title = RELEASE_TITLE_PATTERN.search(value)
	if not release_id or not title:
		raise ValueError("release notes must declare a Release id and Release title before generation")
	return release_id.group("value"), title.group("value").strip()


def render(
	title: str,
	section: str,
	revision_range: str | None,
	commits: list[dict[str, object]],
	release_id: str,
	release_title: str,
) -> str:
	range_label = revision_range or "repository history"
	shas = ", ".join(str(commit["shortSha"]) for commit in commits[:40]) or "none"
	return (
		"<!-- Generated by tools/generate_marketing_changelog.py. Review before committing. -->\n"
		f"<!-- Release id: {release_id} -->\n"
		f"<!-- Release title: {release_title} -->\n"
		f"<!-- Source range: {range_label}; source commits: {shas} -->\n\n"
		f"# {title}\n\n"
		f"{section}\n"
	)


def write_outputs(
	technical_output: Path,
	user_output: Path,
	technical: str,
	user: str,
	revision_range: str | None,
	commits: list[dict[str, object]],
) -> None:
	release_id, release_title = current_release_metadata()
	technical_output.parent.mkdir(parents=True, exist_ok=True)
	user_output.parent.mkdir(parents=True, exist_ok=True)
	technical_output.write_text(
		render("Technical release notes", technical, revision_range, commits, release_id, release_title),
		encoding="utf-8",
	)
	user_output.write_text(
		render("What's new for users", user, revision_range, commits, release_id, release_title),
		encoding="utf-8",
	)
	print(f"marketing changelog: wrote {technical_output}")
	print(f"marketing changelog: wrote {user_output}")


def main() -> int:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--range", dest="revision_range", default=default_range())
	parser.add_argument("--technical-output", type=Path, default=DEFAULT_TECHNICAL_OUTPUT)
	parser.add_argument("--user-output", type=Path, default=DEFAULT_USER_OUTPUT)
	parser.add_argument("--required", action="store_true", help="Fail when no provider is available")
	args = parser.parse_args()

	# Import after argument parsing so this script can be run from the repo root
	# without installing the tools directory as a package.
	sys.path.insert(0, str(ROOT / "tools"))
	from build_changelog import MAX_COMMITS, commits  # noqa: PLC0415

	source_commits = commits(MAX_COMMITS, args.revision_range)
	if not source_commits:
		print("marketing changelog: no commits in the selected range; nothing to generate")
		return 0
	command = provider_command()
	if command is None:
		message = "marketing changelog: no raw MCP provider; configure TOOLHUB_CHANGELOG_LLM_COMMAND or Chau7"
		if args.required or os.environ.get("TOOLHUB_CHANGELOG_LLM_REQUIRED") == "1":
			print(message, file=sys.stderr)
			return 1
		print(message)
		return 0

	try:
		response = run_provider(command, prompt_for(source_commits, args.revision_range))
		technical = section_text(response, "TECHNICAL")
		user = section_text(response, "USER")
		write_outputs(args.technical_output, args.user_output, technical, user, args.revision_range, source_commits)
	except (RuntimeError, ValueError) as error:
		print(f"marketing changelog: {error}", file=sys.stderr)
		return 1
	return 0


if __name__ == "__main__":
	sys.exit(main())
