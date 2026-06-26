// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test } from "vitest";
// Static imports (not dynamic path imports) so Stryker's vitest runner can
// instrument and mutate these modules. The DOM/localStorage/fetch globals these
// modules touch are provided by the happy-dom environment (see vitest.config.mjs).
import * as util from "../../public_html/lib/core/util.js";
import * as dom from "../../public_html/lib/core/dom.js";
import * as routing from "../../public_html/lib/core/routing.js";
import * as api from "../../public_html/lib/core/api.js";
import * as signals from "../../public_html/lib/core/signals.js";
import * as similarity from "../../public_html/lib/core/similarity.js";
import * as synth from "../../public_html/lib/core/synth.js";

test("normStr normalizes absent, padded, and mixed-case values", () => {
	assert.equal(util.normStr(null), "");
	assert.equal(util.normStr(undefined), "");
	assert.equal(util.normStr("  ToolHub  "), "toolhub");
	assert.equal(util.normStr(42), "42");
});

test("memoizeAsync runs the builder exactly once and reuses failures", async () => {
	let successCalls = 0;
	const cached = util.memoizeAsync(async () => {
		successCalls++;
		return { ok: true };
	});
	const [first, second] = await Promise.all([cached(), cached()]);
	assert.equal(successCalls, 1);
	assert.equal(first, second);

	let failureCalls = 0;
	const failing = util.memoizeAsync(async () => {
		failureCalls++;
		throw new Error("boom");
	});
	await assert.rejects(failing, /boom/);
	await assert.rejects(failing, /boom/);
	assert.equal(failureCalls, 1);
});

test("DOM helpers escape, hash, and constrain URLs deterministically", () => {
	const scriptUrl = ["java", "script:alert(1)"].join("");
	assert.equal(dom.esc(`<&>"'`), "&lt;&amp;&gt;&quot;&#39;");
	assert.equal(dom.esc(null), "");
	assert.equal(dom.safeUrl(" https://example.org/?a=<x> "), "https://example.org/?a=&lt;x&gt;");
	assert.equal(dom.safeUrl(scriptUrl), "");
	assert.equal(dom.safeUrl(null), "");
	assert.equal(dom.safeUrl("/relative"), "");
	assert.equal(dom.normalizeVcsUrl("git+https://github.com/example/repo.git"), "https://github.com/example/repo");
	assert.equal(
		dom.normalizeVcsUrl("git@gitlab.wikimedia.org:repos/toolhub/demo.git"),
		"https://gitlab.wikimedia.org/repos/toolhub/demo"
	);
	assert.equal(
		dom.normalizeVcsUrl("ssh://git@gerrit.wikimedia.org/wikimedia/toolhub.git"),
		"https://gerrit.wikimedia.org/wikimedia/toolhub"
	);
	assert.equal(dom.normalizeVcsUrl("https://example.org/repo.git"), "https://example.org/repo.git");
	assert.equal(dom.normalizeVcsUrl(""), "");
	assert.equal(dom.normalizeVcsUrl(null), "");
	assert.equal(dom.normalizeVcsUrl(undefined), "");
	assert.equal(dom.dirAttrs("text"), ' dir="auto"');
	assert.equal(dom.dirAttrs(""), "");
	assert.equal(dom.hash("toolhub"), dom.hash("toolhub"));
	assert.notEqual(dom.hash("toolhub"), dom.hash("Toolhub"));
});

test("route href helpers encode path segments only", () => {
	assert.equal(routing.toolHref("Tool/One Two"), "/tools/Tool%2FOne%20Two");
	assert.equal(routing.listHref("curated tools"), "/lists/curated%20tools");
	assert.equal(routing.authorHref("Ada Lovelace"), "/by/Ada%20Lovelace");
});

test("API scalar helpers preserve core data priority and empty semantics", () => {
	assert.equal(api.firstUrl("https://example.org"), "https://example.org");
	assert.equal(api.firstUrl(null), null);
	assert.equal(api.firstUrl([{ url: "https://docs.example" }]), "https://docs.example");
	assert.equal(api.firstUrl(["https://plain.example"]), "https://plain.example");
	assert.equal(api.firstUrl([]), null);
	assert.equal(api.firstUrl({ url: "https://ignored.example" }), null);
	assert.equal(api.hasValue([]), false);
	assert.equal(api.hasValue(["x"]), true);
	assert.equal(api.hasValue(""), false);
	assert.equal(api.hasValue(0), true);
	assert.equal(api.pick("core", "annotation", "fallback"), "core");
	assert.equal(api.pick("", "annotation", "fallback"), "annotation");
	assert.equal(api.pick(null, [], "fallback"), "fallback");
	assert.deepEqual(api.statusOf({ deprecated: true, experimental: true }), { level: "red", label: "Deprecated" });
	assert.deepEqual(api.statusOf({ experimental: true }), { level: "yellow", label: "Experimental" });
	assert.deepEqual(api.statusOf({}), { level: "green", label: "Healthy" });
});

test("normalizeTool maps live Toolhub schema into compact UI schema", () => {
	const normalized = api.normalizeTool({
		name: "toolforge-admin",
		title: "",
		description: "Admin interface",
		url: "",
		icon: null,
		keywords: ["toolforge"],
		author: [{ name: "Bryan Davis", wiki_username: "BDavis (WMF)", url: "https://meta.example/User" }],
		created_by: { username: "fallback" },
		annotations: {
			url: "https://admin.toolforge.org/",
			icon: "https://commons.example/icon.svg",
			audiences: ["developer"],
			user_docs_url: [{ url: "https://wikitech.example/docs" }],
			deprecated: false
		},
		for_wikis: ["*"],
		tool_type: "web app",
		modified_date: "2026-05-01T00:00:00Z"
	});
	assert.equal(normalized.name, "toolforge-admin");
	assert.equal(normalized.title, "toolforge-admin");
	assert.equal(normalized.description, "Admin interface");
	assert.equal(normalized.url, "https://admin.toolforge.org/");
	assert.equal(normalized.icon, "https://commons.example/icon.svg");
	assert.deepEqual(normalized.authors, ["Bryan Davis"]);
	assert.equal(normalized.authorObjs[0].wikiUsername, "BDavis (WMF)");
	assert.equal(normalized.maintainer, "Bryan Davis");
	assert.deepEqual(normalized.audiences, ["developer"]);
	assert.deepEqual(normalized.forWikis, ["*"]);
	assert.equal(normalized.toolType, "web app");
	assert.equal(normalized.userDocs, "https://wikitech.example/docs");
	assert.equal(normalized.status.level, "green");
	assert.equal(typeof normalized.weeklyViews, "number");
});

test("normalizeTool covers author and annotation fallbacks", () => {
	const stringAuthor = api.normalizeTool({
		name: "string-author",
		description: "",
		author: "Ada Lovelace",
		annotations: {
			description: "ignored",
			deprecated: true,
			experimental: true
		},
		modified: "2026-04-01T00:00:00Z",
		origin: "manual"
	});
	assert.deepEqual(stringAuthor.authors, ["Ada Lovelace"]);
	assert.equal(stringAuthor.maintainer, "Ada Lovelace");
	assert.equal(stringAuthor.description, "");
	assert.equal(stringAuthor.deprecated, true);
	assert.equal(stringAuthor.experimental, true);
	assert.equal(stringAuthor.modified, "2026-04-01T00:00:00Z");
	assert.equal(stringAuthor.origin, "manual");

	const mixedAuthors = api.normalizeTool({
		name: "mixed-authors",
		author: ["Grace Hopper", { name: "Katherine Johnson" }],
		created_by: { username: "fallback" },
		keywords: null
	});
	assert.deepEqual(mixedAuthors.authors, ["Grace Hopper", "Katherine Johnson"]);
	assert.equal(mixedAuthors.maintainer, "Grace Hopper");
	assert.deepEqual(mixedAuthors.keywords, []);

	const creator = api.normalizeTool({ name: "creator-author", author: "", created_by: { username: "creator" } });
	assert.equal(creator.maintainer, "creator");
	assert.deepEqual(api.normalizeTool({ name: "object-author", author: { name: "Object Author" } }).authors, []);
	assert.equal(api.normalizeTool({ name: "anonymous" }).maintainer, "Unknown");
});

test("normalizeList normalizes embedded tools and title defaults", () => {
	const list = api.normalizeList({
		id: "featured",
		description: "Featured tools",
		featured: true,
		tools: [{ name: "demo", description: "Demo", author: "Ada" }]
	});
	assert.equal(list.id, "featured");
	assert.equal(list.title, "Untitled list");
	assert.equal(list.description, "Featured tools");
	assert.equal(list.toolCount, 1);
	assert.equal(list.tools[0].name, "demo");
	assert.equal(list.featured, true);
	assert.equal(api.normalizeList({ id: "empty" }).description, "");
});

test("trust signals distinguish complete, fresh, endorsed, and context-fitting tools", () => {
	const fullTool = {
		description: "A complete tool listing with enough descriptive text.",
		url: "https://example.org",
		repository: "https://git.example/repo",
		license: "GPL-3.0-or-later",
		keywords: ["editing"],
		audiences: ["developer"],
		userDocs: "https://docs.example",
		icon: "https://icon.example/icon.svg",
		bugtracker: "https://bugs.example",
		forWikis: ["*.wikipedia.org", "commons.wikimedia.org"],
		modified: "2026-01-01T00:00:00Z"
	};
	const complete = signals.completeness(fullTool);
	assert.equal(complete.filled, complete.total);
	assert.equal(signals.completeness({ description: "short" }).filled, 0);
	assert.deepEqual(signals.endorsementOf("tool", new Map([["tool", [{ id: "x", title: "X" }]]])), {
		count: 1,
		lists: [{ id: "x", title: "X" }]
	});
	assert.deepEqual(signals.fitsContext(fullTool, { wiki: "en.wikipedia.org", role: "developer" }), {
		wiki: true,
		role: true,
		fits: true
	});
	assert.deepEqual(signals.fitsContext(fullTool, { wiki: "wikidata.org", role: "reader" }), {
		wiki: false,
		role: false,
		fits: false
	});
	assert.deepEqual(signals.fitsContext(fullTool, { wiki: "commons.wikimedia.org" }), {
		wiki: true,
		role: false,
		fits: true
	});
	assert.deepEqual(signals.fitsContext(fullTool, { role: "developer" }), {
		wiki: false,
		role: true,
		fits: true
	});

	const originalNow = Date.now;
	Date.now = () => Date.parse("2026-06-25T00:00:00Z");
	try {
		assert.deepEqual(signals.freshness(fullTool), { known: true, fresh: true });
		assert.deepEqual(signals.freshness({ modified: "2020-01-01T00:00:00Z" }), { known: true, fresh: false });
		const boundary = new Date(Date.now() - 18 * 30 * 24 * 60 * 60 * 1000).toISOString();
		assert.deepEqual(signals.freshness({ modified: boundary }), { known: true, fresh: false });
		assert.deepEqual(signals.freshness({ modified: "not-a-date" }), { known: false, fresh: false });
	} finally {
		Date.now = originalNow;
	}
});

test("similarity vectors normalize weights and nearest neighbors are stable", () => {
	const source = {
		name: "source",
		title: "Source",
		tasks: ["editing"],
		keywords: ["citations"],
		forWikis: ["en.wikipedia.org"],
		audiences: ["editor"],
		toolType: "web app"
	};
	const close = {
		name: "close",
		title: "Close",
		tasks: ["editing"],
		keywords: ["citations"],
		forWikis: ["en.wikipedia.org"],
		audiences: ["editor"],
		toolType: "web app"
	};
	const far = {
		name: "far",
		title: "Far",
		tasks: ["uploading"],
		keywords: ["commons"],
		forWikis: ["commons.wikimedia.org"],
		audiences: ["organizer"],
		toolType: "bot"
	};
	const index = { tools: [source, close, far], df: new Map(), N: 3, vectors: new Map() };
	for (const tool of index.tools) {
		for (const term of [
			...(tool.tasks || []).map((value) => `task:${value}`),
			...(tool.keywords || []).map((value) => `kw:${value}`),
			...(tool.forWikis || []).map((value) => `wiki:${value}`),
			...(tool.audiences || []).map((value) => `aud:${value}`),
			`type:${tool.toolType}`
		]) {
			index.df.set(term, (index.df.get(term) || 0) + 1);
		}
	}
	for (const tool of index.tools) index.vectors.set(tool.name, similarity.vectorFor(tool, index));

	const sourceVector = index.vectors.get("source");
	const magnitude = Math.sqrt([...sourceVector.values()].reduce((sum, value) => sum + value * value, 0));
	assert.ok(Math.abs(magnitude - 1) < 0.000001);
	assert.equal(similarity.vectorFor({ name: "all-wikis", forWikis: ["*"] }, index).size, 0);
	const zeroNVector = similarity.vectorFor(source, { N: 0, df: new Map() });
	assert.ok([...zeroNVector.values()].every((value) => Number.isFinite(value)));
	assert.ok(sourceVector.get("task:editing") > sourceVector.get("kw:citations"));
	assert.equal(similarity.cosine(new Map([["x", 2]]), new Map([["x", 2]])), 1);
	assert.equal(similarity.cosine(new Map([["x", 1]]), new Map([["y", 1]])), 0);
	assert.deepEqual(
		similarity
			.nearestNeighbors(source, { ...index, tools: [source, close, far, null, { name: "missing" }] }, 5)
			.map((item) => item.tool.name),
		["close"]
	);

	const closeByName = { ...close, name: "alpha", title: "" };
	const closeByTitle = { ...close, name: "zeta", title: "Beta" };
	const tiedIndex = {
		...index,
		tools: [source, closeByTitle, closeByName],
		vectors: new Map([
			["source", sourceVector],
			["alpha", similarity.vectorFor(closeByName, index)],
			["zeta", similarity.vectorFor(closeByTitle, index)]
		])
	};
	assert.deepEqual(
		similarity.nearestNeighbors(source, tiedIndex, 2).map((item) => item.tool.name),
		["alpha", "zeta"]
	);
});

test("synthetic signals are deterministic and constrained", () => {
	assert.equal(synth.synthSeed("toolforge-admin", "health"), synth.synthSeed("toolforge-admin", "health"));
	assert.notEqual(synth.synthSeed("toolforge-admin", "health"), synth.synthSeed("toolforge-admin", "thanks"));
	assert.equal(synth.synthViews("tool-140"), 2192);
	assert.equal(synth.synthViews("tool-12"), 570);
	assert.ok(synth.synthViews("toolforge-admin") >= 20);
	assert.deepEqual(synth.synthHealth("health-4"), { level: "red", label: "Down" });
	assert.deepEqual(synth.synthHealth("health-166"), { level: "yellow", label: "Degraded" });
	assert.ok(synth.synthThanks("toolforge-admin") >= 3);
	assert.ok(synth.synthUsage("toolforge-admin") >= 50);
	assert.match(synth.synthHealth("toolforge-admin").level, /^(green|yellow|red)$/);
});

test("apiGet retries a transient 503, then resolves", async () => {
	const original = globalThis.fetch;
	let calls = 0;
	globalThis.fetch = async () => {
		calls += 1;
		if (calls < 3) return { ok: false, status: 503 };
		return { ok: true, json: async () => ({ results: ["ok"] }) };
	};
	// Restore inside .finally (no await precedes that assignment).
	const data = await api.apiGet("/retry-probe/", { n: String(Math.random()) }).finally(() => {
		globalThis.fetch = original;
	});
	assert.equal(calls, 3);
	assert.deepEqual(data.results, ["ok"]);
});

test("apiGet does not retry a 404 (client error)", async () => {
	const original = globalThis.fetch;
	let calls = 0;
	globalThis.fetch = async () => {
		calls += 1;
		return { ok: false, status: 404 };
	};
	const attempt = () =>
		api.apiGet("/missing-probe/", { n: String(Math.random()) }).finally(() => {
			globalThis.fetch = original;
		});
	await assert.rejects(attempt, /API 404/);
	assert.equal(calls, 1);
});
