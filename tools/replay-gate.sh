#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Replay the static quality gates on EVERY commit in the push range
# (origin/main..HEAD), so each pushed commit independently passes. Runs in a
# throwaway detached worktree via `git rebase --exec`; the user's branch and
# working tree are never touched.
set -eu

# Recursion guard: the rebase below re-invokes quality.mjs, which must not
# re-trigger this script. (git rebase does not fire pre-push, so this is
# belt-and-braces.)
if [ "${TOOLHUB_GATE_REPLAY:-}" = "1" ]; then
	exit 0
fi

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

base="$(git merge-base origin/main HEAD 2>/dev/null || true)"
if [ -z "$base" ]; then
	echo "replay-gate: no origin/main to diff against; skipping per-commit replay"
	exit 0
fi
if [ "$base" = "$(git rev-parse HEAD)" ]; then
	echo "replay-gate: nothing ahead of origin/main"
	exit 0
fi

wt="$(mktemp -d "${TMPDIR:-/tmp}/toolhub-replay.XXXXXX")"
cleanup() {
	git -C "$wt" rebase --abort >/dev/null 2>&1 || true
	git worktree remove --force "$wt" >/dev/null 2>&1 || true
	rm -rf "$wt"
}
trap cleanup EXIT INT TERM

git worktree add --detach "$wt" HEAD >/dev/null
# Share the heavy, commit-invariant dependencies rather than reinstalling.
ln -s "$repo_root/node_modules" "$wt/node_modules"
mkdir -p "$wt/.quality"
if [ -d "$repo_root/.quality/python" ]; then
	ln -s "$repo_root/.quality/python" "$wt/.quality/python"
fi

echo "replay-gate: replaying static gates over ${base}..HEAD"
(
	cd "$wt"
	TOOLHUB_GATE_REPLAY=1 git rebase --exec 'node tools/quality.mjs --pre-push --replay' "$base"
)
echo "replay-gate: every commit in the push range passes the static gates"
