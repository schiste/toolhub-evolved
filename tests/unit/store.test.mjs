// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test, beforeEach, afterAll, vi } from "vitest";
import * as store from "../../public_html/lib/core/store.js";
import * as session from "../../public_html/lib/core/session.js";

// This Node/happy-dom build ships a non-functional `localStorage` (its
// getItem/setItem/removeItem are not callable), so the modules under test would
// silently fall back to defaults and persist nothing. Install a faithful,
// Object.keys()-enumerable Storage polyfill before each test so persistence —
// and therefore every store branch — is observable.
function makeStorage() {
	const data = Object.create(null);
	const api = {
		getItem(key) {
			const k = String(key);
			return Object.prototype.hasOwnProperty.call(data, k) ? data[k] : null;
		},
		setItem(k, v) {
			data[String(k)] = String(v);
		},
		removeItem(k) {
			delete data[String(k)];
		},
		clear() {
			for (const k of Object.keys(data)) delete data[k];
		},
		key(i) {
			return Object.keys(data)[i] ?? null;
		},
		get length() {
			return Object.keys(data).length;
		}
	};
	return new Proxy(api, {
		ownKeys() {
			return Object.keys(data);
		},
		getOwnPropertyDescriptor(_t, p) {
			return Object.prototype.hasOwnProperty.call(data, p)
				? { enumerable: true, configurable: true, writable: true, value: data[p] }
				: Reflect.getOwnPropertyDescriptor(api, p);
		},
		has(_t, p) {
			return p in api || Object.prototype.hasOwnProperty.call(data, p);
		}
	});
}

beforeEach(() => {
	Object.defineProperty(globalThis, "localStorage", { value: makeStorage(), configurable: true, writable: true });
	Object.defineProperty(window, "localStorage", {
		value: globalThis.localStorage,
		configurable: true,
		writable: true
	});
	session.applyExp(false);
	session.setAuthRender(() => {});
});

// Some tests turn experimental mode on; reset it so the in-memory flag does not
// leak into sibling test files sharing the process under the Stryker test runner.
afterAll(() => {
	session.applyExp(false);
});

test("exported constants have their exact shape", () => {
	assert.equal(store.DEMO_NS, "thdemo:");
	assert.equal(store.FEED_LOG_CAP, 100);
	assert.deepEqual(store.DEMO_KEYS, {
		favorites: "favorites",
		lists: "lists",
		toolEdits: "toolEdits",
		toolAnnos: "toolAnnos",
		toolNew: "toolNew",
		revisions: "revisions",
		auditlogs: "auditlogs",
		crawlerUrls: "crawlerUrls"
	});
});

test("demoStore.get returns parsed value, default for missing, default for bad JSON", () => {
	assert.equal(store.demoStore.get("missing", "DEF"), "DEF");
	assert.equal(store.demoStore.get("missing"), undefined);
	store.demoStore.set("present", { a: 1 });
	assert.deepEqual(store.demoStore.get("present", "DEF"), { a: 1 });
	// stored under the namespaced key, not the bare key
	assert.equal(localStorage.getItem("thdemo:present"), JSON.stringify({ a: 1 }));
	assert.equal(localStorage.getItem("present"), null);
	// invalid JSON falls back to the default (the catch path)
	localStorage.setItem("thdemo:broken", "{not json");
	assert.equal(store.demoStore.get("broken", "DEF"), "DEF");
});

test("demoStore.set/remove round-trip through the namespaced key", () => {
	store.demoStore.set("k", [1, 2]);
	assert.deepEqual(store.demoStore.get("k"), [1, 2]);
	store.demoStore.remove("k");
	assert.equal(store.demoStore.get("k", "GONE"), "GONE");
	assert.equal(localStorage.getItem("thdemo:k"), null);
});

test("demoStore.clearAll wipes only namespaced keys", () => {
	store.demoStore.set("a", 1);
	store.demoStore.set("b", 2);
	localStorage.setItem("keepme", "raw");
	store.demoStore.clearAll();
	assert.equal(store.demoStore.get("a", "X"), "X");
	assert.equal(store.demoStore.get("b", "X"), "X");
	assert.equal(localStorage.getItem("keepme"), "raw");
});

test("withDemoFixture overlays values, returns render result, and restores prior state", () => {
	store.demoStore.set("lists", [{ id: 1 }]); // present beforehand
	let during;
	const ret = store.withDemoFixture({ lists: [{ id: 99 }], favorites: ["x"] }, () => {
		during = {
			lists: store.demoStore.get("lists"),
			favorites: store.demoStore.get("favorites")
		};
		return "RESULT";
	});
	assert.equal(ret, "RESULT");
	assert.deepEqual(during.lists, [{ id: 99 }]);
	assert.deepEqual(during.favorites, ["x"]);
	// present key restored to its prior value; absent key removed entirely
	assert.deepEqual(store.demoStore.get("lists"), [{ id: 1 }]);
	assert.equal(localStorage.getItem("thdemo:favorites"), null);
});

test("favNames / isFav reflect stored favorites", () => {
	assert.deepEqual(store.favNames(), []);
	assert.equal(store.isFav("a"), false);
	store.demoStore.set("favorites", ["a", "b"]);
	assert.deepEqual(store.favNames(), ["a", "b"]);
	assert.equal(store.isFav("a"), true);
	assert.equal(store.isFav("z"), false);
});

test("toggleFav adds then removes, returning the new state and preserving order", () => {
	assert.equal(store.toggleFav("a"), true);
	assert.deepEqual(store.favNames(), ["a"]);
	assert.equal(localStorage.getItem("thdemo:favorites"), JSON.stringify(["a"]));
	assert.equal(store.toggleFav("b"), true);
	assert.deepEqual(store.favNames(), ["a", "b"]);
	// removing "a" splices exactly one element, leaving "b"
	assert.equal(store.toggleFav("a"), false);
	assert.deepEqual(store.favNames(), ["b"]);
});

test("demoLists / demoListGet read stored lists with string-coerced ids", () => {
	assert.deepEqual(store.demoLists(), []);
	assert.equal(store.demoListGet("x"), null);
	store.demoStore.set("lists", [
		{ id: 5, title: "Five" },
		{ id: "7", title: "Seven" }
	]);
	assert.deepEqual(store.demoLists(), [
		{ id: 5, title: "Five" },
		{ id: "7", title: "Seven" }
	]);
	// numeric stored id matched by string query (String(l.id) === String(id))
	assert.deepEqual(store.demoListGet("5"), { id: 5, title: "Five" });
	// string stored id matched by numeric query
	assert.deepEqual(store.demoListGet(7), { id: "7", title: "Seven" });
	assert.equal(store.demoListGet("nope"), null);
});

test("isDemoListId only matches the demo- prefix", () => {
	assert.equal(store.isDemoListId("demo-abc"), true);
	assert.equal(store.isDemoListId("xdemo-"), false);
	assert.equal(store.isDemoListId("other"), false);
	assert.equal(store.isDemoListId(""), false);
});

test("demoListNew builds an empty list with a demo- id", () => {
	const now = vi.spyOn(Date, "now").mockReturnValue(123456);
	const rnd = vi.spyOn(Math, "random").mockReturnValue(0.71234);
	try {
		const list = store.demoListNew();
		const expectedId = `demo-${(123456).toString(36)}-${Math.floor(0.71234 * 1e4).toString(36)}`;
		assert.equal(list.id, expectedId);
		assert.equal(list.title, "");
		assert.equal(list.description, "");
		assert.deepEqual(list.tools, []);
		assert.equal(store.isDemoListId(list.id), true);
	} finally {
		now.mockRestore();
		rnd.mockRestore();
	}
});

test("demoListSave inserts new lists at the front with timestamps and updates in place", () => {
	vi.useFakeTimers();
	try {
		vi.setSystemTime(new Date("2026-01-01T00:00:00.000Z"));
		const a = store.demoListSave({ id: "a", title: "A", description: "", tools: [] });
		assert.equal(a.created, "2026-01-01T00:00:00.000Z");
		assert.equal(a.modified, "2026-01-01T00:00:00.000Z");
		assert.equal(store.demoLists().length, 1);
		assert.equal(store.demoLists()[0].id, "a");

		vi.setSystemTime(new Date("2026-02-02T00:00:00.000Z"));
		store.demoListSave({ id: "b", title: "B", description: "", tools: [] });
		// unshift => newest first
		assert.deepEqual(
			store.demoLists().map((l) => l.id),
			["b", "a"]
		);

		// update existing "a" in place: modified changes, created stays, position kept
		vi.setSystemTime(new Date("2026-03-03T00:00:00.000Z"));
		const updated = store.demoListSave({ id: "a", title: "A2", description: "", tools: [], created: a.created });
		assert.equal(updated.modified, "2026-03-03T00:00:00.000Z");
		assert.equal(updated.created, "2026-01-01T00:00:00.000Z");
		assert.equal(store.demoLists().length, 2);
		const fetched = store.demoListGet("a");
		assert.equal(fetched.title, "A2");
		assert.deepEqual(
			store.demoLists().map((l) => l.id),
			["b", "a"]
		);
	} finally {
		vi.useRealTimers();
	}
});

test("demoListDelete removes the matching list (string-coerced) and keeps the rest", () => {
	store.demoListSave({ id: 1, title: "One", description: "", tools: [] });
	store.demoListSave({ id: 2, title: "Two", description: "", tools: [] });
	store.demoListDelete("1");
	assert.deepEqual(
		store.demoLists().map((l) => l.id),
		[2]
	);
	store.demoListDelete(2);
	assert.deepEqual(store.demoLists(), []);
});

test("listToolToggle adds/removes a tool and returns false for unknown lists", () => {
	assert.equal(store.listToolToggle("ghost", "t"), false);
	store.demoListSave({ id: "L", title: "L", description: "", tools: ["keep"] });
	assert.equal(store.listToolToggle("L", "t1"), true);
	assert.deepEqual(store.demoListGet("L").tools, ["keep", "t1"]);
	assert.equal(store.listToolToggle("L", "keep"), false);
	assert.deepEqual(store.demoListGet("L").tools, ["t1"]);
});

test("storeMap and the typed map helpers default to {} and read stored objects", () => {
	assert.deepEqual(store.storeMap("toolEdits"), {});
	assert.deepEqual(store.toolEditsMap(), {});
	assert.deepEqual(store.toolAnnosMap(), {});
	assert.deepEqual(store.toolNewMap(), {});
	store.demoStore.set("toolEdits", { a: 1 });
	store.demoStore.set("toolAnnos", { b: 2 });
	store.demoStore.set("toolNew", { c: 3 });
	assert.deepEqual(store.toolEditsMap(), { a: 1 });
	assert.deepEqual(store.toolAnnosMap(), { b: 2 });
	assert.deepEqual(store.toolNewMap(), { c: 3 });
});

test("demoFeed prepends stored items only when signed in, then appends live", () => {
	store.demoStore.set("revisions", [{ d: 1 }]);
	// signed out (exp off) => only live, and missing live arg => []
	assert.deepEqual(store.demoFeed("revisions", [{ l: 1 }]), [{ l: 1 }]);
	assert.deepEqual(store.demoFeed("revisions"), []);
	// signed in => demo first, then live
	session.applyExp(true);
	session.setAuth(true);
	assert.deepEqual(store.demoFeed("revisions", [{ l: 1 }]), [{ d: 1 }, { l: 1 }]);
	assert.deepEqual(store.demoFeed("revisions"), [{ d: 1 }]);
	// signed in but key missing => the stored default is an empty array
	assert.deepEqual(store.demoFeed("neverset", [{ l: 1 }]), [{ l: 1 }]);
});

test("logActivity writes capped revision and audit-log rows", () => {
	vi.useFakeTimers();
	const rnd = vi.spyOn(Math, "random").mockReturnValue(0.5);
	try {
		vi.setSystemTime(new Date("2026-05-05T00:00:00.000Z"));
		store.logActivity("edited", "tool-x", "Tool X");
		const rev = store.demoStore.get("revisions");
		const aud = store.demoStore.get("auditlogs");
		const expectedId = `d${Date.parse("2026-05-05T00:00:00.000Z")}${Math.floor(0.5 * 1e3)}`;
		assert.equal(rev.length, 1);
		assert.equal(aud.length, 1);
		assert.deepEqual(rev[0], {
			id: expectedId,
			timestamp: "2026-05-05T00:00:00.000Z",
			user: { username: "Ada Lovelace" },
			comment: "Demo: edited",
			content_type: "tool",
			content_id: "tool-x",
			content_title: "Tool X",
			_demo: true
		});
		assert.deepEqual(aud[0], {
			id: expectedId,
			timestamp: "2026-05-05T00:00:00.000Z",
			user: { username: "Ada Lovelace" },
			action: "edited",
			target: { type: "tool", id: "tool-x", label: "Tool X" },
			_demo: true
		});
	} finally {
		rnd.mockRestore();
		vi.useRealTimers();
	}
});

test("logActivity caps both feeds at FEED_LOG_CAP, newest first", () => {
	const seedRev = Array.from({ length: 100 }, (_, i) => ({ id: `r${i}` }));
	const seedAud = Array.from({ length: 100 }, (_, i) => ({ id: `a${i}` }));
	store.demoStore.set("revisions", seedRev);
	store.demoStore.set("auditlogs", seedAud);
	store.logActivity("created", "tool-y", "Tool Y");
	const rev = store.demoStore.get("revisions");
	const aud = store.demoStore.get("auditlogs");
	assert.equal(rev.length, 100);
	assert.equal(aud.length, 100);
	assert.equal(rev[0].content_id, "tool-y");
	assert.equal(aud[0].action, "created");
	// the oldest seeded row (index 99 after unshift) is dropped
	assert.equal(
		rev.some((r) => r.id === "r99"),
		false
	);
	assert.equal(
		rev.some((r) => r.id === "r98"),
		true
	);
	assert.equal(
		aud.some((a) => a.id === "a99"),
		false
	);
});

test("demoRevisionsFor returns only matching, signed-in revisions", () => {
	session.applyExp(true);
	session.setAuth(true);
	store.logActivity("edited", "alpha", "Alpha");
	store.logActivity("edited", "beta", "Beta");
	assert.equal(store.demoRevisionsFor("alpha").length, 1);
	assert.equal(store.demoRevisionsFor("alpha")[0].content_id, "alpha");
	assert.deepEqual(store.demoRevisionsFor("missing"), []);
	// gated by signedIn
	session.applyExp(false);
	assert.deepEqual(store.demoRevisionsFor("alpha"), []);
});

test("crawlerUrls add/dedupe/delete", () => {
	assert.deepEqual(store.crawlerUrls(), []);
	store.crawlerUrlAdd("u1");
	assert.deepEqual(
		store.crawlerUrls().map((x) => x.url),
		["u1"]
	);
	assert.equal(typeof store.crawlerUrls()[0].added, "string");
	assert.equal(localStorage.getItem("thdemo:crawlerUrls") !== null, true);
	// duplicate is ignored
	store.crawlerUrlAdd("u1");
	assert.equal(store.crawlerUrls().length, 1);
	// new url is unshifted to the front
	store.crawlerUrlAdd("u2");
	assert.deepEqual(
		store.crawlerUrls().map((x) => x.url),
		["u2", "u1"]
	);
	store.crawlerUrlDelete("u1");
	assert.deepEqual(
		store.crawlerUrls().map((x) => x.url),
		["u2"]
	);
});

test("SAMPLE_TOOLINFO is the exact pretty-printed sample payload", () => {
	const expected = JSON.stringify(
		[
			{
				name: "demo-citation-helper",
				title: "Citation Helper",
				description: "Suggests reliable sources while you edit.",
				url: "https://example.org/citation-helper",
				tool_type: "web app",
				keywords: ["citations", "references"],
				for_wikis: ["*"],
				license: "MIT"
			},
			{
				name: "demo-stub-finder",
				title: "Stub Finder",
				description: "Finds short articles in a topic that need expansion.",
				url: "https://example.org/stub-finder",
				tool_type: "bot",
				keywords: ["stubs", "cleanup"],
				repository: "https://github.com/example/stub-finder"
			}
		],
		null,
		2
	);
	assert.equal(store.SAMPLE_TOOLINFO, expected);
});

test("ingestToolinfo reports invalid JSON", () => {
	const res = store.ingestToolinfo("{not json");
	assert.equal(typeof res.error, "string");
	assert.equal(res.error.startsWith("Invalid JSON: "), true);
	assert.equal(res.added, undefined);
	assert.equal(res.updated, undefined);
});

test("ingestToolinfo accepts a single object and maps defaults", () => {
	const res = store.ingestToolinfo(JSON.stringify({ name: "m1", title: "T", description: "D", url: "U" }));
	assert.deepEqual(res, { added: 1, updated: 0, errors: [] });
	assert.deepEqual(store.toolNewMap().m1, {
		title: "T",
		description: "D",
		url: "U",
		repository: null,
		license: null,
		toolType: null,
		keywords: [],
		forWikis: [],
		uiLanguages: [],
		deprecated: false,
		experimental: false,
		origin: "crawler"
	});
	assert.equal(localStorage.getItem("thdemo:toolNew") !== null, true);
});

test("ingestToolinfo maps every provided field for a full record", () => {
	store.ingestToolinfo(
		JSON.stringify({
			name: "m2",
			title: "T2",
			description: "D2",
			url: "U2",
			repository: "R",
			license: "L",
			tool_type: "bot",
			keywords: ["k"],
			for_wikis: ["w"],
			available_ui_languages: ["en"],
			deprecated: 1,
			experimental: true
		})
	);
	assert.deepEqual(store.toolNewMap().m2, {
		title: "T2",
		description: "D2",
		url: "U2",
		repository: "R",
		license: "L",
		toolType: "bot",
		keywords: ["k"],
		forWikis: ["w"],
		uiLanguages: ["en"],
		deprecated: true,
		experimental: true,
		origin: "crawler"
	});
});

test("ingestToolinfo validates each required field and indexes errors per item", () => {
	const res = store.ingestToolinfo(
		JSON.stringify([
			{ name: "ok", title: "T", description: "D", url: "U" },
			{ title: "T", description: "D", url: "U" }, // missing name -> Item 2
			{ name: "n", description: "D", url: "U" }, // missing title -> Item 3
			{ name: "n", title: "T", url: "U" }, // missing description -> Item 4
			{ name: "n", title: "T", description: "D" }, // missing url -> Item 5
			null // falsy item -> Item 6
		])
	);
	assert.equal(res.added, 1);
	assert.equal(res.updated, 0);
	assert.deepEqual(res.errors, [
		"Item 2: missing required name/title/description/url",
		"Item 3: missing required name/title/description/url",
		"Item 4: missing required name/title/description/url",
		"Item 5: missing required name/title/description/url",
		"Item 6: missing required name/title/description/url"
	]);
});

test("ingestToolinfo counts updates and logs create vs update activity", () => {
	const first = store.ingestToolinfo(JSON.stringify({ name: "dup", title: "T", description: "D", url: "U" }));
	assert.deepEqual(first, { added: 1, updated: 0, errors: [] });
	assert.equal(store.demoStore.get("revisions")[0].comment, "Demo: crawl-created");

	const second = store.ingestToolinfo(JSON.stringify({ name: "dup", title: "T2", description: "D2", url: "U2" }));
	assert.deepEqual(second, { added: 0, updated: 1, errors: [] });
	assert.equal(store.demoStore.get("revisions")[0].comment, "Demo: crawl-updated");
	assert.equal(store.toolNewMap().dup.title, "T2");
});

test("toCsv joins with ', ' and tolerates empty input", () => {
	assert.equal(store.toCsv(["a", "b", "c"]), "a, b, c");
	assert.equal(store.toCsv([]), "");
	assert.equal(store.toCsv(null), "");
	assert.equal(store.toCsv(undefined), "");
});

test("fromCsv splits, trims, and drops empties", () => {
	assert.deepEqual(store.fromCsv("a, b ,,c"), ["a", "b", "c"]);
	assert.deepEqual(store.fromCsv(" only "), ["only"]);
	assert.deepEqual(store.fromCsv(""), []);
	assert.deepEqual(store.fromCsv(null), []);
	assert.deepEqual(store.fromCsv(undefined), []);
});
