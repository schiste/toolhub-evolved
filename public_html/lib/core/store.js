// SPDX-License-Identifier: GPL-3.0-or-later
import { signedIn, USER } from "./session.js";

export const DEMO_KEYS = {
	favorites: "favorites",
	lists: "lists",
	toolEdits: "toolEdits",
	toolAnnos: "toolAnnos",
	toolNew: "toolNew",
	revisions: "revisions",
	auditlogs: "auditlogs",
	crawlerUrls: "crawlerUrls"
};
export const FEED_LOG_CAP = 100;
/* ===== Demo overlay store (Lane B) — localStorage only, namespaced. Holds the
   user-created delta (favorites, …) that overloads live data while experiments
   are on; never sent to Toolhub. Wiped by "Reset demo data". */
export const DEMO_NS = "thdemo:";
/**
 * @typedef {{ id: string, title: string, description: string, tools: string[], modified?: string, created?: string }} DemoList
 */
export const demoStore = {
	/**
	 * @param {string} k
	 * @param {any} [def]
	 * @returns {any}
	 */
	get(k, def) {
		try {
			const v = localStorage.getItem(DEMO_NS + k);
			return v === null ? def : JSON.parse(v);
		} catch {
			return def;
		}
	},
	/**
	 * @param {string} k
	 * @param {any} v
	 */
	set(k, v) {
		try {
			localStorage.setItem(DEMO_NS + k, JSON.stringify(v));
			return true;
		} catch {
			return false; // quota exceeded / storage disabled (e.g. private mode)
		}
	},
	/** @param {string} k */
	remove(k) {
		try {
			localStorage.removeItem(DEMO_NS + k);
			return true;
		} catch {
			return false;
		}
	},
	clearAll() {
		Object.keys(localStorage)
			.filter((k) => k.startsWith(DEMO_NS))
			.forEach((k) => localStorage.removeItem(k));
	}
};
const ABSENT = Symbol("absent");
// Run render() with the demo store temporarily overlaid with `fixture` (a map of
// DEMO_KEYS → value), restoring each key's prior value afterward. Lets previews
// (e.g. the styleguide) show stateful components without touching localStorage
// directly — keeping persistent storage confined to this core module.
/**
 * @template T
 * @param {Record<string, any>} fixture
 * @param {() => T} render
 * @returns {T}
 */
export function withDemoFixture(fixture, render) {
	const entries = Object.entries(fixture);
	const prior = entries.map(([k]) => [k, demoStore.get(k, ABSENT)]);
	try {
		for (const [k, v] of entries) demoStore.set(k, v);
		return render();
	} finally {
		for (const [k, v] of prior) {
			if (v === ABSENT) demoStore.remove(k);
			else demoStore.set(k, v);
		}
	}
}
// EXPERIMENTAL — favorites overlay. Needs: POST/DELETE /api/user/favorites/
// (Toolhub read-only API does not expose this). A set of tool names layered
// over the live catalog; the tool data itself is always the live record.
/** @returns {string[]} */
export function favNames() {
	return demoStore.get(DEMO_KEYS.favorites, []);
}
/** @param {string} name */
export function isFav(name) {
	return favNames().includes(name);
}
/** @param {string} name */
export function toggleFav(name) {
	const f = favNames(),
		i = f.indexOf(name);
	const willFavorite = i === -1;
	if (willFavorite) f.push(name);
	else f.splice(i, 1);
	// If the write failed (quota/private mode) nothing persisted, so report the
	// UNCHANGED state — the star must not show a favorite that wasn't stored.
	return demoStore.set(DEMO_KEYS.favorites, f) ? willFavorite : !willFavorite;
}
// EXPERIMENTAL — demo lists overlay. Needs: POST/PUT/DELETE /api/lists/.
// A demo list stores real tool NAMES; the tool data itself stays live.
/** @returns {DemoList[]} */
export function demoLists() {
	return demoStore.get(DEMO_KEYS.lists, []);
}
/**
 * @param {string} id
 * @returns {DemoList | null}
 */
export function demoListGet(id) {
	return demoLists().find((l) => String(l.id) === String(id)) || null;
}
/** @param {string} id */
export function isDemoListId(id) {
	return String(id).indexOf("demo-") === 0;
}
/** @returns {DemoList} */
export function demoListNew() {
	return {
		id: `demo-${Date.now().toString(36)}-${Math.floor(Math.random() * 1e4).toString(36)}`,
		title: "",
		description: "",
		tools: []
	};
}
/** @param {DemoList} list */
export function demoListSave(list) {
	const all = demoLists(),
		i = all.findIndex((l) => l.id === list.id);
	list.modified = new Date().toISOString();
	if (i === -1) {
		list.created = list.modified;
		all.unshift(list);
	} else {
		all[i] = list;
	}
	demoStore.set(DEMO_KEYS.lists, all);
	return list;
}
/** @param {string} id */
export function demoListDelete(id) {
	demoStore.set(
		DEMO_KEYS.lists,
		demoLists().filter((l) => String(l.id) !== String(id))
	);
}
// Toggle a tool's membership in a demo list; returns true if now present.
/**
 * @param {string} id
 * @param {string} name
 */
export function listToolToggle(id, name) {
	const l = demoListGet(id);
	if (!l) return false;
	const i = l.tools.indexOf(name);
	if (i === -1) l.tools.push(name);
	else l.tools.splice(i, 1);
	demoListSave(l);
	return i === -1;
}
/* ===== Tool overlays (Lane B) — edits / annotations / new submissions ======
   EXPERIMENTAL. Needs: POST /api/tools/, PUT /api/tools/{name}/,
   PUT /api/tools/{name}/annotations/. Edits & annotations are COMPACT-shaped
   overrides merged onto the live record by applyToolOverlay(); new submissions
   are full compact records that live only in the browser. */
/**
 * @param {string} key
 * @returns {Record<string, any>}
 */
export function storeMap(key) {
	return demoStore.get(key, {});
}
/**
 * @param {string} key
 * @param {any[]} [live]
 * @returns {any[]}
 */
export function demoFeed(key, live) {
	return [...(signedIn() ? demoStore.get(key, []) : []), ...(live || [])];
}
export const toolEditsMap = () => storeMap(DEMO_KEYS.toolEdits);
export const toolAnnosMap = () => storeMap(DEMO_KEYS.toolAnnos);
export const toolNewMap = () => storeMap(DEMO_KEYS.toolNew);
// Append local revision + audit-log rows so feeds/history reflect demo edits.
/**
 * @param {string} action
 * @param {string} name
 * @param {string} title
 */
export function logActivity(action, name, title) {
	const ts = new Date().toISOString(),
		id = `d${Date.now()}${Math.floor(Math.random() * 1e3)}`;
	const rev = demoStore.get(DEMO_KEYS.revisions, []);
	rev.unshift({
		id,
		timestamp: ts,
		user: { username: USER.name },
		comment: `Demo: ${action}`,
		content_type: "tool",
		content_id: name,
		content_title: title,
		_demo: true
	});
	demoStore.set(DEMO_KEYS.revisions, rev.slice(0, FEED_LOG_CAP));
	const aud = demoStore.get(DEMO_KEYS.auditlogs, []);
	aud.unshift({
		id,
		timestamp: ts,
		user: { username: USER.name },
		action,
		target: { type: "tool", id: name, label: title },
		_demo: true
	});
	demoStore.set(DEMO_KEYS.auditlogs, aud.slice(0, FEED_LOG_CAP));
}
/** @param {string} name */
export function demoRevisionsFor(name) {
	// Stryker disable next-line ArrayDeclaration — the live arg is immediately filtered by `content_id === name`; any injected element lacks content_id and is dropped, so a non-empty default produces identical output: equivalent.
	return demoFeed(DEMO_KEYS.revisions, []).filter((r) => r.content_id === name);
}
// EXPERIMENTAL — crawler simulation. Needs: server-side crawler (the browser
// can't fetch arbitrary toolinfo.json — CORS). URLs are just recorded; actual
// ingestion is simulated from pasted/sample JSON.
/** @returns {Array<{ url: string, added: string }>} */
export function crawlerUrls() {
	return demoStore.get(DEMO_KEYS.crawlerUrls, []);
}
/** @param {string} url */
export function crawlerUrlAdd(url) {
	const a = crawlerUrls();
	if (!a.some((x) => x.url === url)) {
		a.unshift({ url, added: new Date().toISOString() });
		demoStore.set(DEMO_KEYS.crawlerUrls, a);
	}
}
/** @param {string} url */
export function crawlerUrlDelete(url) {
	demoStore.set(
		DEMO_KEYS.crawlerUrls,
		crawlerUrls().filter((x) => x.url !== url)
	);
}
export const SAMPLE_TOOLINFO = JSON.stringify(
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
// Ingest one toolinfo object or an array, upserting demo records (origin=crawler).
/** @param {string} text */
export function ingestToolinfo(text) {
	let data;
	try {
		data = JSON.parse(text);
	} catch (e) {
		return { error: `Invalid JSON: ${/** @type {Error} */ (e).message}` };
	}
	const items = Array.isArray(data) ? data : [data];
	const m = toolNewMap();
	let added = 0,
		updated = 0;
	/** @type {string[]} */
	const errors = [];
	items.forEach((it, i) => {
		if (!it || !it.name || !it.title || !it.description || !it.url) {
			errors.push(`Item ${i + 1}: missing required name/title/description/url`);
			return;
		}
		const existed = Boolean(m[it.name]);
		m[it.name] = {
			title: it.title,
			description: it.description,
			url: it.url,
			repository: it.repository || null,
			license: it.license || null,
			toolType: it.tool_type || null,
			keywords: it.keywords || [],
			forWikis: it.for_wikis || [],
			uiLanguages: it.available_ui_languages || [],
			deprecated: Boolean(it.deprecated),
			experimental: Boolean(it.experimental),
			origin: "crawler"
		};
		if (existed) updated++;
		else added++;
		logActivity(existed ? "crawl-updated" : "crawl-created", it.name, it.title);
	});
	demoStore.set(DEMO_KEYS.toolNew, m);
	return { added, updated, errors };
}
// CSV helpers for array form fields.
/** @param {string[] | null | undefined} a */
export function toCsv(a) {
	return (a || []).join(", ");
}
/** @param {unknown} s */
export function fromCsv(s) {
	return String(s || "")
		.split(",")
		.map((x) => x.trim())
		.filter(Boolean);
}
