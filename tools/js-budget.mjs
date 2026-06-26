#!/usr/bin/env node
// SPDX-License-Identifier: GPL-3.0-or-later
// Performance budget for the total app JS payload (raw ES modules served
// directly — there is no bundler, so bytes on disk ≈ bytes over the wire).
//
// This is a FIXED, generous ceiling — deliberately NOT a self-baselined ratchet
// like the module-budgets contracts that were removed. It sits at roughly 2× the
// current footprint, so it never creeps upward on its own and only trips on gross
// bloat (a dependency vendored in, a generated blob committed, AI-spawned module
// sprawl). If the app legitimately outgrows it, raise LIMIT in one obvious place,
// with justification — an explicit decision, not a silent baseline.
import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";

const LIMIT = 550_000; // bytes (~2× the ~271 KB current payload)

// :(glob) magic so ** matches the top-level entry point too (see tools/checks.mjs).
const files = execFileSync("git", ["ls-files", ":(glob)public_html/**/*.js"], { encoding: "utf8" })
	.split("\n")
	.filter(Boolean);
const total = files.reduce((sum, file) => sum + readFileSync(file).length, 0);
const kb = (n) => `${Math.round(n / 1000)} KB`;

if (total > LIMIT) {
	console.error(`js-budget: app JS is ${kb(total)} across ${files.length} modules — over the ${kb(LIMIT)} budget`);
	process.exit(1);
}
console.log(`js-budget: app JS is ${kb(total)} across ${files.length} modules — within the ${kb(LIMIT)} budget`);
