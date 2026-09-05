// SPDX-License-Identifier: GPL-3.0-or-later
//
// The data-layer page answers one question -- who filled this catalog in -- and
// the honest answer depends on two properties of the payload holding: the
// per-bucket counts have to add up to the filled count (otherwise the stacked
// bar shows a share of nothing), and a value a language model offered but did
// not win must never be drawn as filled. Both are asserted from rendered
// output, because that is where a reader would be misled.
import assert from "node:assert/strict";
import { beforeEach, test, vi } from "vitest";

const h = vi.hoisted(() => ({ backendGetJson: vi.fn() }));
vi.mock("../../public_html/lib/core/api.js", async (importOriginal) => ({
	...(await importOriginal()),
	backendGetJson: h.backendGetJson
}));

import { dataLayerHTML, viewDataLayer } from "../../public_html/views/data-layer.js";

const buckets = ["human", "toolinfo", "code", "convention", "ai"];
/** @param {Partial<Record<string, number>>} counts */
const byBucket = (counts) => Object.fromEntries(buckets.map((b) => [b, counts[b] ?? 0]));

/** @param {string} field @param {object} spec */
const fieldDoc = (field, { kind = "scalar", filled, missing, percent, primary, shadowed = {} }) => ({
	field,
	kind,
	filled,
	missing,
	percent,
	primary: byBucket(primary),
	contributing: byBucket(primary),
	shadowed: byBucket(shadowed),
	unmapped: {}
});

const payload = {
	generatedAt: "2026-08-31T09:00:00Z",
	tools: 100,
	pendingTools: 7,
	fieldCount: 3,
	scalarFields: ["title", "description"],
	listFields: ["keywords"],
	buckets,
	sourcesByBucket: {
		human: ["curation", "gadget"],
		toolinfo: ["canonical", "crawler"],
		code: ["repository_analysis"],
		convention: ["wiki_talk_page"],
		ai: ["llm_inference"]
	},
	sourceConfidence: { canonical: 95, curation: 100, llm_inference: 60, repository_analysis: 75 },
	overall: {
		slots: 300,
		filled: 210,
		missing: 90,
		percent: 70,
		primary: byBucket({ human: 40, toolinfo: 120, code: 30, ai: 20 })
	},
	fields: [
		fieldDoc("description", {
			filled: 60,
			missing: 40,
			percent: 60,
			primary: { toolinfo: 40, ai: 20 },
			shadowed: { ai: 12 }
		}),
		fieldDoc("title", { filled: 100, missing: 0, percent: 100, primary: { human: 20, toolinfo: 80 } }),
		fieldDoc("keywords", { kind: "list", filled: 50, missing: 50, percent: 50, primary: { human: 20, code: 30 } })
	]
};

beforeEach(() => {
	document.body.innerHTML = "";
	h.backendGetJson.mockReset();
	window.history.replaceState({}, "", "/data-layer");
});

test("the report names every source category and the tools it could not count", () => {
	document.body.innerHTML = dataLayerHTML(payload);
	const text = document.body.textContent;
	for (const label of ["Human", "Toolinfo", "Code analysis", "AI generated"]) {
		assert.match(text, new RegExp(label));
	}
	// The denominator is stated, not implied: a reader who sees 70% is told how
	// many tools that is over, and how many were left out for having no
	// projection yet.
	assert.match(text, /70/);
	assert.match(text, /Tools counted/);
	assert.match(text, /100/);
	assert.match(text, /Not yet projected/);
	assert.match(text, /7/);
});

test("each field's segments span exactly its filled share, leaving the rest unfilled", () => {
	document.body.innerHTML = dataLayerHTML(payload);
	const rows = document.querySelectorAll(".data-layer-table tbody tr");
	assert.equal(rows.length, 3);
	for (const row of rows) {
		const shares = [...row.querySelectorAll(".data-layer-bar__seg")].map((seg) =>
			Number(seg.style.getPropertyValue("--share"))
		);
		const total = shares.reduce((sum, share) => sum + share, 0);
		assert.ok(Math.abs(total - 100) < 0.01, `segments sum to ${total}, not 100`);
	}
});

test("fields are ordered most complete first, whatever order the payload arrives in", () => {
	document.body.innerHTML = dataLayerHTML(payload);
	const names = [...document.querySelectorAll(".data-layer-field")].map((el) => el.textContent.trim());
	assert.deepEqual(names, ["Title", "Description", "Keywords"]);
});

test("an AI value a stronger source overrode never reaches the bar or the filled count", () => {
	document.body.innerHTML = dataLayerHTML(payload);
	const description = [...document.querySelectorAll(".data-layer-table tbody tr")].find((row) =>
		row.textContent.includes("description")
	);
	// 12 tools had an inferred description that lost. The payload still reports
	// them, and the page must ignore them completely: they are not part of the
	// field's 60 filled, and the AI segment stays at the 20 it actually won.
	const ai = description.querySelector(".data-layer-bar__seg--ai");
	assert.equal(Number(ai.style.getPropertyValue("--share")), 20);
	assert.match(description.textContent, /60/);
	assert.equal(description.querySelectorAll(".data-layer-shadow").length, 0);
});

test("a list field is marked as one, so a partial list is not read as a single missing value", () => {
	document.body.innerHTML = dataLayerHTML(payload);
	const keywords = [...document.querySelectorAll(".data-layer-table tbody tr")].find((row) =>
		row.textContent.includes("keywords")
	);
	assert.equal(keywords.querySelector(".data-layer-tag").textContent.trim(), "list");
});

test("the route settles into the report and stays retryable when the snapshot fails", async () => {
	h.backendGetJson.mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce(payload);
	const view = viewDataLayer();
	assert.deepEqual(view.styles, ["/styles/data-layer.css"]);
	document.body.innerHTML = view.html;
	view.mount();
	await vi.waitFor(() => assert.match(document.body.textContent, /temporarily unavailable/));
	document.querySelector("[data-data-layer-retry]").click();
	await vi.waitFor(() => assert.match(document.body.textContent, /Filling by field/));
	assert.deepEqual(h.backendGetJson.mock.calls[0], ["/v1/coverage/"]);
	assert.equal(document.querySelector("[data-data-layer-root]").hasAttribute("aria-busy"), false);
});
