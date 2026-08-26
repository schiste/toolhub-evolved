# SPDX-License-Identifier: GPL-3.0-or-later
"""Deterministic detection of coding-assistant involvement in a repository.

Two kinds of evidence, and both are things a tool wrote down rather than
things a reader inferred:

* **Marker files.** An assistant that takes standing instructions reads them
  from a path it defines: ``CLAUDE.md`` for Claude Code, ``.codex/`` for
  Codex, ``.github/copilot-instructions.md`` for Copilot. The file is in the
  repository because somebody configured that assistant on this repository.
* **Commit identities.** An assistant that commits signs the commit -- as its
  author, its committer, or a ``Co-authored-by:`` trailer. Claude Code's
  trailer names the model it ran as, which is the only place in either kind of
  evidence where a model name is ever stated outright.

The verdict is True or unknown, never False. Finding no marker file and no
assistant identity means these particular traces are absent, which is not the
same as knowing a person typed every line: an assistant driven from an editor,
with its config never checked in, leaves nothing here to find. Recording that
as "no LLM" would state something this module cannot see.

Equally, True says *assisted*, not *generated*. A ``CLAUDE.md`` proves the
tooling was set up here; it does not measure how much of the code came out of
it. Nothing below reads a file's contents -- only its path, and the commit
metadata git already holds -- so nothing below could measure that anyway.
"""

import re
from typing import Any

#: Bumped when the shape of a result changes, so a stored report from an older
#: scan can be told apart from read as a malformed current one.
SCHEMA_VERSION = 1

#: Vendor slugs. The vendor of the *assistant*, not of the model it happened to
#: be pointed at: Aider and its kind run against whichever API the user
#: configured, which is why they name no provider below.
ANTHROPIC = "anthropic"
OPENAI = "openai"
GITHUB = "github"
GOOGLE = "google"
CURSOR = "cursor"
CODEIUM = "codeium"

#: Marker files matched on the final path segment at any depth. Every name here
#: is vendor-specific enough that it is not plausibly about something else: a
#: repository does not contain a `CLAUDE.md` by coincidence.
MARKER_FILES: dict[str, tuple[str, str]] = {
    "claude.md": (ANTHROPIC, "Claude Code"),
    "claude.local.md": (ANTHROPIC, "Claude Code"),
    "gemini.md": (GOOGLE, "Gemini CLI"),
    ".cursorrules": (CURSOR, "Cursor"),
    ".windsurfrules": (CODEIUM, "Windsurf"),
    ".aider.conf.yml": ("", "Aider"),
    ".aider.chat.history.md": ("", "Aider"),
}

#: Marker files matched only at the repository root. `AGENTS.md` is the one
#: marker whose name is an ordinary English word, and a repository about
#: software agents may well document them in `docs/agents.md`. At the root it
#: is the convention and nothing else; anywhere else it is a guess, and this
#: layer does not guess.
ROOT_MARKER_FILES: dict[str, tuple[str, str]] = {
    "agents.md": ("", "agent instructions"),
}

#: Marker directories, matched on any path segment. A directory is evidence
#: through the files inside it, so one hit per repository is enough -- the
#: signal is "this assistant is configured here", however many files say so.
MARKER_DIRS: dict[str, tuple[str, str]] = {
    ".claude": (ANTHROPIC, "Claude Code"),
    ".codex": (OPENAI, "Codex"),
    ".cursor": (CURSOR, "Cursor"),
    ".gemini": (GOOGLE, "Gemini CLI"),
    ".windsurf": (CODEIUM, "Windsurf"),
}

#: Markers that are only themselves at one exact path.
MARKER_PATHS: dict[str, tuple[str, str]] = {
    ".github/copilot-instructions.md": (GITHUB, "GitHub Copilot"),
}


class _Identity:
    """One assistant as it signs a commit.

    Matched on the e-mail address wherever there is a settled one, because the
    tool writes that itself, where a display name is whatever the local git
    config happened to say.
    """

    def __init__(
        self,
        *,
        provider: str,
        assistant: str,
        name: str = "",
        email: str = "",
        model_from_name: bool = False,
    ) -> None:
        self.name = re.compile(name, re.IGNORECASE) if name else None
        self.email = re.compile(email, re.IGNORECASE) if email else None
        self.provider = provider
        self.assistant = assistant
        self.model_from_name = model_from_name

    def matches(self, name: str, email: str) -> bool:
        """Report whether this identity is the one that signed."""
        # Both patterns when both are given: `@openai.com` alone is every
        # employee of the company, and "Codex" alone is a word.
        if self.name is not None and not self.name.fullmatch(name.strip()):
            return False
        return not (self.email is not None and not self.email.fullmatch(email.strip()))


#: The display name Claude Code signs with, which is "Claude" plus the model it
#: ran as -- `Claude Opus 5`, `Claude Sonnet 4.5`. Bounded in shape so that a
#: name mangled by some other tool is read as no model rather than as a model
#: nobody ever shipped.
CLAUDE_MODEL_NAME = re.compile(r"Claude(?: [A-Za-z0-9][A-Za-z0-9.\-]*){1,4}")

#: Every assistant identity this layer recognises, in no particular order --
#: a commit is tested against all of them.
COMMIT_IDENTITIES = (
    _Identity(email=r".*@anthropic\.com", provider=ANTHROPIC, assistant="Claude Code", model_from_name=True),
    _Identity(name=r"claude(?: .*)?", email=r"noreply@anthropic\.com", provider=ANTHROPIC, assistant="Claude Code"),
    _Identity(name=r"(?:openai-)?codex(?:\[bot\])?", provider=OPENAI, assistant="Codex"),
    _Identity(name=r".*codex.*", email=r".*@openai\.com", provider=OPENAI, assistant="Codex"),
    _Identity(name=r"copilot(?:\[bot\])?", provider=GITHUB, assistant="GitHub Copilot"),
    _Identity(email=r"copilot@github\.com", provider=GITHUB, assistant="GitHub Copilot"),
    _Identity(name=r"(?:google-labs-)?jules(?:\[bot\])?", provider=GOOGLE, assistant="Jules"),
    _Identity(name=r"devin(?:-ai-integration)?(?:\[bot\])?", provider="cognition", assistant="Devin"),
)


def _phrase(pattern: str, provider: str, assistant: str, said: str) -> tuple[re.Pattern[str], str, str, str]:
    return (re.compile(pattern, re.IGNORECASE), provider, assistant, said)


#: Phrases a tool appends to a commit message itself. Whole distinctive
#: sentences rather than product names, because "claude" in a commit message is
#: as likely to be someone discussing it as a tool announcing itself.
COMMIT_PHRASES = (
    _phrase(r"Generated with \[?Claude Code", ANTHROPIC, "Claude Code", "generated with Claude Code"),
    _phrase(r"Generated with \[?Codex", OPENAI, "Codex", "generated with Codex"),
)

#: A `Co-authored-by: Name <address>` trailer, which is where an assistant that
#: did not author the commit itself is usually recorded.
CO_AUTHOR_TRAILER = re.compile(r"^\s*co-authored-by:\s*(?P<name>[^<]*)<(?P<email>[^>]*)>", re.IGNORECASE | re.MULTILINE)

#: Signal kinds, strongest first. A commit identity is a record of the tool
#: having written something; a marker file is a record of it having been
#: configured. When the two name different vendors, the one that committed is
#: the one that touched the code.
SIGNAL_RANK = ("commit", "marker")


def _marker_signals(paths: list[str]) -> list[dict[str, str]]:
    """Name every configured assistant visible in a repository's path listing."""
    signals: list[dict[str, str]] = []
    seen_dirs: set[str] = set()
    for raw in paths:
        # removeprefix, not lstrip: lstrip takes a set of characters, and
        # "./" as a set eats the leading dot of every marker there is --
        # `.claude/` arrived here as `claude/` and matched nothing.
        path = str(raw).strip().removeprefix("./")
        if not path:
            continue
        lowered = path.lower()
        segments = lowered.split("/")
        marker = MARKER_PATHS.get(lowered) or MARKER_FILES.get(segments[-1])
        if marker is None and len(segments) == 1:
            marker = ROOT_MARKER_FILES.get(segments[-1])
        if marker is not None:
            signals.append(_signal("marker", marker, evidence=path))
        for segment in segments[:-1]:
            directory = MARKER_DIRS.get(segment)
            # One signal per directory, not one per file inside it: a populated
            # `.claude/` would otherwise drown every other signal in the list
            # while saying the single thing its name already said.
            if directory is not None and segment not in seen_dirs:
                seen_dirs.add(segment)
                signals.append(_signal("marker", directory, evidence=f"{segment}/"))
    return signals


def _signal(kind: str, marker: tuple[str, str], *, evidence: str, model: str = "") -> dict[str, str]:
    provider, assistant = marker
    return {"kind": kind, "provider": provider, "assistant": assistant, "model": model, "evidence": evidence}


def _identity_signal(name: str, email: str, *, where: str) -> dict[str, str] | None:
    """Return the signal one signature carries, or None if it is a person's."""
    for identity in COMMIT_IDENTITIES:
        if not identity.matches(name, email):
            continue
        model = ""
        if identity.model_from_name:
            matched = CLAUDE_MODEL_NAME.fullmatch(name.strip())
            # A bare "Claude" is the tool, not a model, and naming it as one
            # would put a model nobody ships into the stored record.
            model = matched.group(0) if matched and " " in matched.group(0) else ""
        return _signal(
            "commit",
            (identity.provider, identity.assistant),
            evidence=f"{where} {name} <{email}>".strip(),
            model=model,
        )
    return None


def _commit_signals(commits: list[dict[str, str]]) -> list[dict[str, str]]:
    """Name every assistant that signed one of the commits this clone holds."""
    signals: list[dict[str, str]] = []
    for commit in commits:
        sha = str(commit.get("sha") or "")[:12]
        label = f"{sha}:" if sha else "commit:"
        signatures = [
            (str(commit.get("authorName") or ""), str(commit.get("authorEmail") or ""), f"{label} author"),
            (str(commit.get("committerName") or ""), str(commit.get("committerEmail") or ""), f"{label} committer"),
        ]
        message = str(commit.get("message") or "")
        signatures += [
            (match.group("name").strip(), match.group("email").strip(), f"{label} co-author")
            for match in CO_AUTHOR_TRAILER.finditer(message)
        ]
        for name, email, where in signatures:
            signal = _identity_signal(name, email, where=where)
            if signal is not None:
                signals.append(signal)
        for phrase, provider, assistant, said in COMMIT_PHRASES:
            if phrase.search(message):
                # The label rather than the pattern: this string is stored and
                # read by people, and a regexp reads as a bug in the record.
                signals.append(_signal("commit", (provider, assistant), evidence=f"{label} {said}"))
    return signals


def _settled_provider(signals: list[dict[str, str]]) -> str:
    """Return the one vendor the strongest evidence names, or "" if it is split."""
    for kind in SIGNAL_RANK:
        named = sorted({signal["provider"] for signal in signals if signal["kind"] == kind and signal["provider"]})
        if len(named) == 1:
            return named[0]
        if named:
            # Two vendors at the same strength. Both were involved, and the
            # signal list says so; the single-value column cannot, so it stays
            # empty rather than picking one of them arbitrarily.
            return ""
    return ""


def _dedupe(signals: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, ...]] = set()
    unique: list[dict[str, str]] = []
    ordered = sorted(signals, key=lambda item: (item["kind"], item["provider"], item["assistant"], item["evidence"]))
    for signal in ordered:
        key = (signal["kind"], signal["provider"], signal["assistant"], signal["model"], signal["evidence"])
        if key not in seen:
            seen.add(key)
            unique.append(signal)
    return unique


def summarize(signals: list[dict[str, str]]) -> dict[str, Any]:
    """Reduce a set of signals to the verdict, the vendor and the model."""
    signals = _dedupe(signals)
    provider = _settled_provider(signals)
    models = sorted({signal["model"] for signal in signals if signal["model"] and signal["provider"] == provider})
    return {
        "schemaVersion": SCHEMA_VERSION,
        # None, not False. See the module docstring: absence of these traces is
        # not evidence that no assistant was used.
        "llmAssisted": True if signals else None,
        "provider": provider if signals else "",
        # One model or none. Two different models over a repository's history is
        # a true statement that a single column cannot hold, and picking either
        # would make the record say the other was never used.
        "model": models[0] if len(models) == 1 else "",
        "assistants": sorted({signal["assistant"] for signal in signals if signal["assistant"]}),
        "signals": signals,
    }


def detect(paths: list[str], commits: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """Report assistant involvement from a path listing and commit metadata.

    `paths` are repository-relative, as `git ls-tree` prints them. `commits`
    carry `sha`, `authorName`, `authorEmail`, `committerName`, `committerEmail`
    and `message`; an empty list is normal rather than a failure, because the
    only caller with git available is the scanner.
    """
    return summarize(_marker_signals(list(paths)) + _commit_signals(list(commits or [])))


def merge(*results: dict[str, Any] | None) -> dict[str, Any]:
    """Combine detections of the same repository made from different evidence.

    The analyzer sees the files it was budgeted to read; the scanner sees the
    whole tree and the commits. Neither is a subset of the other in practice --
    a marker file can fall outside the read budget, and a wiki-hosted tool has
    no commits at all -- so the verdict is re-derived from both sets together
    rather than taken from whichever ran last.
    """
    signals: list[dict[str, str]] = []
    for result in results:
        if isinstance(result, dict) and isinstance(result.get("signals"), list):
            signals += [signal for signal in result["signals"] if isinstance(signal, dict)]
    return summarize([_clean(signal) for signal in signals])


def _clean(signal: dict[str, Any]) -> dict[str, str]:
    """Coerce one stored or supplied signal back to the shape summarize expects."""
    return {
        "kind": str(signal.get("kind") or ""),
        "provider": str(signal.get("provider") or ""),
        "assistant": str(signal.get("assistant") or ""),
        "model": str(signal.get("model") or "")[:128],
        "evidence": str(signal.get("evidence") or "")[:256],
    }
