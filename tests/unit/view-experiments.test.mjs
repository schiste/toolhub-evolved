// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test } from "vitest";
import * as experiments from "../../public_html/views/experiments.js";

const EXPECTED_TITLE = "Experimental features — Toolhub";

test("viewExperiments() renders the hybrid-feature showcase copy and title", () => {
	const actual = experiments.viewExperiments();
	assert.equal(actual.title, EXPECTED_TITLE);
	// Pin the computed feature total derived from the reduce() over every group.
	assert.ok(actual.html.includes("The 14 prospective features below appear only when"));
	assert.ok(actual.html.includes("adds an Evolved-specific layer"));
	assert.ok(actual.html.includes("Toolhub sign-in"));
	assert.ok(actual.html.includes("Official Toolhub OAuth plus an Evolved server session."));
	assert.ok(actual.html.includes("Your contributions — official when possible, local when needed"));
	assert.ok(
		actual.html.includes("Official list create/edit/delete when permitted; local draft lists remain as fallback.")
	);
	assert.ok(actual.html.includes("Official annotation PUT first; rejected annotations remain local overlays."));
	assert.ok(!actual.html.includes("nothing here is written to the"));
});

test("EXPERIMENTS is the three-group source array with the expected feature counts", () => {
	assert.equal(experiments.EXPERIMENTS.length, 3);
	assert.deepEqual(
		experiments.EXPERIMENTS.map((g) => g.group),
		[
			"Identity & account",
			"Your contributions — official when possible, local when needed",
			"Synthetic signals — computed deterministically per tool"
		]
	);
	assert.deepEqual(
		experiments.EXPERIMENTS.map((g) => g.items.length),
		[2, 7, 5]
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
			items: [{ name: "Probe item", what: "w", sim: "s", needs: "n", tryHref: "/probe" }]
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
