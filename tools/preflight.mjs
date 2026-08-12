#!/usr/bin/env node
// SPDX-License-Identifier: GPL-3.0-or-later
/** Run independent, deterministic quality gates concurrently before full suites. */
import { spawn } from "node:child_process";
import { access } from "node:fs/promises";
import { constants } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const npm = process.platform === "win32" ? "npm.cmd" : "npm";

const checks = [
	["Prettier", npm, ["run", "format:check"]],
	["ESLint", npm, ["run", "lint"]],
	["Stylelint", npm, ["run", "lint:css"]],
	["Spelling", npm, ["run", "spell"]],
	["Types", npm, ["run", "types"]],
	["Dead code", npm, ["run", "dead:check"]],
	["Duplication", npm, ["run", "dup:check"]],
	["Repository invariants", npm, ["run", "checks"]],
	["Production cleanliness", npm, ["run", "clean:prod"]],
	["JavaScript budget", npm, ["run", "budget"]],
	["Translations", npm, ["run", "i18n:check"]],
	["Feature docs", npm, ["run", "features:docs:check"]],
	["Secrets", npm, ["run", "secrets"]],
	["Whitespace", "git", ["diff", "--check"]]
];

async function executable(path) {
	try {
		await access(resolve(root, path), constants.X_OK);
		return true;
	} catch {
		return false;
	}
}

if (await executable("node_modules/.bin/banana-checker")) {
	checks.push(["Banana messages", npm, ["run", "lint:banana"]]);
} else {
	console.log("SKIP Banana messages — run npm ci to install the declared checker");
}
if (await executable(".venv/bin/ruff")) {
	checks.push(["Ruff lint", ".venv/bin/ruff", ["check", "proxy"]]);
	checks.push(["Ruff format", ".venv/bin/ruff", ["format", "--check", "proxy"]]);
} else {
	console.log("SKIP Ruff — create the project .venv to enable Python preflight checks");
}

function run([label, command, args]) {
	return new Promise((done) => {
		const child = spawn(command, args, { cwd: root, env: process.env });
		let output = "";
		child.stdout.on("data", (chunk) => (output += chunk));
		child.stderr.on("data", (chunk) => (output += chunk));
		child.on("error", (error) => done({ label, code: 1, output: error.message }));
		child.on("close", (code) => done({ label, code: code ?? 1, output: output.trim() }));
	});
}

const started = performance.now();
const results = await Promise.all(checks.map((check) => run(check)));
for (const result of results) {
	const state = result.code === 0 ? "PASS" : "FAIL";
	console.log(`${state} ${result.label}`);
	if (result.code !== 0 && result.output) console.log(result.output);
}
const failed = results.filter((result) => result.code !== 0);
console.log(
	`Preflight: ${results.length - failed.length}/${results.length} passed in ${Math.ceil(performance.now() - started)}ms`
);
if (failed.length > 0) process.exitCode = 1;
