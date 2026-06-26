// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { afterEach, beforeEach, test, vi } from "vitest";
import { installStorage } from "./_storage-setup.mjs";
import * as api from "../../public_html/lib/core/api.js";
import * as session from "../../public_html/lib/core/session.js";
import { demoStore, DEMO_KEYS } from "../../public_html/lib/core/store.js";

let originalFetch;
beforeEach(() => {
	installStorage();
	originalFetch = globalThis.fetch;
	session.applyExp(false);
});
afterEach(() => {
	globalThis.fetch = originalFetch;
	session.applyExp(false);
});

const tick = () =>
	new Promise((r) => {
		setTimeout(r, 5);
	});

// ----------------------------------------------------------------- scalars
test("firstUrl treats empty string as no url", () => {
	assert.equal(api.firstUrl(""), null);
	assert.equal(api.firstUrl(0), null);
	assert.equal(api.firstUrl("https://x.example"), "https://x.example");
	assert.equal(api.firstUrl([{ url: "https://a.example" }]), "https://a.example");
	assert.equal(api.firstUrl(["https://b.example"]), "https://b.example");
});

test("isNewTool reflects the demo new-tool overlay", () => {
	demoStore.set(DEMO_KEYS.toolNew, { IN: { title: "t" } });
	assert.equal(api.isNewTool("IN"), true);
	assert.equal(api.isNewTool("nope"), false);
});

// ----------------------------------------------------------------- fetchJson retries
test("apiGet retries network errors with exact backoff and rethrows after the cap", async () => {
	const sleeps = [];
	vi.stubGlobal("setTimeout", (fn, ms) => {
		sleeps.push(ms);
		fn();
		return 0;
	});
	let calls = 0;
	globalThis.fetch = async () => {
		calls += 1;
		throw new Error("netfail");
	};
	try {
		await assert.rejects(api.apiGet("/net-retry/", { n: "1" }), /netfail/);
		assert.equal(calls, 3);
		assert.deepEqual(sleeps, [200, 400]);
	} finally {
		vi.unstubAllGlobals();
	}
});

test("apiGet retries 502/503/504 with exact backoff and rethrows API <status>", async () => {
	const sleeps = [];
	vi.stubGlobal("setTimeout", (fn, ms) => {
		sleeps.push(ms);
		fn();
		return 0;
	});
	let calls = 0;
	globalThis.fetch = async () => {
		calls += 1;
		return { ok: false, status: 503 };
	};
	try {
		await assert.rejects(api.apiGet("/status-retry/", { n: "1" }), /API 503/);
		assert.equal(calls, 3);
		assert.deepEqual(sleeps, [200, 400]);
	} finally {
		vi.unstubAllGlobals();
	}
});

test("fetchJson sends the JSON Accept header to the proxied /api URL", async () => {
	let seenUrl, seenOpts;
	globalThis.fetch = async (url, opts) => {
		seenUrl = url;
		seenOpts = opts;
		return { ok: true, json: async () => ({ ok: 1 }) };
	};
	await api.apiGet("/hdr-probe/", { a: "b" });
	assert.equal(seenUrl, "/api/hdr-probe/?a=b");
	assert.deepEqual(seenOpts, { headers: { Accept: "application/json" } });

	// Without params there is no query string.
	await api.apiGet("/hdr-noparams/");
	assert.equal(seenUrl, "/api/hdr-noparams/");
});

// ----------------------------------------------------------------- SWR cache
test("apiGet caches, serves fresh hits without refetching, and revalidates stale entries", async () => {
	let now = 5_000_000;
	const nowSpy = vi.spyOn(Date, "now").mockImplementation(() => now);
	let calls = 0;
	const payloads = [{ v: "a" }, { v: "b" }];
	globalThis.fetch = async () => {
		const body = payloads[Math.min(calls, payloads.length - 1)];
		calls += 1;
		return { ok: true, json: async () => body };
	};
	try {
		const url = "/swr-1/";
		const d1 = await api.apiGet(url);
		assert.equal(d1.v, "a");
		assert.equal(calls, 1);

		// fresh hit: no refetch
		const d2 = await api.apiGet(url);
		assert.equal(d2.v, "a");
		assert.equal(calls, 1);

		// advance exactly the TTL => stale; returns stale value immediately and
		// kicks off a background revalidate that replaces the cache.
		now += 30000;
		const d3 = await api.apiGet(url);
		assert.equal(d3.v, "a");
		await tick();
		assert.equal(calls, 2); // revalidate fetched
		const d4 = await api.apiGet(url);
		assert.equal(d4.v, "b"); // cache updated (inflight was cleared in finally)
	} finally {
		nowSpy.mockRestore();
	}
});

test("apiFetch dedupes concurrent requests for the same url", async () => {
	let calls = 0;
	globalThis.fetch = async () => {
		calls += 1;
		return { ok: true, json: async () => ({ v: "x" }) };
	};
	const url = "/dedupe-1/";
	const [a, b] = await Promise.all([api.apiGet(url), api.apiGet(url)]);
	assert.equal(a.v, "x");
	assert.equal(b.v, "x");
	assert.equal(calls, 1);
});

// ----------------------------------------------------------------- paginate
function pageFetch(pages) {
	// pages: map of page-number -> { results, next }
	return async (url) => {
		const m = /[&?]page=(\d+)/.exec(String(url));
		const page = m ? m[1] : "1";
		const body = pages[page] || { results: [], next: null };
		return { ok: true, json: async () => body };
	};
}

test("paginate walks pages, maps items, and sends page_size/page params", async () => {
	const seen = [];
	globalThis.fetch = async (url) => {
		seen.push(String(url));
		const m = /[&?]page=(\d+)/.exec(String(url));
		const page = m ? m[1] : "1";
		const body =
			page === "1"
				? { results: [{ name: "a" }, { name: "b" }], next: "?page=2" }
				: { results: [{ name: "c" }], next: null };
		return { ok: true, json: async () => body };
	};
	const out = await api.paginate("/pg-walk/", { q: "x" }, { pageSize: 25, map: (r) => r.name });
	assert.deepEqual(out, ["a", "b", "c"]);
	assert.ok(seen[0].includes("page_size=25"));
	assert.ok(seen[0].includes("page=1"));
	assert.ok(seen[0].includes("q=x"));
	assert.ok(seen[1].includes("page=2"));
});

test("paginate stops at maxPages even when next persists", async () => {
	let calls = 0;
	globalThis.fetch = async () => {
		calls += 1;
		return { ok: true, json: async () => ({ results: [{ name: "x" }], next: "?page=next" }) };
	};
	const out = await api.paginate("/pg-max/", {}, { maxPages: 3, map: (r) => r.name });
	assert.deepEqual(out, ["x", "x", "x"]);
	assert.equal(calls, 3);
});

test("paginate stops on an empty results page and never reaches later pages", async () => {
	globalThis.fetch = pageFetch({
		1: { results: [{ name: "a" }], next: "?page=2" },
		2: { results: [], next: "?page=3" },
		3: { results: [{ name: "c" }], next: null }
	});
	const out = await api.paginate("/pg-empty/", {}, { map: (r) => r.name });
	assert.deepEqual(out, ["a"]);
});

test("paginate stops when next is missing and tolerates a missing results field", async () => {
	globalThis.fetch = pageFetch({ 1: { results: [{ name: "a" }] } }); // no next
	assert.deepEqual(await api.paginate("/pg-nonext/", {}, { map: (r) => r.name }), ["a"]);

	globalThis.fetch = pageFetch({ 1: { next: null } }); // no results field
	assert.deepEqual(await api.paginate("/pg-noresults/", {}), []);
});

test("paginate breaks (returns what it has) when a page request errors", async () => {
	globalThis.fetch = async (url) => {
		if (/page=2/.test(String(url))) throw new Error("boom");
		return { ok: true, json: async () => ({ results: [{ name: "a" }], next: "?page=2" }) };
	};
	assert.deepEqual(await api.paginate("/pg-err/", {}, { map: (r) => r.name }), ["a"]);
});

// ----------------------------------------------------------------- normalizeTool / authors
test("normalizeTool fills compact defaults for a minimal record", () => {
	const o = api.normalizeTool({ name: "min" });
	assert.equal(o.name, "min");
	assert.equal(o.title, "min");
	assert.equal(o.description, "");
	assert.equal(o.url, "");
	assert.equal(o.icon, null);
	assert.equal(o.maintainer, "Unknown");
	assert.equal(o.origin, "crawler");
	assert.equal(o.deprecated, false);
	assert.equal(o.experimental, false);
	assert.equal(o.modified, null);
	for (const f of [
		"keywords",
		"authors",
		"authorObjs",
		"technologyUsed",
		"audiences",
		"tasks",
		"forWikis",
		"uiLanguages",
		"sponsor"
	]) {
		assert.deepEqual(o[f], [], `${f} should default to []`);
	}
	// firstUrl([]) === null for the doc/feedback fields (their pick fallback is []).
	assert.equal(o.userDocs, null);
	assert.equal(o.devDocs, null);
	assert.equal(o.feedback, null);
	assert.deepEqual(o.status, { level: "green", label: "Healthy" });
});

test("normalizeTool normalizes a single (non-array) author", () => {
	const str = api.normalizeTool({ name: "solo", author: "Solo Dev" });
	assert.deepEqual(str.authorObjs, [{ name: "Solo Dev", url: null, wikiUsername: null, developerUsername: null }]);
	const obj = api.normalizeTool({ name: "solo2", author: { name: "Obj Dev", url: "https://o.example" } });
	assert.deepEqual(obj.authorObjs, [
		{ name: "Obj Dev", url: "https://o.example", wikiUsername: null, developerUsername: null }
	]);
});

test("normalizeTool normalizes a heterogeneous author array via normalizeAuthorObj", () => {
	const o = api.normalizeTool({
		name: "auth",
		author: [
			"Ada",
			{ name: "Bob", url: "https://bob.example", wiki_username: "BobW", developer_username: "bobd" },
			{ name: "Cleo" },
			{ url: "https://nameless.example" }, // no name => dropped
			"", // empty string => dropped
			null // => dropped
		]
	});
	assert.deepEqual(o.authors, ["Ada", "Bob", "Cleo"]);
	assert.equal(o.authorObjs.length, 3);
	assert.deepEqual(o.authorObjs[0], { name: "Ada", url: null, wikiUsername: null, developerUsername: null });
	assert.deepEqual(o.authorObjs[1], {
		name: "Bob",
		url: "https://bob.example",
		wikiUsername: "BobW",
		developerUsername: "bobd"
	});
	assert.deepEqual(o.authorObjs[2], { name: "Cleo", url: null, wikiUsername: null, developerUsername: null });
	assert.equal(o.maintainer, "Ada");
});

// ----------------------------------------------------------------- overlays
test("applyToolOverlay merges edits, then annotations, and recomputes status", () => {
	demoStore.set(DEMO_KEYS.toolEdits, { T: { description: "edited", deprecated: true } });
	demoStore.set(DEMO_KEYS.toolAnnos, { T2: { subtitle: "anno" } });

	const edited = api.applyToolOverlay({ name: "T", description: "x", deprecated: false });
	assert.equal(edited.description, "edited");
	assert.equal(edited.deprecated, true);
	assert.equal(edited.edited, true);
	assert.deepEqual(edited.status, { level: "red", label: "Deprecated" });

	const annotated = api.applyToolOverlay({ name: "T2", subtitle: "x" });
	assert.equal(annotated.subtitle, "anno");
	assert.equal(annotated.annotated, true);

	const untouched = api.applyToolOverlay({ name: "none", deprecated: true });
	assert.equal(untouched.edited, undefined);
	assert.equal(untouched.annotated, undefined);
	assert.equal(untouched.status, undefined); // neither edit nor anno => status not set
});

test("newToolBase builds a compact record with defaults or null for unknown names", () => {
	// rec omits keywords so the default [] is used (and asserted).
	demoStore.set(DEMO_KEYS.toolNew, { NT: { title: "New", description: "d", url: "u" } });
	const o = api.newToolBase("NT");
	assert.equal(o.name, "NT");
	assert.equal(o.title, "New");
	assert.equal(o.maintainer, "Ada Lovelace");
	assert.equal(o.deprecated, false);
	assert.equal(o.experimental, false);
	assert.equal(o.origin, "api");
	assert.equal(typeof o.weeklyViews, "number");
	assert.deepEqual(o.status, { level: "green", label: "Healthy" });
	for (const f of ["keywords", "authors", "audiences", "tasks", "forWikis", "uiLanguages", "technologyUsed"]) {
		assert.deepEqual(o[f], [], `${f} should default to []`);
	}
	// a rec value overrides the default.
	demoStore.set(DEMO_KEYS.toolNew, { NT2: { title: "New2", description: "d", url: "u", keywords: ["k"] } });
	assert.deepEqual(api.newToolBase("NT2").keywords, ["k"]);
	assert.equal(api.newToolBase("absent"), null);
});

test("normalizeTool applies the demo overlay only when experimental mode is on", () => {
	demoStore.set(DEMO_KEYS.toolEdits, { OV: { description: "overlaid" } });
	session.applyExp(false);
	const off = api.normalizeTool({ name: "OV", description: "orig" });
	assert.equal(off.edited, undefined);
	assert.equal(off.description, "orig");
	session.applyExp(true);
	const on = api.normalizeTool({ name: "OV", description: "orig" });
	assert.equal(on.edited, true);
	assert.equal(on.description, "overlaid");
	session.applyExp(false);
});

// ----------------------------------------------------------------- getTool / getToolsByName
test("getTool fetches+normalizes, returns null on failure, and uses newToolBase when signed in", async () => {
	let seenUrl;
	globalThis.fetch = async (url) => {
		seenUrl = url;
		if (/\/tools\/Bad\//.test(String(url))) throw new Error("nope");
		return { ok: true, json: async () => ({ name: "Good", title: "Good Tool" }) };
	};
	const good = await api.getTool("Good");
	assert.equal(good.name, "Good");
	assert.equal(good.title, "Good Tool");
	assert.equal(seenUrl, "/api/tools/Good/");

	assert.equal(await api.getTool("Bad"), null);

	// signed-in + new tool => newToolBase path, no fetch
	session.applyExp(true);
	session.setAuth(true);
	demoStore.set(DEMO_KEYS.toolNew, { NewOne: { title: "N", description: "d", url: "u" } });
	const nt = await api.getTool("NewOne");
	assert.equal(nt.name, "NewOne");
	assert.equal(nt.origin, "api");
	session.applyExp(false);
});

test("getTool ignores newToolBase when not signed in (uses the live API path)", async () => {
	session.applyExp(false); // signedIn() === false
	demoStore.set(DEMO_KEYS.toolNew, { NewishOnly: { title: "t", description: "d", url: "u" } });
	globalThis.fetch = async () => ({ ok: true, json: async () => ({ name: "NewishOnly" }) });
	const t = await api.getTool("NewishOnly");
	// apiGet path => normalizeTool default origin "crawler"; newToolBase would give "api".
	assert.equal(t.origin, "crawler");
});

test("getToolsByName resolves each name and filters out failures", async () => {
	globalThis.fetch = async (url) => {
		if (/\/tools\/B\//.test(String(url))) throw new Error("nope");
		const m = /\/tools\/([^/]+)\//.exec(String(url));
		const name = m ? decodeURIComponent(m[1]) : "?";
		return { ok: true, json: async () => ({ name }) };
	};
	const out = await api.getToolsByName(["A", "B", "C"]);
	assert.deepEqual(
		out.map((t) => t.name),
		["A", "C"]
	);
	assert.deepEqual(await api.getToolsByName([]), []);
	// undefined uses the `names || []` fallback => empty (a non-empty fallback would fetch).
	assert.deepEqual(await api.getToolsByName(undefined), []);
});

// ----------------------------------------------------------------- normalizeList
test("normalizeList normalizes embedded tools and applies defaults", () => {
	const list = api.normalizeList({ id: "L", tools: [{ name: "a" }, { name: "b" }] });
	assert.equal(list.id, "L");
	assert.equal(list.title, "Untitled list");
	assert.equal(list.description, "");
	assert.equal(list.toolCount, 2);
	assert.equal(list.featured, false);
	assert.equal(list.tools[0].name, "a");

	const featured = api.normalizeList({ id: "L2", title: "T", description: "D", featured: true });
	assert.equal(featured.title, "T");
	assert.equal(featured.toolCount, 0);
	assert.equal(featured.featured, true);
});
