// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "vitest";
import { installStorage } from "./_storage-setup.mjs";
import * as signals from "../../public_html/lib/core/signals.js";

const LISTS = {
	next: null,
	results: [
		{ id: "L1", title: "List One", published: true, tools: [{ name: "alpha" }, { name: "beta" }] },
		{ id: "L2", title: "", published: true, tools: [{ name: "alpha" }, null, { name: "" }] },
		{ id: "L3", title: "Hidden", published: false, tools: [{ name: "alpha" }] },
		{ id: "L4", tools: [{ name: "gamma" }] }, // published undefined => counted; title => "Untitled list"
		{ id: "L5", title: "No Tools", published: true } // tools missing => [] (no throw)
	]
};

let originalFetch;
const listsUrls = [];
beforeEach(() => {
	installStorage();
	originalFetch = globalThis.fetch;
	globalThis.fetch = async (url) => {
		if (String(url).includes("/lists/")) listsUrls.push(String(url));
		return {
			ok: true,
			json: async () => (String(url).includes("/lists/") ? LISTS : { results: [], next: null })
		};
	};
});
afterEach(() => {
	globalThis.fetch = originalFetch;
});

const FULL_ITEMS = [
	{ key: "description", label: "Description", ok: true },
	{ key: "url", label: "Tool URL", ok: true },
	{ key: "repository", label: "Source repository", ok: true },
	{ key: "license", label: "License", ok: true },
	{ key: "keywords", label: "Keywords", ok: true },
	{ key: "audienceOrTask", label: "Audience or task tagged", ok: true },
	{ key: "docs", label: "Documentation", ok: true },
	{ key: "icon", label: "Icon", ok: true },
	{ key: "contact", label: "Issue tracker or feedback", ok: true }
];

test("completeness reports exact keys, labels, and ok flags for a full tool", () => {
	const full = {
		description: "A complete listing with more than enough descriptive text here.",
		url: "https://example.org",
		repository: "https://git.example/repo",
		license: "GPL-3.0-or-later",
		keywords: ["editing"],
		audiences: ["developer"],
		tasks: [],
		userDocs: "https://docs.example",
		devDocs: "",
		icon: "https://icon.example/i.svg",
		bugtracker: "https://bugs.example",
		feedback: ""
	};
	const c = signals.completeness(full);
	assert.equal(c.filled, 9);
	assert.equal(c.total, 9);
	assert.deepEqual(c.items, FULL_ITEMS);
});

test("completeness marks every field unfilled for an empty tool", () => {
	const c = signals.completeness({});
	assert.equal(c.filled, 0);
	assert.equal(c.total, 9);
	assert.deepEqual(
		c.items.map((i) => i.ok),
		[false, false, false, false, false, false, false, false, false]
	);
});

test("completeness description needs >= 30 chars", () => {
	assert.equal(signals.completeness({ description: "x".repeat(30) }).items[0].ok, true);
	assert.equal(signals.completeness({ description: "x".repeat(29) }).items[0].ok, false);
});

test("completeness OR-fields: audience-or-task, docs, contact each accept either side", () => {
	const at = (t) => signals.completeness(t).items[5].ok;
	assert.equal(at({ audiences: ["x"] }), true);
	assert.equal(at({ tasks: ["y"] }), true);
	assert.equal(at({ audiences: [], tasks: [] }), false);

	const docs = (t) => signals.completeness(t).items[6].ok;
	assert.equal(docs({ userDocs: "u" }), true);
	assert.equal(docs({ devDocs: "d" }), true);
	assert.equal(docs({}), false);

	const contact = (t) => signals.completeness(t).items[8].ok;
	assert.equal(contact({ bugtracker: "b" }), true);
	assert.equal(contact({ feedback: "f" }), true);
	assert.equal(contact({}), false);
});

test("buildMemberships (via listMemberships) counts only published lists with named tools", async () => {
	const map = await signals.listMemberships();
	assert.deepEqual(signals.endorsementOf("alpha", map), {
		count: 2,
		lists: [
			{ id: "L1", title: "List One" },
			{ id: "L2", title: "Untitled list" }
		]
	});
	assert.deepEqual(signals.endorsementOf("beta", map), { count: 1, lists: [{ id: "L1", title: "List One" }] });
	assert.deepEqual(signals.endorsementOf("gamma", map), { count: 1, lists: [{ id: "L4", title: "Untitled list" }] });
	assert.deepEqual(signals.endorsementOf("missing", map), { count: 0, lists: [] });
	assert.deepEqual(signals.endorsementOf("alpha", null), { count: 0, lists: [] });
	// the {name:""} tool in L2 is skipped by the `if (!name)` guard => no "" key.
	assert.equal(signals.endorsementOf("", map).count, 0);
	// paginate is called with pageSize 50 (page_size param), not the default 100.
	assert.ok(listsUrls.length > 0);
	assert.ok(listsUrls[0].includes("page_size=50"), listsUrls[0]);
});

test("attachEndorsements decorates each tool with its endorsement", async () => {
	const tools = [{ name: "alpha" }, { name: "beta" }, { name: "missing" }];
	const out = await signals.attachEndorsements(tools);
	assert.equal(out, tools);
	assert.equal(out[0].endorsement.count, 2);
	assert.equal(out[1].endorsement.count, 1);
	assert.equal(out[2].endorsement.count, 0);
});

test("getUserContext reads/parses the context key and survives bad JSON", () => {
	assert.deepEqual(signals.getUserContext(), {});
	localStorage.setItem("toolhub-context", JSON.stringify({ wiki: "en.wikipedia.org", role: "editor" }));
	assert.deepEqual(signals.getUserContext(), { wiki: "en.wikipedia.org", role: "editor" });
	localStorage.setItem("toolhub-context", "{not json");
	assert.deepEqual(signals.getUserContext(), {});
});

test("setUserContext normalizes fields and clears when empty", () => {
	signals.setUserContext({ wiki: "W" });
	assert.deepEqual(signals.getUserContext(), { wiki: "W", role: "" });
	signals.setUserContext({ role: "R" });
	assert.deepEqual(signals.getUserContext(), { wiki: "", role: "R" });
	signals.setUserContext({ wiki: "W", role: "R" });
	assert.deepEqual(signals.getUserContext(), { wiki: "W", role: "R" });
	signals.setUserContext(null);
	assert.deepEqual(signals.getUserContext(), {});
	signals.setUserContext({ wiki: "W" });
	signals.setUserContext({}); // no wiki/role => removed
	assert.deepEqual(signals.getUserContext(), {});
});

test("hasContext is true when either wiki or role is set", () => {
	assert.equal(signals.hasContext(), false);
	signals.setUserContext({ wiki: "W" });
	assert.equal(signals.hasContext(), true);
	signals.setUserContext({ role: "R" });
	assert.equal(signals.hasContext(), true);
	signals.setUserContext(null);
	assert.equal(signals.hasContext(), false);
});

test("wikiMatches handles exact, family wildcard, and rejects bare * or pseudo-suffixes", () => {
	assert.equal(signals.wikiMatches(["en.wikipedia.org"], "en.wikipedia.org"), true);
	assert.equal(signals.wikiMatches(["*.wikipedia.org"], "en.wikipedia.org"), true);
	assert.equal(signals.wikiMatches(["commons.wikimedia.org"], "en.wikipedia.org"), false);
	assert.equal(signals.wikiMatches(["*"], "en.wikipedia.org"), false); // bare * is not specific
	assert.equal(signals.wikiMatches(["ax.foo"], "bx.foo"), false); // suffix match requires the "*." prefix
	assert.equal(signals.wikiMatches([], "en.wikipedia.org"), false);
	assert.equal(signals.wikiMatches(undefined, "en.wikipedia.org"), false);
});

test("fitsContext uses provided ctx or falls back to stored context", () => {
	const tool = { forWikis: ["en.wikipedia.org"], audiences: ["developer"] };
	assert.deepEqual(signals.fitsContext(tool, { wiki: "en.wikipedia.org", role: "developer" }), {
		wiki: true,
		role: true,
		fits: true
	});
	assert.deepEqual(signals.fitsContext(tool, { wiki: "fr.wikipedia.org", role: "reader" }), {
		wiki: false,
		role: false,
		fits: false
	});
	assert.deepEqual(signals.fitsContext({}, { wiki: "x", role: "y" }), { wiki: false, role: false, fits: false });
	assert.deepEqual(signals.fitsContext(tool, {}), { wiki: false, role: false, fits: false });
	// default ctx from storage
	signals.setUserContext({ role: "developer" });
	assert.deepEqual(signals.fitsContext(tool), { wiki: false, role: true, fits: true });
	signals.setUserContext(null);
});

test("rankFitsFirst is identity without context and stable fits-first with context", () => {
	signals.setUserContext(null);
	const a = { name: "A" };
	const b = { name: "B" };
	const input = [a, b];
	const noCtx = signals.rankFitsFirst(input);
	assert.equal(noCtx, input); // identity: same array returned untouched
	assert.deepEqual(
		noCtx.map((t) => t.name),
		["A", "B"]
	);

	signals.setUserContext({ wiki: "en.wikipedia.org" });
	const tA = { name: "A", forWikis: ["en.wikipedia.org"] };
	const tB = { name: "B", forWikis: [] };
	const tC = { name: "C", forWikis: ["en.wikipedia.org"] };
	const tD = { name: "D", forWikis: [] };
	const ranked = signals.rankFitsFirst([tB, tA, tD, tC]);
	assert.deepEqual(
		ranked.map((t) => t.name),
		["A", "C", "B", "D"]
	);

	// Two equally-fitting tools must keep input (index) order — the `a[1] - b[1]`
	// tiebreak. With `a[1] + b[1]` the (always-positive) comparator would swap them.
	const x = { name: "X", forWikis: ["en.wikipedia.org"] };
	const y = { name: "Y", forWikis: ["en.wikipedia.org"] };
	assert.deepEqual(
		signals.rankFitsFirst([x, y]).map((t) => t.name),
		["X", "Y"]
	);
	signals.setUserContext(null);
});
