// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test } from "vitest";
import * as experiments from "../../public_html/views/experiments.js";

const EXPECTED_TITLE = "Feature status — Toolhub Evolved";

test("viewExperiments() renders the hybrid-feature showcase copy and title", () => {
	const actual = experiments.viewExperiments();
	assert.equal(actual.title, EXPECTED_TITLE);
	// Pin the computed feature total derived from the reduce() over every group.
	assert.ok(actual.html.includes("The 13 features below describe Toolhub Evolved's hybrid model"));
	assert.ok(actual.html.includes("live Toolhub data stays the base"));
	assert.ok(actual.html.includes("local overlays cover drafts, fallback data, and Evolved-owned data"));
	assert.ok(actual.html.includes("Current behavior"));
	assert.ok(actual.html.includes("Production need"));
	assert.ok(actual.html.includes("Toolhub sign-in"));
	assert.ok(actual.html.includes("Official Toolhub OAuth plus an Evolved server session."));
	assert.ok(actual.html.includes("Your contributions — official when possible, local when needed"));
	assert.ok(
		actual.html.includes("Official list create/edit/delete when permitted; local draft lists remain as fallback.")
	);
	assert.ok(actual.html.includes("Official annotation PUT first; rejected annotations remain local overlays."));
	assert.ok(actual.html.includes("Public popularity ranking remains hidden"));
	assert.ok(actual.html.includes("Signed-in users can thank a tool"));
	assert.ok(actual.html.includes("Approved Evolved media records render on tool pages"));
	assert.ok(!actual.html.includes('href="/search?sort=views" data-enable-evolved'));
	assert.ok(!actual.html.includes("Simulated with"));
	assert.ok(!actual.html.includes("nothing here is written to the"));
});

test("EXPERIMENTS is the three-group source array with the expected feature counts", () => {
	assert.equal(experiments.EXPERIMENTS.length, 3);
	assert.deepEqual(
		experiments.EXPERIMENTS.map((g) => g.group),
		[
			"Identity & account",
			"Your contributions — official when possible, local when needed",
			"Evolved-only signals — real Evolved data only"
		]
	);
	assert.deepEqual(
		experiments.EXPERIMENTS.map((g) => g.items.length),
		[1, 7, 5]
	);
});

test("a tryHref item without a tryLabel falls back to the 'Try it' label", () => {
	// viewExperiments() reads the module-level EXPERIMENTS directly, so exercise
	// the `it.tryLabel || "Try it"` fallback (unreachable via the real data, where
	// every linked feature supplies a label) by swapping the array contents and
	// restoring them afterwards.
	const original = experiments.EXPERIMENTS.splice(0, experiments.EXPERIMENTS.length);
	try {
		experiments.EXPERIMENTS.push({
			group: "Probe",
			items: [{ name: "Probe item", what: "w", current: "c", need: "n", tryHref: "/probe" }]
		});
		const { html } = experiments.viewExperiments();
		assert.ok(
			html.includes('<a class="exfeat__try" href="/probe">Try it <span aria-hidden="true">→</span></a>'),
			"missing tryLabel should render the 'Try it' fallback"
		);
		// And the &&-mutant guard: with a present label, that label (not "Try it") is shown.
		experiments.EXPERIMENTS[0].items[0].tryLabel = "Labelled";
		assert.ok(experiments.viewExperiments().html.includes('>Labelled <span aria-hidden="true">→</span></a>'));
	} finally {
		experiments.EXPERIMENTS.splice(0, experiments.EXPERIMENTS.length, ...original);
	}
});
