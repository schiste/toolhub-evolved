#!/usr/bin/env bash
# Aethyme SessionStart hook: load AGENTS.md / CLAUDE.md content into
# `additionalContext` so headless Claude Code sessions (e.g. evaluation
# runs launched via `claude --dangerously-skip-permissions`) discover the
# in-repo agent instructions even when the harness skips the standard
# CWD-CLAUDE.md auto-load.
#
# This script is deployed by `aethyme enhance deploy --repo <path>` and
# wired into the project's .claude/settings.local.json under
# hooks.SessionStart.
#
# Output protocol: the script must emit a single JSON object on stdout
# of the shape
#   {"hookSpecificOutput": {"hookEventName": "SessionStart",
#                            "additionalContext": "<text>"}}
# Empty stdout (or non-zero exit) = no context injected.

set -uo pipefail

cwd="${CLAUDE_PROJECT_DIR:-${PWD}}"

# Resolve the installed router once, for both telemetry and the JSON envelope.
# Empty means "no router" — telemetry is skipped and the envelope cannot be
# emitted. Repository deployment never embeds a source-checkout path.
if command -v aethyme >/dev/null 2>&1; then
    aethyme_bin="aethyme"
else
    aethyme_bin=""
fi

agents="$cwd/AGENTS.md"
claude_md="$cwd/CLAUDE.md"

context=""

if [[ -f "$agents" ]]; then
    context="$(cat -- "$agents")"
fi

# Append CLAUDE.md only if it exists AND differs from AGENTS.md
# (typical setup deploys both with identical content).
if [[ -f "$claude_md" ]]; then
    if [[ -z "$context" ]] || ! diff -q "$agents" "$claude_md" >/dev/null 2>&1; then
        if [[ -n "$context" ]]; then
            context+=$'\n\n---\n\n'
        fi
        context+="$(cat -- "$claude_md")"
    fi
fi

if [[ -z "$context" ]]; then
    exit 0
fi

# Best-effort telemetry via the native router. The native command also ledgers
# its own arg-parse failures, so this fire-and-forget call does not fail
# invisibly.
if [[ -n "$aethyme_bin" ]] && [[ -d "$cwd" ]]; then
    "$aethyme_bin" repo record-wrapper-invocation \
        "$cwd" \
        --wrapper aethyme-sessionstart-hook \
        --detail source=claude-hook \
        >/dev/null 2>&1 || true
fi

# Emit the JSON envelope via the native router (python-retirement Phase
# 6, 2026-08-01; previously a bare `python3` heredoc calling json.dumps
# — the last Python invocation on the product path). Output is
# byte-identical to the heredoc's. Context goes over a pipe, not argv,
# so a large AGENTS.md cannot blow the argument-list limit.
if [[ -z "$aethyme_bin" ]]; then
    # No router reachable: emit nothing rather than an unescaped
    # envelope. Empty stdout = no context injected, per the protocol.
    exit 0
fi
printf '%s' "$context" | "$aethyme_bin" repo hook-envelope
