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
export const SYNC_STATUS = {
	official: "official",
	localDraft: "local_draft",
	localFallback: "local_fallback",
	evolvedReal: "evolved_real",
	syncError: "sync_error"
};
export const SOURCE = {
	official: "official",
	local: "local"
};
/* ===== Evolved overlay store — localStorage cache, namespaced. Holds the
   user-created delta (favorites, lists, drafts, annotations) layered onto live
   data while Evolved features are on. With a real session these keys sync to
   Evolved's backend; supported flows may also publish to official Toolhub via
   /v1/toolhub/* first. */
export const DEMO_NS = "thdemo:";
/* ---- Server write-through hook (production sync) ------------------------
   When a real session exists, serversync.js registers a handler here and every
   overlay mutation is pushed to the backend as well — localStorage becomes a
   synchronous cache of the server copy. With no handler (logged out / local
   dev), write routes stay gated by Toolhub sign-in. */
/** @type {((key: string, value: any) => void) | null} */
let storeSync = null;
let syncMuted = false;
/** @param {unknown} fn */
export function setStoreSync(fn) {
	storeSync = typeof fn === "function" ? /** @type {(key: string, value: any) => void} */ (fn) : null;
}
/**
 * Run `run` without pushing mutations to the server (fixture previews, and the
 * initial pull that writes the server copy into the cache).
 * @template T
 * @param {() => T} run
 * @returns {T}
 */
export function withSyncMuted(run) {
	syncMuted = true;
	try {
		return run();
	} finally {
		syncMuted = false;
	}
}
/**
 * @typedef {{ source?: string, syncStatus?: string, syncLabel?: string, lastSyncedAt?: string, lastError?: string, createdByUserId?: number, deletedAt?: string, officialId?: number, officialName?: string, visibility?: string, toolhubResponse?: Record<string, any> | null, validationErrors?: any[], baseRevision?: string, fieldStatuses?: Record<string, string>, reviewStatus?: string }} SyncMeta
 * @typedef {{ id: string, title: string, description: string, tools: string[], modified?: string, created?: string } & SyncMeta} DemoList
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
		} catch {
			return false; // quota exceeded / storage disabled (e.g. private mode)
		}
		if (storeSync && !syncMuted) storeSync(k, v); // write-through to the server copy
		return true;
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
		withSyncMuted(() => {
			for (const [k, v] of entries) demoStore.set(k, v);
		});
		return render();
	} finally {
		withSyncMuted(() => {
			for (const [k, v] of prior) {
				if (v === ABSENT) demoStore.remove(k);
				else demoStore.set(k, v);
			}
		});
	}
}
/**
 * @param {string | null | undefined} status
 * @returns {string}
 */
export function syncStatusLabel(status) {
	return (
		{
			[SYNC_STATUS.official]: "Official Toolhub",
			[SYNC_STATUS.localDraft]: "Local draft",
			[SYNC_STATUS.localFallback]: "Local fallback",
			[SYNC_STATUS.evolvedReal]: "Evolved data",
			[SYNC_STATUS.syncError]: "Sync error"
		}[String(status || "")] || "Local draft"
	);
}
/**
 * @template {Record<string, any>} T
 * @param {T} item
 * @param {Partial<SyncMeta>} [meta]
 * @returns {T}
 */
export function stampSyncMeta(item, meta = {}) {
	const out = /** @type {T & SyncMeta & { id?: unknown }} */ (item);
	const idCandidate = meta.officialId ?? out.officialId ?? (typeof out.id === "number" ? out.id : undefined);
	const officialId = typeof idCandidate === "number" && Number.isFinite(idCandidate) ? idCandidate : undefined;
	if (meta.source) out.source = meta.source;
	if (!out.source) out.source = officialId ? SOURCE.official : SOURCE.local;
	if (meta.syncStatus) out.syncStatus = meta.syncStatus;
	if (!out.syncStatus) out.syncStatus = officialId ? SYNC_STATUS.official : SYNC_STATUS.localDraft;
	if (meta.lastError !== undefined) out.lastError = meta.lastError;
	if (meta.lastSyncedAt !== undefined) out.lastSyncedAt = meta.lastSyncedAt;
	if (meta.createdByUserId !== undefined) out.createdByUserId = meta.createdByUserId;
	if (meta.deletedAt !== undefined) out.deletedAt = meta.deletedAt;
	if (meta.officialId !== undefined) out.officialId = meta.officialId;
	if (meta.officialName !== undefined) out.officialName = meta.officialName;
	if (meta.visibility !== undefined) out.visibility = meta.visibility;
	if (meta.toolhubResponse !== undefined) out.toolhubResponse = meta.toolhubResponse;
	if (meta.validationErrors !== undefined) out.validationErrors = meta.validationErrors;
	if (meta.baseRevision !== undefined) out.baseRevision = meta.baseRevision;
	if (meta.fieldStatuses !== undefined) out.fieldStatuses = meta.fieldStatuses;
	if (meta.reviewStatus !== undefined) out.reviewStatus = meta.reviewStatus;
	if (out.syncStatus === SYNC_STATUS.official && !out.lastSyncedAt) out.lastSyncedAt = new Date().toISOString();
	out.syncLabel = syncStatusLabel(out.syncStatus);
	return out;
}
// Favorites overlay. Signed-in UI attempts POST/DELETE /api/user/favorites/
// through the backend bridge; this local set keeps the UI responsive.
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
// List overlay. Official list writes go through Toolhub where possible; local
// draft lists store real tool names while the tool data itself stays live.
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
	return String(id).startsWith("demo-");
}
/** @returns {DemoList} */
export function demoListNew() {
	return stampSyncMeta({
		id: `demo-${Date.now().toString(36)}-${Math.floor(Math.random() * 1e4).toString(36)}`,
		title: "",
		description: "",
		tools: []
	});
}
/**
 * @param {DemoList} list
 * @param {Partial<SyncMeta>} [meta]
 */
export function demoListSave(list, meta = {}) {
	const all = demoLists(),
		i = all.findIndex((l) => l.id === list.id);
	list.modified = new Date().toISOString();
	stampSyncMeta(list, meta);
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
// Toggle a tool's membership in a local Evolved list; returns true if now present.
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
/* ===== Tool overlays — edits / annotations / new submissions ===============
   Official writes are attempted through /v1/toolhub/* when signed in. These
   COMPACT-shaped records remain the local Evolved draft/fallback layer merged
   onto live Toolhub data by applyToolOverlay(). */
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
// Append local revision + audit-log rows so feeds/history reflect Evolved edits.
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
		comment: `Evolved: ${action}`,
		content_type: "tool",
		content_id: name,
		content_title: title,
		_evolved: true
	});
	demoStore.set(DEMO_KEYS.revisions, rev.slice(0, FEED_LOG_CAP));
	const aud = demoStore.get(DEMO_KEYS.auditlogs, []);
	aud.unshift({
		id,
		timestamp: ts,
		user: { username: USER.name },
		action,
		target: { type: "tool", id: name, label: title },
		_evolved: true
	});
	demoStore.set(DEMO_KEYS.auditlogs, aud.slice(0, FEED_LOG_CAP));
}
/** @param {string} name */
export function demoRevisionsFor(name) {
	// Stryker disable next-line ArrayDeclaration — the live arg is immediately filtered by `content_id === name`; any injected element lacks content_id and is dropped, so a non-empty default produces identical output: equivalent.
	return demoFeed(DEMO_KEYS.revisions, []).filter((r) => r.content_id === name);
}
// Evolved crawler registration cache. Official URL writes go to Toolhub first;
// local URLs and pasted Toolinfo are stored in Evolved.
/** @returns {Array<{ url: string, added: string, id?: number, officialId?: number } & SyncMeta>} */
export function crawlerUrls() {
	return demoStore.get(DEMO_KEYS.crawlerUrls, []);
}
/**
 * @param {string} url
 * @param {number | undefined} [id]
 * @param {Partial<SyncMeta>} [meta]
 */
export function crawlerUrlAdd(url, id, meta = {}) {
	const a = crawlerUrls();
	const existing = a.find((x) => x.url === url);
	const nextMeta =
		id === undefined
			? meta
			: { source: SOURCE.official, syncStatus: SYNC_STATUS.official, officialId: id, ...meta };
	if (existing) {
		if (id !== undefined) {
			existing.id = id;
			existing.officialId = id;
		}
		stampSyncMeta(existing, nextMeta);
		demoStore.set(DEMO_KEYS.crawlerUrls, a);
	} else {
		const row = stampSyncMeta({ url, id, officialId: id, added: new Date().toISOString() }, nextMeta);
		a.unshift(row);
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
// Ingest one toolinfo object or an array, upserting Evolved records (origin=crawler).
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
		m[it.name] = stampSyncMeta(
			{
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
				origin: "crawler",
				visibility: "public"
			},
			{ source: SOURCE.local, syncStatus: SYNC_STATUS.evolvedReal }
		);
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
