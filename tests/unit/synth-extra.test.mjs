// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test } from "vitest";
import * as synth from "../../public_html/lib/core/synth.js";

// Exact values computed from the deterministic hash; assert each branch so the
// boundary conditionals and arithmetic operators cannot be mutated unnoticed.
test("synthViews picks the exact tier for low/mid/high bands", () => {
	// tool-0 -> b=17 (<70) -> 20 + (h % 230)
	assert.equal(synth.synthViews("tool-0"), 157);
	// tool-10 -> b=72 (70..91) -> 250 + (h % 750)
	assert.equal(synth.synthViews("tool-10"), 572);
	// tool-140 -> b=92 (>=92) -> 1000 + (h % 1500)
	assert.equal(synth.synthViews("tool-140"), 2192);
});

test("synthHealth returns exact bands green/yellow/red", () => {
	assert.deepEqual(synth.synthHealth("tool-0"), { level: "green", label: "Healthy" });
	assert.deepEqual(synth.synthHealth("tool-7"), { level: "yellow", label: "Degraded" });
	assert.deepEqual(synth.synthHealth("tool-16"), { level: "red", label: "Down" });
});

test("synthThanks and synthUsage use exact offsets and salts", () => {
	assert.equal(synth.synthThanks("tool-0"), 140);
	assert.equal(synth.synthUsage("tool-0"), 7781);
	// salt matters: empty salt would give different numbers.
	assert.notEqual(synth.synthThanks("tool-0"), synth.synthUsage("tool-0"));
});

test("synthSeed is salt-sensitive and deterministic", () => {
	assert.equal(synth.synthSeed("a", "health"), synth.synthSeed("a", "health"));
	assert.notEqual(synth.synthSeed("a", "health"), synth.synthSeed("a", "usage"));
});
