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

test("new catalog fields keep readable labels and their canonical field names", () => {
	const extendedPayload = {
		...payload,
		fieldCount: 6,
		fields: [
			...payload.fields,
			fieldDoc("content_types", {
				kind: "list",
				filled: 40,
				missing: 60,
				percent: 40,
				primary: { toolinfo: 40 }
			}),
			fieldDoc("subject_domains", {
				kind: "list",
				filled: 30,
				missing: 70,
				percent: 30,
				primary: { human: 30 }
			}),
			fieldDoc("url_alternates", {
				kind: "list",
				filled: 20,
				missing: 80,
				percent: 20,
				primary: { toolinfo: 20 }
			})
		]
	};
	document.body.innerHTML = dataLayerHTML(extendedPayload);
	const rows = [...document.querySelectorAll(".data-layer-table tbody tr")];
	for (const [label, field] of [
		["Content types", "content_types"],
		["Subject domains", "subject_domains"],
		["Alternate URLs", "url_alternates"]
	]) {
		const row = rows.find(
			(candidate) => candidate.querySelector(".data-layer-field")?.textContent.trim() === label
		);
		assert.ok(row, `missing data-layer row: ${label}`);
		assert.equal(row.querySelector("code").textContent, field);
	}
});

test("every projected field gets a readable label, including future fields", () => {
	const expectedLabels = {
		api_url: "API URL",
		available_ui_languages: "Interface languages",
		bot_username: "Bot username",
		bugtracker_url: "Bug tracker URL",
		content_types: "Content types",
		developer_docs_url: "Developer documentation",
		description: "Description",
		feedback_url: "Feedback URL",
		for_wikis: "Wikimedia projects",
		icon: "Icon",
		keywords: "Keywords",
		license: "License",
		openhub_id: "OpenHub ID",
		privacy_policy_url: "Privacy policy URL",
		replaced_by: "Replaced by",
		repository: "Repository",
		sponsor: "Sponsor",
		subject_domains: "Subject domains",
		subtitle: "Subtitle",
		tasks: "Tasks",
		technology_used: "Technology",
		title: "Title",
		tool: "Tool",
		tool_type: "Tool type",
		toolinfo_url: "Toolinfo URL",
		translate_url: "Translate URL",
		url: "Tool URL",
		url_alternates: "Alternate URLs",
		user_docs_url: "User documentation",
		wikidata_qid: "Wikidata ID",
		custom_field: "Custom field"
	};
	const fields = Object.keys(expectedLabels).map((field) =>
		fieldDoc(field, {
			kind: [
				"available_ui_languages",
				"content_types",
				"for_wikis",
				"keywords",
				"sponsor",
				"subject_domains",
				"tasks",
				"technology_used",
				"url_alternates"
			].includes(field)
				? "list"
				: "scalar",
			filled: 1,
			missing: 0,
			percent: 100,
			primary: { toolinfo: 1 }
		})
	);
	document.body.innerHTML = dataLayerHTML({ ...payload, tools: 1, fields, fieldCount: fields.length });
	const actual = Object.fromEntries(
		[...document.querySelectorAll(".data-layer-table tbody tr")].map((row) => [
			row.querySelector("code").textContent,
			row.querySelector(".data-layer-field").textContent.trim()
		])
	);
	assert.deepEqual(actual, expectedLabels);
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
