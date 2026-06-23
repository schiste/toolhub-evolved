// SPDX-License-Identifier: GPL-3.0-or-later
import { signedIn, USER } from "./session.js";

export const DEMO_KEYS = { favorites: "favorites", lists: "lists", toolEdits: "toolEdits", toolAnnos: "toolAnnos", toolNew: "toolNew", revisions: "revisions", auditlogs: "auditlogs", crawlerUrls: "crawlerUrls" };
export const FEED_LOG_CAP = 100;
/* ===== Demo overlay store (Lane B) — localStorage only, namespaced. Holds the
   user-created delta (favorites, …) that overloads live data while experiments
   are on; never sent to Toolhub. Wiped by "Reset demo data". */
export const DEMO_NS = "thdemo:";
export const demoStore = {
	get(k, def) { try { const v = localStorage.getItem(DEMO_NS + k); return v == null ? def : JSON.parse(v); } catch (e) { return def; } },
	set(k, v) { try { localStorage.setItem(DEMO_NS + k, JSON.stringify(v)); } catch (e) {} },
	clearAll() { Object.keys(localStorage).filter((k) => k.indexOf(DEMO_NS) === 0).forEach((k) => localStorage.removeItem(k)); },
};
// EXPERIMENTAL — favorites overlay. Needs: POST/DELETE /api/user/favorites/
// (Toolhub read-only API does not expose this). A set of tool names layered
// over the live catalog; the tool data itself is always the live record.
export function favNames() { return demoStore.get(DEMO_KEYS.favorites, []); }
export function isFav(name) { return favNames().indexOf(name) !== -1; }
export function toggleFav(name) {
	const f = favNames(), i = f.indexOf(name);
	if (i === -1) f.push(name); else f.splice(i, 1);
	demoStore.set(DEMO_KEYS.favorites, f);
	return i === -1; // true => now favorited
}
// EXPERIMENTAL — demo lists overlay. Needs: POST/PUT/DELETE /api/lists/.
// A demo list stores real tool NAMES; the tool data itself stays live.
export function demoLists() { return demoStore.get(DEMO_KEYS.lists, []); }
export function demoListGet(id) { return demoLists().find((l) => String(l.id) === String(id)) || null; }
export function isDemoListId(id) { return String(id).indexOf("demo-") === 0; }
export function demoListNew() { return { id: "demo-" + Date.now().toString(36) + "-" + Math.floor(Math.random() * 1e4).toString(36), title: "", description: "", tools: [] }; }
export function demoListSave(list) {
	const all = demoLists(), i = all.findIndex((l) => l.id === list.id);
	list.modified = new Date().toISOString();
	if (i === -1) { list.created = list.modified; all.unshift(list); } else all[i] = list;
	demoStore.set(DEMO_KEYS.lists, all);
	return list;
}
export function demoListDelete(id) { demoStore.set(DEMO_KEYS.lists, demoLists().filter((l) => String(l.id) !== String(id))); }
// Toggle a tool's membership in a demo list; returns true if now present.
export function listToolToggle(id, name) {
	const l = demoListGet(id); if (!l) return false;
	const i = l.tools.indexOf(name);
	if (i === -1) l.tools.push(name); else l.tools.splice(i, 1);
	demoListSave(l); return i === -1;
}
/* ===== Tool overlays (Lane B) — edits / annotations / new submissions ======
   EXPERIMENTAL. Needs: POST /api/tools/, PUT /api/tools/{name}/,
   PUT /api/tools/{name}/annotations/. Edits & annotations are COMPACT-shaped
   overrides merged onto the live record by applyToolOverlay(); new submissions
   are full compact records that live only in the browser. */
export function storeMap(key) { return demoStore.get(key, {}); }
export function demoFeed(key, live) { return (signedIn() ? demoStore.get(key, []) : []).concat(live || []); }
export const toolEditsMap = () => storeMap(DEMO_KEYS.toolEdits);
export const toolAnnosMap = () => storeMap(DEMO_KEYS.toolAnnos);
export const toolNewMap = () => storeMap(DEMO_KEYS.toolNew);
// Append local revision + audit-log rows so feeds/history reflect demo edits.
export function logActivity(action, name, title) {
	const ts = new Date().toISOString(), id = "d" + Date.now() + Math.floor(Math.random() * 1e3);
	const rev = demoStore.get(DEMO_KEYS.revisions, []);
	rev.unshift({ id, timestamp: ts, user: { username: USER.name }, comment: "Demo: " + action, content_type: "tool", content_id: name, content_title: title, _demo: true });
	demoStore.set(DEMO_KEYS.revisions, rev.slice(0, FEED_LOG_CAP));
	const aud = demoStore.get(DEMO_KEYS.auditlogs, []);
	aud.unshift({ id, timestamp: ts, user: { username: USER.name }, action, target: { type: "tool", id: name, label: title }, _demo: true });
	demoStore.set(DEMO_KEYS.auditlogs, aud.slice(0, FEED_LOG_CAP));
}
export function demoRevisionsFor(name) { return demoFeed(DEMO_KEYS.revisions, []).filter((r) => r.content_id === name); }
// EXPERIMENTAL — crawler simulation. Needs: server-side crawler (the browser
// can't fetch arbitrary toolinfo.json — CORS). URLs are just recorded; actual
// ingestion is simulated from pasted/sample JSON.
export function crawlerUrls() { return demoStore.get(DEMO_KEYS.crawlerUrls, []); }
export function crawlerUrlAdd(url) {
	const a = crawlerUrls();
	if (!a.some((x) => x.url === url)) { a.unshift({ url, added: new Date().toISOString() }); demoStore.set(DEMO_KEYS.crawlerUrls, a); }
}
export function crawlerUrlDelete(url) { demoStore.set(DEMO_KEYS.crawlerUrls, crawlerUrls().filter((x) => x.url !== url)); }
export const SAMPLE_TOOLINFO = JSON.stringify([
	{ name: "demo-citation-helper", title: "Citation Helper", description: "Suggests reliable sources while you edit.", url: "https://example.org/citation-helper", tool_type: "web app", keywords: ["citations", "references"], for_wikis: ["*"], license: "MIT" },
	{ name: "demo-stub-finder", title: "Stub Finder", description: "Finds short articles in a topic that need expansion.", url: "https://example.org/stub-finder", tool_type: "bot", keywords: ["stubs", "cleanup"], repository: "https://github.com/example/stub-finder" },
], null, 2);
// Ingest one toolinfo object or an array, upserting demo records (origin=crawler).
export function ingestToolinfo(text) {
	let data;
	try { data = JSON.parse(text); } catch (e) { return { error: "Invalid JSON: " + e.message }; }
	const items = Array.isArray(data) ? data : [data];
	const m = toolNewMap(); let added = 0, updated = 0; const errors = [];
	items.forEach((it, i) => {
		if (!it || !it.name || !it.title || !it.description || !it.url) { errors.push("Item " + (i + 1) + ": missing required name/title/description/url"); return; }
		const existed = !!m[it.name];
		m[it.name] = {
			title: it.title, description: it.description, url: it.url,
			repository: it.repository || null, license: it.license || null, toolType: it.tool_type || null,
			keywords: it.keywords || [], forWikis: it.for_wikis || [],
			deprecated: !!it.deprecated, experimental: !!it.experimental, origin: "crawler",
		};
		if (existed) updated++; else added++;
		logActivity(existed ? "crawl-updated" : "crawl-created", it.name, it.title);
	});
	demoStore.set(DEMO_KEYS.toolNew, m);
	return { added, updated, errors };
}
// CSV helpers for array form fields.
export function toCsv(a) { return (a || []).join(", "); }
export function fromCsv(s) { return String(s || "").split(",").map((x) => x.trim()).filter(Boolean); }
