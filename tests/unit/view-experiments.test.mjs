// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test } from "vitest";
import * as experiments from "../../public_html/views/experiments.js";

const EXPECTED_TITLE = "Feature status — Toolhub Evolved";

test("viewExperiments() renders the hybrid-feature showcase copy and title", () => {
	const actual = experiments.viewExperiments();
	assert.equal(actual.title, EXPECTED_TITLE);
	// Pin the computed feature total derived from the reduce() over every group.
	assert.ok(actual.html.includes("The 43 features below describe Toolhub Evolved's hybrid model"));
	assert.ok(actual.html.includes("the local Toolhub replica serves public reads"));
	assert.ok(actual.html.includes("local overlays cover drafts, fallback data, and Evolved-owned data"));
	assert.ok(actual.html.includes("Current behavior"));
	assert.ok(actual.html.includes("Production need"));
	assert.ok(actual.html.includes("Local catalog read surfaces"));
	assert.ok(actual.html.includes("Search and browse"));
	assert.ok(actual.html.includes("Tool detail and history"));
	assert.ok(actual.html.includes("Recent changes table"));
	assert.ok(actual.html.includes("Toolhub sign-in"));
	assert.ok(actual.html.includes("Official Toolhub OAuth plus an Evolved server session."));
	assert.ok(actual.html.includes("Evolved roles and permissions"));
	assert.ok(actual.html.includes("Developer settings"));
	assert.ok(actual.html.includes("My tools workspace"));
	assert.ok(actual.html.includes("Maintainer summary and activity"));
	assert.ok(actual.html.includes("Preferences"));
	assert.ok(actual.html.includes("Your contributions — official when possible, local when needed"));
	assert.ok(
		actual.html.includes("Official list create/edit/delete when permitted; local draft lists remain as fallback.")
	);
	assert.ok(actual.html.includes("Official annotation PUT first; rejected annotations remain local overlays."));
	assert.ok(actual.html.includes("Forms show diffs before official-first writes"));
	assert.ok(actual.html.includes("Provenance and sync controls"));
	assert.ok(actual.html.includes("Create-time toolinfo enrichment"));
	assert.ok(actual.html.includes("Toolinfo registration"));
	assert.ok(actual.html.includes("Public popularity ranking remains hidden"));
	assert.ok(actual.html.includes("Signed-in users can thank a tool"));
	assert.ok(actual.html.includes("approved Evolved media renders on tool pages"));
	assert.ok(actual.html.includes("Public local tools and toolinfo feed"));
	assert.ok(actual.html.includes("Moderation and review queue"));
	assert.ok(actual.html.includes("Performance, resilience, and platform"));
	assert.ok(actual.html.includes("Shared Toolhub API cache"));
	assert.ok(actual.html.includes("Cache invalidation and prewarming"));
	assert.ok(actual.html.includes("Language, theme, and accessibility"));
	assert.ok(!actual.html.includes('href="/search?sort=views" data-enable-evolved'));
	assert.ok(!actual.html.includes("Simulated with"));
	assert.ok(!actual.html.includes("nothing here is written to the"));
});

test("EXPERIMENTS is the source array with the expected feature counts", () => {
	assert.equal(experiments.EXPERIMENTS.length, 5);
	assert.deepEqual(
		experiments.EXPERIMENTS.map((g) => g.group),
		[
			"Local catalog read surfaces",
			"Identity & account",
			"Your contributions — official when possible, local when needed",
			"Evolved-only signals — real Evolved data only",
			"Performance, resilience, and platform"
		]
	);
	assert.deepEqual(
		experiments.EXPERIMENTS.map((g) => g.items.length),
		[10, 10, 10, 7, 6]
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
