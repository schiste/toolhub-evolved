# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression tests for the repository-shipped Toolhub creation skill."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills" / "toolhub-creation" / "scripts" / "toolinfo.py"
EXAMPLE = ROOT / "skills" / "toolhub-creation" / "assets" / "toolinfo.example.json"


def run_skill(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed local interpreter and repository script.
        [sys.executable, str(SCRIPT), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def test_example_validates_with_the_expected_toolforge_project() -> None:
    result = run_skill("check", str(EXAMPLE), "--toolforge-project", "example")

    assert result.returncode == 0
    assert "1 valid Toolinfo 1.2.2 record" in result.stdout


def test_create_structures_identity_and_refuses_to_overwrite(tmp_path: Path) -> None:
    output = tmp_path / "toolinfo.json"
    arguments = (
        "create",
        "--toolforge-project",
        "citation-bot",
        "--title",
        "Citation Bot",
        "--description",
        "Helps editors improve citations.",
        "--url",
        "https://citation-bot.toolforge.org/",
        "--author-name",
        "Ada",
        "--wiki-username",
        "AdaWiki",
        "--developer-username",
        "ada",
        "--output",
        str(output),
    )

    assert run_skill(*arguments).returncode == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["name"] == "toolforge-citation-bot"
    assert payload["author"] == [{"name": "Ada", "wiki_username": "AdaWiki", "developer_username": "ada"}]
    assert run_skill(*arguments).returncode == 1


def test_check_rejects_annotation_fields_and_wrong_project_name(tmp_path: Path) -> None:
    path = tmp_path / "toolinfo.json"
    payload = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    payload["name"] = "wrong-name"
    payload["audiences"] = ["developers"]
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = run_skill("check", str(path), "--toolforge-project", "example")

    assert result.returncode == 1
    assert "name must be toolforge-example" in result.stderr
    assert "audiences is a Toolhub annotation" in result.stderr
