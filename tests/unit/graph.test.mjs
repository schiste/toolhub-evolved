// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test, vi } from "vitest";
// Static imports so Stryker's vitest runner can instrument and mutate graph.js.
// The async dependencies are mocked (getSimilarityIndex/listMemberships/getTool and
// nearestNeighbors) while cosine/vectorFor/endorsementOf/fitsContext stay real, so the
// graph logic under test runs against deterministic, fixture-built similarity indexes.
import * as graph from "../../public_html/lib/core/graph.js";
import * as similarity from "../../public_html/lib/core/similarity.js";
import * as signals from "../../public_html/lib/core/signals.js";
import * as api from "../../public_html/lib/core/api.js";

vi.mock("../../public_html/lib/core/similarity.js", async (importOriginal) => {
	const actual = await importOriginal();
	return { ...actual, getSimilarityIndex: vi.fn(), nearestNeighbors: vi.fn() };
});
vi.mock("../../public_html/lib/core/signals.js", async (importOriginal) => {
	const actual = await importOriginal();
	// endorsementOf stays real; listMemberships is fixture-driven; fitsContext is made
	// deterministic (it otherwise reads localStorage, which does not persist under the
	// test env) so node `.fits` is exercised both true and false.
	return {
		...actual,
		listMemberships: vi.fn(),
		fitsContext: vi.fn((tool) => {
			const fits = (tool.forWikis || []).includes("en.wikipedia.org");
			return { wiki: fits, role: false, fits };
		})
	};
});
vi.mock("../../public_html/lib/core/api.js", async (importOriginal) => {
	const actual = await importOriginal();
	return { ...actual, getTool: vi.fn() };
});

const entries = (map) => [...map.entries()];

// Replica of similarity.js termsOf, used only to build fixture indexes with realistic
// df/vectors via the real similarity.vectorFor.
function termsOf(tool) {
	const out = [];
	const seen = new Set();
	const push = (prefix, values, skipStar) => {
		for (const raw of values || []) {
			const v = String(raw === null || raw === undefined ? "" : raw)
				.trim()
				.toLowerCase();
			if (!v || (skipStar && v === "*")) continue;
			const term = `${prefix}:${v}`;
			if (seen.has(term)) continue;
			seen.add(term);
			out.push(term);
		}
	};
	push("task", tool.tasks);
	push("kw", tool.keywords);
	push("wiki", tool.forWikis, true);
	push("aud", tool.audiences);
	const type = String(tool.toolType === null || tool.toolType === undefined ? "" : tool.toolType)
		.trim()
		.toLowerCase();
	if (type) push("type", [type]);
	return out;
}

function buildIndex(tools) {
	const real = tools.filter((t) => t && t.name);
	const df = new Map();
	for (const t of real) for (const term of termsOf(t)) df.set(term, (df.get(term) || 0) + 1);
	const index = { tools, byName: new Map(), vectors: new Map(), df, N: real.length };
	for (const t of real) {
		index.byName.set(t.name, t);
		index.vectors.set(t.name, similarity.vectorFor(t, index));
	}
	return index;
}

// ---- knnEdges (pure; real cosine) -----------------------------------------

const knnIndex = {
	vectors: new Map([
		[
			"a",
			new Map([
				["t", 0.6],
				["u", 0.8]
			])
		],
		[
			"b",
			new Map([
				["t", 0.8],
				["u", 0.6]
			])
		],
		["c", new Map([["t", 1.0]])],
		["d", new Map([["z", 1.0]])],
		["e", new Map()]
	])
};

test("knnEdges dedupes names, drops unknown/empty vectors, and keeps the strongest undirected edges", () => {
	assert.deepEqual(graph.knnEdges(["a", "a", "b", "c", "d", "e", "missing"], knnIndex, 4), [
		{ source: "a", target: "b", weight: 0.96 },
		{ source: "a", target: "c", weight: 0.6 },
		{ source: "b", target: "c", weight: 0.8 }
	]);
});

test("knnEdges respects k and degenerate inputs", () => {
	assert.deepEqual(graph.knnEdges(["a", "b", "c"], knnIndex, 1), [
		{ source: "a", target: "b", weight: 0.96 },
		{ source: "b", target: "c", weight: 0.8 }
	]);
	assert.deepEqual(graph.knnEdges(null, knnIndex, 4), []);
	assert.deepEqual(graph.knnEdges(["a"], knnIndex, 4), []);
	// "d" only shares no terms with anyone (weight 0) and "e" has an empty vector.
	assert.deepEqual(graph.knnEdges(["d", "e"], knnIndex, 4), []);
});

// ---- detectCommunities (pure) ---------------------------------------------

test("detectCommunities groups connected nodes and numbers communities by size", () => {
	assert.deepEqual(
		entries(
			graph.detectCommunities(
				["a", "b", "c", "d"],
				[
					{ source: "a", target: "b", weight: 1 },
					{ source: "c", target: "d", weight: 1 }
				]
			)
		),
		[
			["a", 0],
			["b", 0],
			["c", 1],
			["d", 1]
		]
	);
});

test("detectCommunities normalizes node shapes, edge weights, and unknown endpoints", () => {
	const nodes = ["a", { id: "b" }, "a", { id: "" }, "", { id: "c" }];
	const edges = [
		{ source: "a", target: "b", weight: 1 },
		{ source: "b", target: "zzz", weight: 5 }, // zzz is not a node -> skipped
		{ source: "a", target: "c", weight: "notnum" } // weight coerces to 0
	];
	assert.deepEqual(entries(graph.detectCommunities(nodes, edges)), [
		["a", 0],
		["b", 0],
		["c", 0]
	]);
	// Missing weight also coerces to 0 and still links the nodes.
	assert.deepEqual(entries(graph.detectCommunities(["a", "b"], [{ source: "a", target: "b" }])), [
		["a", 0],
		["b", 0]
	]);
});

test("detectCommunities handles empty/nullish inputs and isolated singletons", () => {
	assert.deepEqual(entries(graph.detectCommunities(null, null)), []);
	assert.deepEqual(entries(graph.detectCommunities(["x", "y", "z"], [])), [
		["x", 0],
		["y", 1],
		["z", 2]
	]);
});

test("detectCommunities resolves two distinct clusters and a weighted chain", () => {
	const triEdges = [
		{ source: "a", target: "b", weight: 1 },
		{ source: "b", target: "c", weight: 1 },
		{ source: "a", target: "c", weight: 1 },
		{ source: "d", target: "e", weight: 1 },
		{ source: "e", target: "f", weight: 1 },
		{ source: "d", target: "f", weight: 1 },
		{ source: "c", target: "d", weight: 0.1 }
	];
	assert.deepEqual(entries(graph.detectCommunities(["a", "b", "c", "d", "e", "f"], triEdges)), [
		["a", 0],
		["b", 0],
		["c", 0],
		["d", 1],
		["e", 1],
		["f", 1]
	]);
	// A strong chain pulls every node into one community.
	assert.deepEqual(
		entries(
			graph.detectCommunities(
				["a", "b", "c", "d"],
				[
					{ source: "a", target: "b", weight: 0.1 },
					{ source: "b", target: "c", weight: 5 },
					{ source: "c", target: "d", weight: 5 }
				]
			)
		),
		[
			["a", 0],
			["b", 0],
			["c", 0],
			["d", 0]
		]
	);
});

test("detectCommunities output is keyed in sorted id order regardless of input order", () => {
	// If the internal id sort were dropped, the output Map order would follow input order.
	assert.deepEqual(
		entries(
			graph.detectCommunities(
				["c", "a", "b"],
				[
					{ source: "a", target: "b", weight: 1 },
					{ source: "b", target: "c", weight: 1 }
				]
			)
		),
		[
			["a", 0],
			["b", 0],
			["c", 0]
		]
	);
});

test("detectCommunities numbers larger communities first (size beats label order)", () => {
	// Triangle x/y/z (size 3) outranks pair a/b (size 2) even though "a" sorts before "x".
	assert.deepEqual(
		entries(
			graph.detectCommunities(
				["x", "y", "z", "a", "b"],
				[
					{ source: "x", target: "y", weight: 1 },
					{ source: "y", target: "z", weight: 1 },
					{ source: "x", target: "z", weight: 1 },
					{ source: "a", target: "b", weight: 1 }
				]
			)
		),
		[
			["a", 1],
			["b", 1],
			["x", 0],
			["y", 0],
			["z", 0]
		]
	);
});

test("detectCommunities ignores edges that reference an unknown node", () => {
	// The strong a->ghost edge must be dropped; otherwise it would split "a" off.
	assert.deepEqual(
		entries(
			graph.detectCommunities(
				["a", "b", "c"],
				[
					{ source: "a", target: "b", weight: 1 },
					{ source: "b", target: "c", weight: 1 },
					{ source: "a", target: "ghost", weight: 100 }
				]
			)
		),
		[
			["a", 0],
			["b", 0],
			["c", 0]
		]
	);
});

test("detectCommunities assigns a node to the neighborhood with the greatest summed weight", () => {
	// x is pulled to {a,b} because 1.5+1.5 > the single 2.0 edge to c.
	assert.deepEqual(
		entries(
			graph.detectCommunities(
				["a", "b", "c", "d", "x"],
				[
					{ source: "a", target: "b", weight: 5 },
					{ source: "c", target: "d", weight: 5 },
					{ source: "a", target: "x", weight: 1.5 },
					{ source: "b", target: "x", weight: 1.5 },
					{ source: "c", target: "x", weight: 2 }
				]
			)
		),
		[
			["a", 0],
			["b", 0],
			["c", 1],
			["d", 1],
			["x", 0]
		]
	);
});

test("detectCommunities breaks score ties toward the lexicographically smaller label", () => {
	// m ties between the z-cluster (seen first) and the a-cluster, and must pick "a".
	assert.deepEqual(
		entries(
			graph.detectCommunities(
				["a", "a2", "z", "z2", "m"],
				[
					{ source: "z", target: "z2", weight: 5 },
					{ source: "a", target: "a2", weight: 5 },
					{ source: "z", target: "m", weight: 1 },
					{ source: "a", target: "m", weight: 1 }
				]
			)
		),
		[
			["a", 0],
			["a2", 0],
			["m", 0],
			["z", 1],
			["z2", 1]
		]
	);
});

test("detectCommunities does not merge across a negative-weight edge", () => {
	// A negative score never clears the bestScore >= 0 bar, so the nodes stay separate.
	assert.deepEqual(entries(graph.detectCommunities(["a", "b"], [{ source: "a", target: "b", weight: -5 }])), [
		["a", 0],
		["b", 1]
	]);
});

// ---- globalGraph (memoized; one shot) -------------------------------------

function rep(name, base, count, extra = {}) {
	return Array.from({ length: count }, (_, i) => ({ name: `${name}${i}`, title: `${name} ${i}`, ...base, ...extra }));
}

function makeClusterTools() {
	const tools = [];
	// Community A (size 4, processed first): single-term label "alpha"; matches the user wiki.
	tools.push(...rep("a", { keywords: ["alpha"], tasks: ["atask"], forWikis: ["en.wikipedia.org"] }, 4));
	// Community B (size 3): top term overlaps "alpha" (already used) -> two-term label "alpha beta · btask".
	tools.push(...rep("b", { keywords: ["alpha beta"], tasks: ["btask"] }, 3));
	// Community C (size 2): every term overlaps "alpha" -> no distinct term -> fallback "Cluster N".
	tools.push(...rep("c", { keywords: ["alpha gamma", "beta alpha"] }, 2));
	// Community D (size 2): keyword and audience share a token -> communityTerms dedup path.
	tools.push(...rep("d", { keywords: ["dup"], tasks: ["dtask"], audiences: ["dup"] }, 2));
	// Community E (size 2): two equal-frequency keywords -> rankedFrequentTerms alpha tiebreak (apple < zebra).
	tools.push(...rep("e", { keywords: ["zebra", "apple"], tasks: ["etask"] }, 2));
	// Community F (size 2): differing keyword frequencies -> rankedFrequentTerms count-desc ordering.
	tools.push({ name: "f0", title: "f 0", keywords: ["fkw", "frare"], tasks: ["ftask"] });
	tools.push({ name: "f1", title: "f 1", keywords: ["fkw"], tasks: ["ftask"] });
	// Communities G, H, I (size 2): plain unique single-term clusters to push the total past the cap.
	for (const g of ["g", "h", "i"]) tools.push(...rep(g, { keywords: [`kw_${g}`], tasks: [`task_${g}`] }, 2));
	// A node with an empty title exercises the `tool.title || name` fallback.
	tools.push({ name: "j0", title: "", keywords: ["kw_j"], tasks: ["task_j"] });
	tools.push({ name: "j1", title: "J one", keywords: ["kw_j"], tasks: ["task_j"] });
	return tools;
}

test("globalGraph ranks, clusters, labels, caps, and annotates nodes (memoized, one shot)", async () => {
	const tools = makeClusterTools();
	// Filtered-out tools: null, blank name, and no keywords/tasks.
	tools.push(null);
	tools.push({ name: "", keywords: ["x"], tasks: ["y"] });
	tools.push({ name: "nokw", keywords: [], tasks: [] });
	const index = buildIndex(tools);
	similarity.getSimilarityIndex.mockResolvedValue(index);
	signals.listMemberships.mockResolvedValue(
		new Map([
			["a0", [{ id: "L1", title: "List One" }]],
			[
				"b0",
				[
					{ id: "L1", title: "List One" },
					{ id: "L2", title: "List Two" }
				]
			]
		])
	);

	const g = await graph.globalGraph();

	// Nodes: ranked by richness (desc) then title/name; filtered tools are absent; the
	// empty-title node falls back to its name; community ids cap at 8 with overflow "other";
	// degree (weight), endorsement, and fits are all annotated.
	assert.deepEqual(g.nodes, [
		{ id: "a0", title: "a 0", community: 0, weight: 3, endorsement: 1, fits: true },
		{ id: "a1", title: "a 1", community: 0, weight: 3, endorsement: 0, fits: true },
		{ id: "a2", title: "a 2", community: 0, weight: 3, endorsement: 0, fits: true },
		{ id: "a3", title: "a 3", community: 0, weight: 3, endorsement: 0, fits: true },
		{ id: "d0", title: "d 0", community: 3, weight: 1, endorsement: 0, fits: false },
		{ id: "d1", title: "d 1", community: 3, weight: 1, endorsement: 0, fits: false },
		{ id: "e0", title: "e 0", community: 4, weight: 1, endorsement: 0, fits: false },
		{ id: "e1", title: "e 1", community: 4, weight: 1, endorsement: 0, fits: false },
		{ id: "f0", title: "f 0", community: 5, weight: 1, endorsement: 0, fits: false },
		{ id: "b0", title: "b 0", community: 1, weight: 2, endorsement: 2, fits: false },
		{ id: "b1", title: "b 1", community: 1, weight: 2, endorsement: 0, fits: false },
		{ id: "b2", title: "b 2", community: 1, weight: 2, endorsement: 0, fits: false },
		{ id: "c0", title: "c 0", community: 2, weight: 1, endorsement: 0, fits: false },
		{ id: "c1", title: "c 1", community: 2, weight: 1, endorsement: 0, fits: false },
		{ id: "f1", title: "f 1", community: 5, weight: 1, endorsement: 0, fits: false },
		{ id: "g0", title: "g 0", community: 6, weight: 1, endorsement: 0, fits: false },
		{ id: "g1", title: "g 1", community: 6, weight: 1, endorsement: 0, fits: false },
		{ id: "h0", title: "h 0", community: 7, weight: 1, endorsement: 0, fits: false },
		{ id: "h1", title: "h 1", community: 7, weight: 1, endorsement: 0, fits: false },
		{ id: "i0", title: "i 0", community: "other", weight: 1, endorsement: 0, fits: false },
		{ id: "i1", title: "i 1", community: "other", weight: 1, endorsement: 0, fits: false },
		{ id: "j1", title: "J one", community: "other", weight: 1, endorsement: 0, fits: false },
		{ id: "j0", title: "j0", community: "other", weight: 1, endorsement: 0, fits: false }
	]);

	// Community labels exercise: single-term, two-term (top term overlaps an earlier label),
	// fallback (no distinct term), the dedup path, and the frequency/alpha term ordering.
	assert.deepEqual(g.communityMeta, [
		{ id: 0, label: "alpha", size: 4 },
		{ id: 1, label: "alpha beta · btask", size: 3 },
		{ id: 2, label: "Cluster 3", size: 2 },
		{ id: 3, label: "dup", size: 2 },
		{ id: 4, label: "apple", size: 2 },
		{ id: 5, label: "fkw", size: 2 },
		{ id: 6, label: "kw_g", size: 2 },
		{ id: 7, label: "kw_h", size: 2 }
	]);
	assert.equal(g.communities, 8);
	assert.equal(g.truncated, 0);

	// Edges connect intra-cluster pairs only (weights validated separately in the knnEdges tests).
	assert.deepEqual(
		g.edges.map((e) => [e.source, e.target]),
		[
			["a0", "a1"],
			["a0", "a2"],
			["a0", "a3"],
			["a1", "a2"],
			["a1", "a3"],
			["a2", "a3"],
			["b0", "b1"],
			["b0", "b2"],
			["b1", "b2"],
			["c0", "c1"],
			["d0", "d1"],
			["e0", "e1"],
			["f0", "f1"],
			["g0", "g1"],
			["h0", "h1"],
			["i0", "i1"],
			["j0", "j1"]
		]
	);
	assert.ok(g.edges.every((e) => e.weight > 0 && e.weight <= 1));
	// The 4-clique gives each community-A node degree 3.
	assert.equal(g.edges.filter((e) => e.source.startsWith("a")).length, 6);
});

const T1 = { name: "t1", title: "Tool One", keywords: ["x"], tasks: ["e"] };
const T2 = { name: "t2", title: "Tool Two", keywords: ["x"], tasks: ["e"] };
const T3 = { name: "t3", title: "Tool Three", keywords: ["y"] };
const T4 = { name: "t4", title: "Tool Four", keywords: ["x"] };

test("egoGraph centers on a known tool, skips null/duplicate neighbors, and weights by score*k", async () => {
	similarity.getSimilarityIndex.mockResolvedValue(buildIndex([T1, T2, T3]));
	// Neighbors include a null tool and a duplicate of the center to exercise the skip branches.
	similarity.nearestNeighbors.mockReturnValue([
		{ tool: T2, score: 0.9 },
		{ tool: null, score: 0.5 },
		{ tool: T1, score: 1 },
		{ tool: T3, score: 0.3 }
	]);
	const g = await graph.egoGraph("t1", 10);
	assert.deepEqual(g.nodes, [
		{ id: "t1", title: "Tool One", fits: false, center: true, score: 1, weight: 10 },
		{ id: "t2", title: "Tool Two", fits: false, center: false, score: 0.9, weight: 9 },
		{ id: "t3", title: "Tool Three", fits: false, center: false, score: 0.3, weight: 3 }
	]);
	assert.deepEqual(
		g.edges.map((e) => [e.source, e.target]),
		[["t1", "t2"]]
	);
	assert.equal(g.edges[0].weight, 1);
	assert.equal(g.center, "t1");
});

test("egoGraph resolves an unknown center via getTool and builds its vector", async () => {
	similarity.getSimilarityIndex.mockResolvedValue(buildIndex([T1, T2]));
	api.getTool.mockResolvedValue(T4);
	similarity.nearestNeighbors.mockReturnValue([{ tool: T1, score: 0.7 }]);
	const g = await graph.egoGraph("t4"); // default k = 10
	assert.deepEqual(g.nodes, [
		{ id: "t4", title: "Tool Four", fits: false, center: true, score: 1, weight: 10 },
		{ id: "t1", title: "Tool One", fits: false, center: false, score: 0.7, weight: 7 }
	]);
	assert.deepEqual(
		g.edges.map((e) => [e.source, e.target]),
		[["t1", "t4"]]
	);
	assert.ok(g.edges[0].weight > 0 && g.edges[0].weight < 1);
	assert.equal(g.center, "t4");
});

test("egoGraph rebuilds the center vector when the index has the name but not the vector", async () => {
	const partial = buildIndex([T1, T2]);
	partial.vectors.delete("t1");
	similarity.getSimilarityIndex.mockResolvedValue(partial);
	similarity.nearestNeighbors.mockReturnValue([{ tool: T2, score: 0.5 }]);
	const g = await graph.egoGraph("t1", 4);
	assert.deepEqual(g.nodes, [
		{ id: "t1", title: "Tool One", fits: false, center: true, score: 1, weight: 4 },
		{ id: "t2", title: "Tool Two", fits: false, center: false, score: 0.5, weight: 2 }
	]);
	assert.deepEqual(
		g.edges.map((e) => [e.source, e.target]),
		[["t1", "t2"]]
	);
	assert.equal(g.center, "t1");
});

test("egoGraph returns an empty graph when the tool is unknown", async () => {
	similarity.getSimilarityIndex.mockResolvedValue(buildIndex([T1, T2]));
	api.getTool.mockResolvedValue(null);
	assert.deepEqual(await graph.egoGraph("ghost"), { nodes: [], edges: [], center: "ghost" });
});
