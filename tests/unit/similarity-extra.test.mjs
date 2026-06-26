// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "vitest";
import { installStorage } from "./_storage-setup.mjs";
import * as similarity from "../../public_html/lib/core/similarity.js";

const TOOLS = {
	next: null,
	results: [
		{
			name: "t1",
			tasks: ["editing"],
			keywords: ["cite"],
			for_wikis: ["en.wikipedia.org"],
			audiences: ["editor"],
			tool_type: "web app"
		},
		{ name: "t2", tasks: ["editing"], keywords: ["images"], tool_type: "bot" },
		{ name: "t3", tasks: ["editing", "editing"] } // duplicate term => deduped by termsOf
	]
};

let originalFetch;
beforeEach(() => {
	installStorage();
	originalFetch = globalThis.fetch;
	globalThis.fetch = async (url) => ({
		ok: true,
		json: async () => (String(url).includes("/search/tools/") ? TOOLS : { results: [], next: null })
	});
});
afterEach(() => {
	globalThis.fetch = originalFetch;
});

test("FACET_WEIGHTS holds the exact tuning weights", () => {
	assert.deepEqual(similarity.FACET_WEIGHTS, { task: 1.4, keyword: 1.0, wiki: 0.8, audience: 0.6, type: 0.5 });
});

test("loadAllTools normalizes every page item once", async () => {
	const tools = await similarity.loadAllTools();
	assert.equal(tools.length, 3);
	// normalizeTool attaches status/weeklyViews; raw items would not have them.
	assert.equal(tools[0].name, "t1");
	assert.equal(tools[0].status.level, "green");
	assert.equal(typeof tools[0].weeklyViews, "number");
});

test("getSimilarityIndex builds byName, vectors, deduped df, and N", async () => {
	const index = await similarity.getSimilarityIndex();
	assert.equal(index.N, 3);
	assert.equal(index.byName.get("t1").name, "t1");
	assert.ok(index.vectors.get("t1") instanceof Map);
	assert.ok(index.vectors.get("t1").size > 0);
	// editing appears in t1, t2, t3 — t3's duplicate must be deduped => df 3 (not 4).
	assert.equal(index.df.get("task:editing"), 3);
	assert.equal(index.df.get("kw:cite"), 1);
	assert.equal(index.df.get("type:web app"), 1);
});

// ---- helpers for hand-built indexes (mirrors core.test.mjs approach) --------
function termsOf(tool) {
	const out = [];
	const seen = new Set();
	const push = (prefix, values, skipAll) => {
		for (const raw of values || []) {
			const v = String(raw).trim().toLowerCase();
			if (!v || (skipAll && v === "*")) continue;
			const term = `${prefix}:${v}`;
			if (!seen.has(term)) {
				seen.add(term);
				out.push(term);
			}
		}
	};
	push("task", tool.tasks);
	push("kw", tool.keywords);
	push("wiki", tool.forWikis, true);
	push("aud", tool.audiences);
	const type = String(tool.toolType || "")
		.trim()
		.toLowerCase();
	if (type) push("type", [type]);
	return out;
}
function buildIndex(tools) {
	const df = new Map();
	for (const t of tools) for (const term of termsOf(t)) df.set(term, (df.get(term) || 0) + 1);
	const index = { tools, byName: new Map(), vectors: new Map(), df, N: tools.length };
	for (const t of tools) {
		index.byName.set(t.name, t);
		index.vectors.set(t.name, similarity.vectorFor(t, index));
	}
	return index;
}

test("vectorFor weights facets in the expected strict order and is unit-normalized", () => {
	// Single tool, all terms unique => every df = 1, N = 1 => idf identical across
	// terms, so the only differentiator is the per-facet weight.
	const tool = {
		name: "one",
		tasks: ["a"],
		keywords: ["b"],
		forWikis: ["c.example"],
		audiences: ["d"],
		toolType: "e"
	};
	const index = buildIndex([tool]);
	const v = index.vectors.get("one");
	const task = v.get("task:a");
	const kw = v.get("kw:b");
	const wiki = v.get("wiki:c.example");
	const aud = v.get("aud:d");
	const type = v.get("type:e");
	assert.ok(task > kw && kw > wiki && wiki > aud && aud > type, `order ${task} ${kw} ${wiki} ${aud} ${type}`);
	const mag = Math.sqrt([...v.values()].reduce((s, x) => s + x * x, 0));
	assert.ok(Math.abs(mag - 1) < 1e-9);
});

test("vectorFor uses the real idf formula (N and 1+df matter)", () => {
	// df("task:x") = 2, df("kw:y") = 1, N = 2.
	const tools = [
		{ name: "p", tasks: ["x"], keywords: ["y"] },
		{ name: "q", tasks: ["x"] }
	];
	const index = buildIndex(tools);
	const v = index.vectors.get("p");
	const idf = (df) => Math.log(Math.max(index.N, 1) / (1 + df)) + 1;
	const rawTask = idf(2) * 1.4;
	const rawKw = idf(1); // kw facet weight is 1.0 (identity)
	const mag = Math.sqrt(rawTask * rawTask + rawKw * rawKw);
	assert.ok(Math.abs(v.get("task:x") - rawTask / mag) < 1e-9);
	assert.ok(Math.abs(v.get("kw:y") - rawKw / mag) < 1e-9);
});

test("termsOf via vectorFor: prefixes, dedup, all-wiki skip, empties, and type guard", () => {
	const tool = {
		name: "z",
		tasks: ["editing", "editing", ""],
		keywords: ["*"], // '*' kept for non-wiki facets
		forWikis: ["*", "en.wikipedia.org"], // bare '*' skipped for wiki
		audiences: ["editor"],
		toolType: "Web App"
	};
	const index = buildIndex([tool]);
	const keys = [...index.vectors.get("z").keys()].sort();
	assert.deepEqual(keys, ["aud:editor", "kw:*", "task:editing", "type:web app", "wiki:en.wikipedia.org"].sort());

	// toolType empty => no type term emitted.
	const noType = buildIndex([{ name: "n", tasks: ["x"], toolType: "" }]);
	assert.deepEqual([...noType.vectors.get("n").keys()], ["task:x"]);
});

test("vectorFor returns an empty vector for an all-wikis-only tool", () => {
	const idx = { N: 1, df: new Map() };
	assert.equal(similarity.vectorFor({ name: "w", forWikis: ["*"] }, idx).size, 0);
});

test("cosine multiplies matched weights and clamps to [0,1]", () => {
	assert.equal(similarity.cosine(new Map([["x", 0.5]]), new Map([["x", 0.5]])), 0.25);
	assert.equal(similarity.cosine(new Map([["x", 2]]), new Map([["x", 2]])), 1); // clamped from 4
	assert.equal(similarity.cosine(new Map([["x", 1]]), new Map([["y", 1]])), 0); // disjoint
	// asymmetric sizes still give the same (commutative) score
	assert.equal(
		similarity.cosine(
			new Map([["x", 0.5]]),
			new Map([
				["x", 0.5],
				["y", 0.5],
				["z", 0.5]
			])
		),
		0.25
	);
});

test("nearestNeighbors ranks by score, applies k, skips empty/missing vectors", () => {
	const source = { name: "S", title: "S", tasks: ["a"], keywords: ["b"] };
	const near = { name: "N", title: "N", tasks: ["a"], keywords: ["b"] }; // identical => high score
	const partial = { name: "P", title: "P", tasks: ["a"] }; // shares only task
	const none = { name: "X", title: "X", tasks: ["zzz"] }; // shares nothing => score 0, excluded
	const empty = { name: "E", title: "E", forWikis: ["*"] }; // empty vector => skipped
	const index = buildIndex([source, near, partial, none, empty]);
	// add a deliberately-missing vector entry
	index.tools = [...index.tools, { name: "M", title: "M" }];

	const all = similarity.nearestNeighbors(source, index, 6);
	assert.deepEqual(
		all.map((r) => r.tool.name),
		["N", "P"]
	);
	assert.ok(all[0].score >= all[1].score);

	// k limits the result
	assert.equal(similarity.nearestNeighbors(source, index, 1).length, 1);
	assert.equal(similarity.nearestNeighbors(source, index, 1)[0].tool.name, "N");

	// empty source vector => no neighbors
	assert.deepEqual(similarity.nearestNeighbors({ name: "ZZ", forWikis: ["*"] }, index, 6), []);
});

test("nearestNeighbors breaks score ties by title-or-name, and lists shared term labels", () => {
	const source = { name: "src", title: "Src", tasks: ["a"], keywords: ["b"] };
	const byTitle = { name: "zeta", title: "Beta", tasks: ["a"], keywords: ["b"] };
	const byName = { name: "alpha", title: "", tasks: ["a"], keywords: ["b"] };
	const index = buildIndex([source, byTitle, byName]);
	const out = similarity.nearestNeighbors(source, index, 5);
	// equal scores => sorted by (title || name): "alpha" (name) before "Beta"
	assert.deepEqual(
		out.map((r) => r.tool.name),
		["alpha", "zeta"]
	);
	// shared labels are the value parts, not the prefixed terms
	assert.deepEqual(out[0].shared.sort(), ["a", "b"]);
});

test("sharedTermsForVector skips terms present in only one tool", () => {
	const source = { name: "s", title: "s", keywords: ["a", "b"] };
	const other = { name: "o", title: "o", keywords: ["a", "c"] };
	const index = buildIndex([source, other]);
	const out = similarity.nearestNeighbors(source, index, 5);
	// only "a" is shared; "b" (source-only) must be skipped, not pushed with NaN.
	assert.deepEqual(out[0].shared, ["a"]);
});

test("sharedTermsForVector orders by combined weight then label, requiring a real sort", () => {
	// task outweighs keyword; the two keywords tie on weight and break by label.
	const source = { name: "s", title: "s", tasks: ["t"], keywords: ["z", "a"] };
	const other = { name: "o", title: "o", tasks: ["t"], keywords: ["z", "a"] };
	const index = buildIndex([source, other]);
	const out = similarity.nearestNeighbors(source, index, 5);
	// insertion order is [t, z, a]; correct output sorts the tied keywords => [t, a, z].
	assert.deepEqual(out[0].shared, ["t", "a", "z"]);
});

test("nearestNeighbors orders strictly by score before any tiebreak", () => {
	const source = { name: "src", title: "src", keywords: ["p", "q"] };
	const nHi = { name: "Zhi", title: "Zhi", keywords: ["p", "q"] }; // shares both => higher score
	const nLo = { name: "Alo", title: "Alo", keywords: ["p"] }; // shares one => lower score
	const index = buildIndex([source, nHi, nLo]);
	const out = similarity.nearestNeighbors(source, index, 5);
	assert.ok(out[0].score > out[1].score);
	// score wins over the alphabetical name tiebreak (Alo < Zhi).
	assert.deepEqual(
		out.map((r) => r.tool.name),
		["Zhi", "Alo"]
	);
});

test("nearestNeighbors tiebreak prefers title, falling back to name", () => {
	const source = { name: "src", title: "src", keywords: ["s"] };
	const nP = { name: "Zeta", title: "Apple", keywords: ["s"] };
	const nQ = { name: "Beta", title: "Zebra", keywords: ["s"] };
	const index = buildIndex([source, nP, nQ]);
	const out = similarity.nearestNeighbors(source, index, 5);
	// equal scores => sort by TITLE ("Apple" < "Zebra"), not name ("Beta" < "Zeta").
	assert.deepEqual(
		out.map((r) => r.tool.name),
		["Zeta", "Beta"]
	);
});

test("sharedTermsForVector caps at 5 and sorts by combined weight then label", () => {
	// source and other share 6 keyword terms; result must cap to 5.
	const mk = (name) => ({
		name,
		title: name,
		keywords: ["k1", "k2", "k3", "k4", "k5", "k6"]
	});
	const source = mk("s");
	const other = mk("o");
	const index = buildIndex([source, other]);
	const out = similarity.nearestNeighbors(source, index, 5);
	const shared = out[0].shared;
	assert.equal(shared.length, 5);
	for (const label of shared) assert.ok(/^k[1-6]$/.test(label));
});
