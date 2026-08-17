#!/usr/bin/env node
// SPDX-License-Identifier: GPL-3.0-or-later
// Performance budget for the app's total JS source, measured on disk under
// public_html/.
//
// This used to say "bytes on disk ≈ bytes over the wire", which was true while
// the modules were served raw. tools/build_dist.py now concatenates them into
// bundles, so what a visitor downloads is a subset of this — the entry bundle
// plus whichever routes they visit — and gzipped at that. Source bytes remain
// the right thing to bound here: they are what actually grows when a dependency
// is vendored in or a generated blob is committed, and they cap what any bundle
// could ever contain. The wire-side number the bundling exists to protect is the
// landing payload, which is asserted in tests/proxy/test_build_dist.py.
//
// This is a FIXED, generous ceiling — deliberately NOT a self-baselined ratchet
// like the module-budgets contracts that were removed. It sits at roughly 2× the
// current footprint, so it never creeps upward on its own and only trips on gross
// bloat (a dependency vendored in, a generated blob committed, AI-spawned module
// sprawl). If the app legitimately outgrows it, raise LIMIT in one obvious place,
// with justification — an explicit decision, not a silent baseline.
import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";

// Raised 2026-08-07 from 620_000, which had been failing.
//
// The ceiling above is described as "roughly 2x the current footprint", but
// 620_000 was set against an app of ~613 KB — about 1.01x, so it had no headroom
// at all and tripped on the next ordinary feature rather than on gross bloat.
// The app measured 868 KB at the time of this change, spread broadly (largest
// module ~68 KB, no vendored dependency and no generated blob), so this is the
// mis-set-ceiling case rather than the case the gate exists to catch.
//
// 1_750_000 restores the ~2x intent against that 868 KB. It is a policy
// judgement, not a derived value: if the app genuinely should be smaller, the
// answer is to trim modules and lower this again, not to let it drift upward.
const LIMIT = 1_750_000; // bytes; ~2x the 868 KB measured on 2026-08-07.
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
