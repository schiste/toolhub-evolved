// SPDX-License-Identifier: GPL-3.0-or-later
// Cards ship without the score popover's breakdown, so it has to arrive after
// the route renders — and land in the panel without redrawing the page.
import assert from "node:assert/strict";
import { beforeEach, test, vi } from "vitest";

const h = vi.hoisted(() => ({ attachEvolvedSummaries: vi.fn() }));
vi.mock("../../public_html/lib/core/signals.js", async (orig) => {
	const actual = await orig();
	return { ...actual, attachEvolvedSummaries: h.attachEvolvedSummaries };
});

const { hydrateHealthPopovers } = await import("../../public_html/lib/molecules/health-popover-lazy.js");
const { healthScoreChip } = await import("../../public_html/lib/molecules/tool-health-summary.js");

const CARD_SUMMARY = { health: { score: 71, grade: "good" } };
const FULL_SUMMARY = {
	health: {
		score: 71,
		grade: "good",
		calculation: { includedDimensionCount: 1, dimensionCount: 1, includedWeight: 1 },
		dimensions: [
			{ key: "maintainer-status", label: "Maintainer status", score: 100, weight: 1, includedInScore: true }
		]
	}
};

/** @param {any} summary */
function renderCard(summary) {
	document.body.innerHTML = `<article data-tool="ada-tool">${healthScoreChip(summary, { compact: true })}</article>`;
}

beforeEach(() => {
	h.attachEvolvedSummaries.mockReset();
	document.body.innerHTML = "";
});

test("a card summary renders a pending panel rather than claiming there are no dimensions", () => {
	renderCard(CARD_SUMMARY);
	const panel = document.querySelector("[data-health-panel]");

	assert.ok(panel, "no panel rendered");
	assert.equal(panel.getAttribute("data-health-panel"), "pending");
	// The score is already known, so the chip itself must not wait.
	assert.match(document.body.innerHTML, /71/);
	assert.doesNotMatch(panel.textContent, /No local dimensions are available yet/);
});

test("hydration fills the panel in place and asks for the full view once", async () => {
	renderCard(CARD_SUMMARY);
	h.attachEvolvedSummaries.mockImplementation(async (carriers) => {
		for (const carrier of carriers) carrier.evolvedSummary = FULL_SUMMARY;
		return carriers;
	});

	const filled = await hydrateHealthPopovers();

	assert.equal(filled, 1);
	assert.equal(h.attachEvolvedSummaries.mock.calls.length, 1, "expected a single batched request");
	const [carriers, opts] = h.attachEvolvedSummaries.mock.calls[0];
	assert.deepEqual(
		carriers.map((c) => c.name),
		["ada-tool"]
	);
	assert.equal(opts.view, "full");
	// Patched in place: still one card, now carrying the breakdown.
	assert.equal(document.querySelectorAll("article[data-tool]").length, 1);
	assert.equal(document.querySelector('[data-health-panel="pending"]'), null);
	assert.match(document.body.textContent, /Maintainer status/);
});

test("a summary that never arrives stays pending so a later pass can retry", async () => {
	renderCard(CARD_SUMMARY);
	h.attachEvolvedSummaries.mockImplementation(async (carriers) => carriers);

	const filled = await hydrateHealthPopovers();

	assert.equal(filled, 0);
	assert.ok(document.querySelector('[data-health-panel="pending"]'), "pending marker was cleared with no data");
});

test("a card that already has the breakdown is not re-requested", async () => {
	renderCard(FULL_SUMMARY);
	assert.equal(document.querySelector('[data-health-panel="pending"]'), null, "full summary should render ready");

	const filled = await hydrateHealthPopovers();

	assert.equal(filled, 0);
	assert.deepEqual(h.attachEvolvedSummaries.mock.calls, [], "requested a breakdown it already had");
});
