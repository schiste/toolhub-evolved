# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for deterministic detection of coding-assistant involvement."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import source_authorship  # noqa: E402


def _evidence(result):
    return [signal["evidence"] for signal in result["signals"]]


def test_no_marker_and_no_signature_is_unknown_rather_than_no():
    result = source_authorship.detect(["README.md", "src/app.py", "tests/test_app.py"])

    # None, not False. Every assertion this module can make is about a trace a
    # tool left; an assistant driven from an editor leaves none, so "found
    # nothing" cannot be reported as "nobody used one" without saying more than
    # was measured.
    assert result["llmAssisted"] is None
    assert result["provider"] == ""
    assert result["model"] == ""
    assert result["signals"] == []


def test_vendor_marker_file_names_the_vendor_and_the_assistant():
    result = source_authorship.detect(["CLAUDE.md", "src/app.py"])

    assert result["llmAssisted"] is True
    assert result["provider"] == "anthropic"
    assert result["assistants"] == ["Claude Code"]
    assert _evidence(result) == ["CLAUDE.md"]
    # A configured assistant is not a stated model. Naming one here would put a
    # model nobody ever ran into the record.
    assert result["model"] == ""


def test_marker_directory_is_reported_once_however_many_files_it_holds():
    result = source_authorship.detect(
        [".claude/settings.json", ".claude/agents/reviewer.md", ".claude/commands/ship.md"]
    )

    assert _evidence(result) == [".claude/"]


def test_agents_md_counts_at_the_root_and_nowhere_else():
    # The one marker whose name is an ordinary English word: a repository about
    # software agents may document them under docs/, and that is not evidence
    # of anything.
    assert source_authorship.detect(["AGENTS.md"])["llmAssisted"] is True
    assert source_authorship.detect(["docs/agents.md"])["llmAssisted"] is None

    # It names no vendor, so neither does the record.
    assert source_authorship.detect(["AGENTS.md"])["provider"] == ""


def test_dot_directories_survive_the_path_cleaner():
    # Every marker directory starts with a dot, and a leading-"./" strip
    # written as lstrip("./") would eat it -- ".codex/x" became "codex/x" and
    # matched nothing at all.
    assert source_authorship.detect(["./.codex/config.toml"])["provider"] == "openai"
    assert source_authorship.detect([".github/copilot-instructions.md"])["provider"] == "github"


def _commit(message, *, name="Ada Lovelace", email="ada@example.org", sha="ab12cd34ef56"):
    return {
        "sha": sha,
        "authorName": name,
        "authorEmail": email,
        "committerName": name,
        "committerEmail": email,
        "message": message,
    }


def test_claude_trailer_states_the_model_and_a_bare_name_does_not():
    named = source_authorship.detect([], [_commit("feat: thing\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>")])

    assert named["provider"] == "anthropic"
    # The trailer is the one place in either kind of evidence where a model is
    # written down rather than inferred.
    assert named["model"] == "Claude Opus 5"

    bare = source_authorship.detect([], [_commit("feat: thing\n\nCo-Authored-By: Claude <noreply@anthropic.com>")])

    assert bare["llmAssisted"] is True
    assert bare["provider"] == "anthropic"
    assert bare["model"] == ""


def test_codex_and_copilot_are_recognised_by_the_identity_they_commit_under():
    codex = source_authorship.detect([], [_commit("chore: tidy", name="openai-codex", email="codex@openai.com")])
    copilot = source_authorship.detect([], [_commit("chore: tidy", name="Copilot", email="copilot@github.com")])

    assert (codex["provider"], codex["assistants"]) == ("openai", ["Codex"])
    assert (copilot["provider"], copilot["assistants"]) == ("github", ["GitHub Copilot"])


def test_a_person_writing_about_an_assistant_is_not_an_assistant():
    # The word in a message is someone discussing a tool. Only the whole phrase
    # a tool appends to its own commits counts.
    talking = source_authorship.detect([], [_commit("docs: explain why we do not use claude or codex here")])

    assert talking["llmAssisted"] is None

    announcing = source_authorship.detect(
        [], [_commit("fix: thing\n\nGenerated with [Claude Code](https://claude.com/claude-code)")]
    )

    assert announcing["provider"] == "anthropic"


def test_a_commit_identity_outranks_a_marker_file_that_names_another_vendor():
    result = source_authorship.detect(
        ["CLAUDE.md"], [_commit("chore: tidy", name="openai-codex", email="codex@openai.com")]
    )

    # Both are true and both are recorded. The column reports the one that
    # actually wrote a commit over the one that was merely configured.
    assert result["assistants"] == ["Claude Code", "Codex"]
    assert result["provider"] == "openai"


def test_two_markers_naming_two_vendors_leave_the_column_empty_not_arbitrary():
    result = source_authorship.detect(["CLAUDE.md", ".codex/config.toml"])

    assert result["llmAssisted"] is True
    assert result["assistants"] == ["Claude Code", "Codex"]
    # Both were configured, which the signal list says and one column cannot.
    # Picking either would make the record deny the other.
    assert result["provider"] == ""


def test_merge_rederives_the_verdict_from_both_partial_views():
    # The analyzer sees the paths it was budgeted to read; the clone sees the
    # whole tree and the commits. Neither contains the other.
    analyzed = source_authorship.detect(["README.md"])
    cloned = source_authorship.detect(["CLAUDE.md"], [_commit("Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>")])

    merged = source_authorship.merge(analyzed, cloned)

    assert merged["llmAssisted"] is True
    assert merged["provider"] == "anthropic"
    assert merged["model"] == "Claude Opus 5"
    assert len(merged["signals"]) == 2


def test_merge_tolerates_a_missing_or_older_stored_result():
    merged = source_authorship.merge(None, {}, {"signals": "not a list"}, source_authorship.detect(["CLAUDE.md"]))

    assert merged["provider"] == "anthropic"
    assert merged["schemaVersion"] == source_authorship.SCHEMA_VERSION


def test_a_listing_entry_that_names_no_path_is_skipped_rather_than_matched():
    """`"./"` and `"  "` are entries a tree listing produces, not filenames."""
    result = source_authorship.detect(["./", "  ", "", "./CLAUDE.md"])

    # The bare `./` is the repository root, and stripping its prefix leaves
    # nothing to match. Letting "" through would ask `MARKER_FILES` for the
    # empty name on every listing there is.
    assert _evidence(result) == ["CLAUDE.md"]
