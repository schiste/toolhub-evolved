// SPDX-License-Identifier: GPL-3.0-or-later
// `eslint .` decides for itself which files exist to lint, and its flat config
// does not read .gitignore the way Prettier's CLI does. So the two file sets
// drift apart silently, and the symptom is not a failure but a slowdown: once
// enough broker worktrees had accumulated, the pre-push hook was linting ~7400
// files instead of ~100 and ran past ten minutes. These tests pin the file set
// itself rather than the wording of the ignore list.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { test } from "vitest";
import { ESLint } from "eslint";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const eslint = new ESLint({ cwd: ROOT });

test("a broker worktree's copy of the app is not linted as if it were ours", async () => {
	// Every worktree is a full checkout of this same repo at another session's
	// commit. Linting them repeats our own source dozens of times and lets an
	// error in someone else's unfinished branch fail a push it is not part of.
	const inAWorktree = path.join(ROOT, ".aethyme/worktrees/example-session/public_html/app.js");
	assert.equal(await eslint.isPathIgnored(inAWorktree), true);
});

test("our own source is still linted", async () => {
	// The guard above is one glob away from ignoring the app itself.
	assert.equal(await eslint.isPathIgnored(path.join(ROOT, "public_html/app.js")), false);
});

test("nothing git ignores is left for eslint to walk", async () => {
	// The general form: any future local tool directory that lands JS in the
	// working tree is caught here rather than by a push that mysteriously hangs.
	// A clean checkout has no such files, so this asserts nothing there.
	const ignoredFiles = execFileSync(
		"git",
		[
			"ls-files",
			"--others",
			"--ignored",
			"--exclude-standard",
			"-z",
			"*.js",
			"*.mjs",
			"*.cjs",
			// Installed packages are ignored by eslint's own defaults and there are
			// hundreds of thousands of them; listing them would dwarf the answer.
			// Both spellings are needed: pathspec wildcards match slashes, so the
			// leading `**/` requires a directory above it and therefore never
			// matched the root-level node_modules/ that holds every one of them.
			":!:**/node_modules/**",
			":!:node_modules/**"
		],
		{ cwd: ROOT, encoding: "utf8", maxBuffer: 64 * 1024 * 1024 }
	)
		.split("\0")
		.filter(Boolean);

	const linted = [];
	for (const file of ignoredFiles) {
		if (linted.length >= 5) break;
		if (!(await eslint.isPathIgnored(path.join(ROOT, file)))) linted.push(file);
	}
	assert.deepEqual(linted, [], `git ignores these but eslint would lint them: ${linted.join(", ")}`);
});
