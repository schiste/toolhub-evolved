#!/usr/bin/env node
// SPDX-License-Identifier: GPL-3.0-or-later
// Performance budget for production user-route JS payload (raw ES modules served
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

const LIMIT = 620_000; // bytes; current app is ~613 KB after eager health summaries and render-refresh coordination.
const EXCLUDED_ROUTE_DOCS = new Set(["public_html/views/_fixtures.js", "public_html/views/styleguide.js"]);

// :(glob) magic so ** matches the top-level entry point too (see tools/checks.mjs).
const files = execFileSync("git", ["ls-files", ":(glob)public_html/**/*.js"], { encoding: "utf8" })
	.split("\n")
	.filter((file) => file && !EXCLUDED_ROUTE_DOCS.has(file));
const total = files.reduce((sum, file) => sum + readFileSync(file).length, 0);
const kb = (n) => `${Math.round(n / 1000)} KB`;

if (total > LIMIT) {
	console.error(`js-budget: app JS is ${kb(total)} across ${files.length} modules — over the ${kb(LIMIT)} budget`);
	process.exit(1);
}
console.log(`js-budget: app JS is ${kb(total)} across ${files.length} modules — within the ${kb(LIMIT)} budget`);
