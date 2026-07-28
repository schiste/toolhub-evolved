// SPDX-License-Identifier: GPL-3.0-or-later
import { localizedField, t } from "./i18n.js";
import { markFrontendTiming, markFrontendTimingOnce } from "./diagnostics.js";
import { signedIn, USER } from "./session.js";
import {
	publicApiCacheClear,
	publicApiCacheLoad,
	publicApiCacheSave,
	recentOwnerCacheDelete,
	toolEditsMap,
	toolAnnosMap,
	toolNewMap
} from "./store.js";

/* Tool cache for O(1) detail / quick-view lookups; filled by normalizeTool()
   as live data arrives (search results, lists, tool pages). No snapshot. */
/** @type {Record<string, Tool>} */
export const INDEX = {};
const OVERLAY_META_KEYS = new Set([
	"source",
	"syncStatus",
	"syncLabel",
	"lastSyncedAt",
	"lastError",
	"createdByUserId",
	"created_by_user_id",
	"deletedAt",
	"deleted_at",
	"officialId",
	"officialName",
	"visibility",
	"toolhubResponse",
	"validationErrors",
	"baseRevision",
	"fieldStatuses",
	"reviewStatus"
]);
const CANONICAL_TOOL_KEYS = new Set(["name", "origin"]);

/**
 * @param {Record<string, any>} patch
 * @returns {Record<string, any>}
 */
function dataPatch(patch) {
	return Object.fromEntries(
		Object.entries(patch || {}).filter(([key]) => !OVERLAY_META_KEYS.has(key) && !CANONICAL_TOOL_KEYS.has(key))
	);
}

/** @param {string} name */
export function isNewTool(name) {
	return Boolean(toolNewMap()[name]);
}
/**
 * @param {Tool} o
 * @returns {Tool}
 */
export function applyToolOverlay(o) {
	const e = toolEditsMap()[o.name];
	if (e) {
		Object.assign(o, dataPatch(e));
		// `edited`/`annotated`/`status` (object) are runtime extras the static
		// Tool interface doesn't model; cast through any for these writes.
		/** @type {any} */ (o).edited = true;
		/** @type {any} */ (o).editSyncStatus = e.syncStatus;
		/** @type {any} */ (o).editLastError = e.lastError;
		/** @type {any} */ (o).editValidationErrors = e.validationErrors;
		/** @type {any} */ (o).editReviewStatus = e.reviewStatus;
		/** @type {any} */ (o).editLastSyncedAt = e.lastSyncedAt;
	}
	const a = toolAnnosMap()[o.name];
	if (a) {
		Object.assign(o, dataPatch(a));
		/** @type {any} */ (o).annotated = true;
		/** @type {any} */ (o).annotationSyncStatus = a.syncStatus;
		/** @type {any} */ (o).annotationLastError = a.lastError;
		/** @type {any} */ (o).annotationValidationErrors = a.validationErrors;
		/** @type {any} */ (o).annotationReviewStatus = a.reviewStatus;
		/** @type {any} */ (o).annotationLastSyncedAt = a.lastSyncedAt;
	}
	if (e || a) o.status = /** @type {any} */ (statusOf(o)); // flags may have changed
	return o;
}
// Build a compact tool object from a locally-registered record (the project
// database that complements the live catalog), then overlay edits.
/**
 * @param {string} name
 * @param {Record<string, any>} rec
 * @returns {Tool}
 */
export function localToolBase(name, rec) {
	// The defaults + record spread produce a structurally-complete compact tool;
	// assert the Tool shape once here (same trust boundary as normalizeTool).
	const o = /** @type {Tool} */ (
		/** @type {unknown} */ (
			Object.assign(
				{
					name,
					keywords: [],
					authors: [],
					audiences: [],
					tasks: [],
					forWikis: [],
					uiLanguages: [],
					technologyUsed: [],
					maintainer: USER.name,
					deprecated: false,
					experimental: false,
					origin: "api"
				},
				rec
			)
		)
	);
	o.name = name;
	o.weeklyViews = 0;
	o.status = statusOf(o);
	INDEX[name] = o;
	return applyToolOverlay(o);
}
// Net-new submission from this browser's overlay cache.
/**
 * @param {string} name
 * @returns {Tool | null}
 */
export function newToolBase(name) {
	const rec = toolNewMap()[name];
	return rec ? localToolBase(name, rec) : null;
}
/**
 * @param {{ deprecated: boolean; experimental: boolean }} t
 * @returns {ToolStatus}
 */
export function statusOf(t) {
	return t.deprecated
		? { level: "red", label: "Deprecated" }
		: t.experimental
			? { level: "yellow", label: "Experimental" }
			: { level: "green", label: "Healthy" };
}
/* ===================================================================== LIVE API
   Every read goes through the same-origin proxy (/api → toolhub.wikimedia.org/api).
   Tool/list objects are normalized to the compact shape the views/cards expect.
   There is no bundled snapshot — the catalog is always the live one. */
export const API_BASE = "/api";
/* Stale-while-revalidate cache for anonymous Toolhub GET reads. Keyed by full
   same-origin /api URL. Hot entries live in memory; a bounded public-data copy
   also lives in localStorage so hard refreshes can render useful content before
   the live API refresh finishes. /v1 session, OAuth, overlay, and write calls use
   the backend* helpers below and never enter this cache. */
const API_RECENT_TTL_MS = 30 * 1000;
const API_SEARCH_TTL_MS = 2 * 60 * 1000;
const API_DETAIL_TTL_MS = 15 * 60 * 1000;
const API_CONFIG_TTL_MS = 24 * 60 * 60 * 1000;
const API_DEFAULT_TTL_MS = 60 * 1000;
const API_STALE_IF_ERROR_MS = 24 * 60 * 60 * 1000;
const API_STORAGE_MAX_ENTRIES = 48;
const API_STORAGE_MAX_CHARS = 240000;
const API_PERSISTENT_MAX_AGE_MS = API_CONFIG_TTL_MS + API_STALE_IF_ERROR_MS;
const SERVER_CACHE_HEADER = "X-Toolhub-Evolved-Cache";
const SERVER_STALE_CACHE = "stale";
const SERVER_STALE_FOLLOWUP_MS = 1200;
const apiCache = new Map(); // url -> { data, ts }
const apiInflight = new Map(); // url -> Promise<data>
/** @type {Map<string, ReturnType<typeof setTimeout>>} */
const apiServerStaleFollowups = new Map();
let apiCacheLoaded = false;
const DETAIL_COLLECTIONS = new Set(["tools", "lists"]);
const TOOL_AGGREGATE_PATHS = new Set(["/api/search/tools/", "/api/ui/home/"]);
const LIST_COLLECTION_PATH = "/api/lists/";
const RECENT_COLLECTION_PATH = "/api/recent/";
const CONFIG_PATHS = new Set([
	"/api/",
	"/api/schema/",
	"/api/audiences/",
	"/api/content-types/",
	"/api/licenses/",
	"/api/origins/",
	"/api/tasks/",
	"/api/tool-types/",
	"/api/technology-used/",
	"/api/wikis/"
]);
// Transient failures — a network blip (e.g. ERR_NETWORK_CHANGED on a WiFi/VPN
// switch) or a momentary 5xx (e.g. the webservice restarting on deploy) — would
// otherwise leave the SPA with no data. Retry those a few times with backoff so
// a hiccup self-heals; fail fast on real client errors (4xx).
const RETRYABLE_STATUS = new Set([502, 503, 504]);
const API_RETRIES = 3;
/** @param {number} ms */
function sleep(ms) {
	return new Promise((resolve) => {
		setTimeout(resolve, ms);
	});
}
/** @param {string} url */
function apiPath(url) {
	const path = new URL(url, "https://toolhub-evolved.local").pathname;
	return path.endsWith("/") ? path : `${path}/`;
}
/** @param {string} url */
function apiPathParts(url) {
	return apiPath(url)
		.split("/")
		.filter(Boolean)
		.map((part) => decodeURIComponent(part));
}
/** @param {string} path */
function isDetailPath(path) {
	const parts = path.replaceAll(/^\/+|\/+$/g, "").split("/");
	return parts.length === 3 && parts[0] === "api" && DETAIL_COLLECTIONS.has(parts[1]) && Boolean(parts[2]);
}
/**
 * @param {unknown} value
 * @returns {string | null}
 */
function cleanCacheId(value) {
	if (value === null || value === undefined) return null;
	const text = String(value).trim();
	return text || null;
}
/**
 * @param {any} object
 * @param {...string} keys
 * @returns {string | null}
 */
function objectStringValue(object, ...keys) {
	if (!object || typeof object !== "object") return null;
	for (const key of keys) {
		const value = cleanCacheId(object[key]);
		if (value) return value;
	}
	return null;
}
/**
 * @param {string} url
 * @param {Set<string>} toolNames
 */
function matchesToolCache(url, toolNames) {
	const path = apiPath(url);
	if (path === RECENT_COLLECTION_PATH || TOOL_AGGREGATE_PATHS.has(path)) return toolNames.size > 0;
	const parts = apiPathParts(url);
	return parts.length >= 3 && parts[0] === "api" && parts[1] === "tools" && toolNames.has(parts[2]);
}
/**
 * @param {string} url
 * @param {Set<string>} listIds
 */
function matchesListCache(url, listIds) {
	const path = apiPath(url);
	if (path === RECENT_COLLECTION_PATH || path === LIST_COLLECTION_PATH) return listIds.size > 0;
	const parts = apiPathParts(url);
	return parts.length >= 3 && parts[0] === "api" && parts[1] === "lists" && listIds.has(parts[2]);
}
/** @param {(url: string) => boolean} predicate */
function invalidateApiCacheWhere(predicate) {
	loadPersistentApiCache();
	let removed = 0;
	for (const url of apiCache.keys()) {
		if (predicate(url)) {
			apiCache.delete(url);
			removed += 1;
		}
	}
	for (const url of apiInflight.keys()) {
		if (predicate(url)) apiInflight.delete(url);
	}
	if (removed > 0) persistApiCache();
	return removed;
}
/**
 * @param {string} url
 * @returns {{ freshMs: number, staleIfErrorMs: number }}
 */
export function apiCachePolicy(url) {
	const path = apiPath(url);
	if (path === "/api/recent/") return { freshMs: API_RECENT_TTL_MS, staleIfErrorMs: API_STALE_IF_ERROR_MS };
	if (path === "/api/search/tools/") return { freshMs: API_SEARCH_TTL_MS, staleIfErrorMs: API_STALE_IF_ERROR_MS };
	if (isDetailPath(path)) return { freshMs: API_DETAIL_TTL_MS, staleIfErrorMs: API_STALE_IF_ERROR_MS };
	if (CONFIG_PATHS.has(path)) return { freshMs: API_CONFIG_TTL_MS, staleIfErrorMs: API_STALE_IF_ERROR_MS };
	return { freshMs: API_DEFAULT_TTL_MS, staleIfErrorMs: API_STALE_IF_ERROR_MS };
}
/** @param {string} url @param {string} state @param {unknown} [error] */
function emitApiCacheRefresh(url, state, error) {
	if (typeof document === "undefined" || typeof CustomEvent === "undefined") return;
	document.dispatchEvent(new CustomEvent("toolhub:api-cache-refresh", { detail: { url, state, error } }));
}
/** @param {any} res @param {string} name */
function responseHeader(res, name) {
	return typeof res?.headers?.get === "function" ? res.headers.get(name) || "" : "";
}
/** @param {string} url */
function scheduleServerStaleFollowup(url) {
	if (apiServerStaleFollowups.has(url)) return;
	const timer = setTimeout(() => {
		apiServerStaleFollowups.delete(url);
		apiFetch(url, { background: true }).catch(() => {});
	}, SERVER_STALE_FOLLOWUP_MS);
	apiServerStaleFollowups.set(url, timer);
}
function loadPersistentApiCache() {
	if (apiCacheLoaded) return;
	apiCacheLoaded = true;
	try {
		const now = Date.now();
		for (const [url, entry] of publicApiCacheLoad(API_PERSISTENT_MAX_AGE_MS)) {
			const policy = apiCachePolicy(url);
			if (now - entry.ts > policy.freshMs + policy.staleIfErrorMs) continue;
			apiCache.set(url, { data: entry.data, ts: entry.ts });
		}
	} catch {
		return;
	}
}
function persistApiCache() {
	try {
		const entries = [...apiCache.entries()]
			.filter(([url, entry]) => {
				if (!url.startsWith(API_BASE)) return false;
				const policy = apiCachePolicy(url);
				return Date.now() - entry.ts <= policy.freshMs + policy.staleIfErrorMs;
			})
			.sort((a, b) => b[1].ts - a[1].ts)
			.slice(0, API_STORAGE_MAX_ENTRIES)
			.filter(([, entry]) => JSON.stringify(entry.data).length <= API_STORAGE_MAX_CHARS);
		publicApiCacheSave(entries);
	} catch {
		return;
	}
}
/**
 * An HTTP-level API failure carrying the upstream status, so callers can tell a
 * genuine 404 (resource absent) from a transient outage (5xx / network) and
 * react differently — e.g. show "not found" vs. propagate to the error boundary.
 */
export class ApiError extends Error {
	/**
	 * @param {number} status
	 * @param {string} url
	 */
	constructor(status, url) {
		super(`API ${status} ${url}`); // message kept stable: tests/log scrapers match it
		this.name = "ApiError";
		this.status = status;
	}
}
/**
 * @param {string} url
 * @param {number} [attempts]
 * @returns {Promise<{ data: any, serverCache: string }>}
 */
async function fetchJson(url, attempts = API_RETRIES) {
	let lastError;
	for (let attempt = 1; attempt <= attempts; attempt += 1) {
		let res;
		try {
			res = await fetch(url, { headers: { Accept: "application/json" } });
			markFrontendTimingOnce("first-api-response", {
				url,
				status: res.status,
				cache: responseHeader(res, SERVER_CACHE_HEADER)
			});
		} catch (error) {
			lastError = error; // network-layer failure → retry
			if (attempt >= attempts) throw error;
			await sleep(200 * 2 ** (attempt - 1));
			continue;
		}
		if (res.ok) return { data: await res.json(), serverCache: responseHeader(res, SERVER_CACHE_HEADER) };
		if (!RETRYABLE_STATUS.has(res.status) || attempt >= attempts) throw new ApiError(res.status, url);
		await sleep(200 * 2 ** (attempt - 1));
	}
	throw lastError;
}
/**
 * @param {string} url
 * @param {{ background?: boolean }} [options]
 */
function apiFetch(url, options = {}) {
	if (apiInflight.has(url)) return apiInflight.get(url);
	if (options.background) emitApiCacheRefresh(url, "start");
	const p = fetchJson(url)
		.then(({ data, serverCache }) => {
			const serverStale = serverCache === SERVER_STALE_CACHE;
			const policy = apiCachePolicy(url);
			const ts = serverStale ? Date.now() - policy.freshMs : Date.now();
			apiCache.set(url, { data, ts });
			persistApiCache();
			if (serverStale) {
				markFrontendTiming("stale-cache-served", { url, source: "server" });
				emitApiCacheRefresh(url, "server-background");
				if (!options.background) scheduleServerStaleFollowup(url);
			} else if (options.background) {
				markFrontendTiming("fresh-refresh-completed", { url, source: "background" });
				emitApiCacheRefresh(url, "success");
			}
			return data;
		})
		.catch((error) => {
			if (options.background) emitApiCacheRefresh(url, "error", error);
			throw error;
		})
		.finally(() => {
			apiInflight.delete(url);
		});
	apiInflight.set(url, p);
	return p;
}
/**
 * @param {string} path
 * @param {Record<string, string>} [params]
 */
export async function apiGet(path, params) {
	const qs = params ? `?${new URLSearchParams(params).toString()}` : "";
	const url = API_BASE + path + qs;
	loadPersistentApiCache();
	const hit = apiCache.get(url);
	if (hit) {
		const policy = apiCachePolicy(url);
		const age = Date.now() - hit.ts;
		if (age <= policy.freshMs + policy.staleIfErrorMs) {
			if (age >= policy.freshMs) {
				markFrontendTiming("stale-cache-served", { url, source: "browser", ageMs: Math.round(age) });
				apiFetch(url, { background: true }).catch(() => {});
			}
			return hit.data;
		}
		apiCache.delete(url);
		persistApiCache();
	}
	return apiFetch(url);
}
export function clearApiCache() {
	apiCache.clear();
	apiInflight.clear();
	for (const timer of apiServerStaleFollowups.values()) clearTimeout(timer);
	apiServerStaleFollowups.clear();
	apiCacheLoaded = false;
	publicApiCacheClear();
}
/** @param {string} toolName */
export function invalidateToolApiCache(toolName) {
	const name = cleanCacheId(toolName);
	if (!name) return 0;
	recentOwnerCacheDelete(name);
	return invalidateApiCacheWhere((url) => matchesToolCache(url, new Set([name])));
}
/** @param {string | number} listId */
export function invalidateListApiCache(listId) {
	const ident = cleanCacheId(listId);
	if (!ident) return 0;
	return invalidateApiCacheWhere((url) => matchesListCache(url, new Set([ident])));
}
export function invalidateListCollectionApiCache() {
	return invalidateApiCacheWhere(
		(url) => apiPath(url) === LIST_COLLECTION_PATH || apiPath(url) === RECENT_COLLECTION_PATH
	);
}
/** @param {any} data */
function officialWriteSucceeded(data) {
	if (!data || typeof data !== "object") return false;
	if (data.syncStatus) return data.syncStatus === "official";
	if (data.result) return data.result === "official";
	return data.ok === true;
}
/**
 * @param {string} _method
 * @param {string} path
 * @param {any} body
 * @param {any} data
 */
export function invalidateApiCacheForOfficialWrite(_method, path, body, data) {
	if (!officialWriteSucceeded(data)) return 0;
	const parts = new URL(path, "https://toolhub-evolved.local").pathname
		.split("/")
		.filter(Boolean)
		.map((part) => decodeURIComponent(part));
	const apiKind = parts[0] === "v1" && (parts[1] === "write" || parts[1] === "toolhub") ? parts[2] : null;
	if (apiKind === "tools") {
		const toolName =
			cleanCacheId(parts[3]) || objectStringValue(data.toolhub, "name") || objectStringValue(body, "name");
		return toolName ? invalidateToolApiCache(toolName) : 0;
	}
	if (apiKind === "lists") {
		const listId =
			objectStringValue(data.local, "officialId", "official_list_id") ||
			objectStringValue(data.toolhub, "id") ||
			cleanCacheId(parts[3]);
		return listId ? invalidateListApiCache(listId) : invalidateListCollectionApiCache();
	}
	return 0;
}
/**
 * Page through a list endpoint, collecting results. Stops on error, missing
 * `next`, or an empty page.
 * @param {string} path
 * @param {Record<string, string>} [params]
 * @param {{ pageSize?: number, maxPages?: number, map?: (item: any) => any }} [options]
 *   `map` (optional) transforms each raw item.
 * @returns {Promise<any[]>}
 */
export async function paginate(path, params = {}, { pageSize = 100, maxPages = 10, map } = {}) {
	const out = [];
	for (let page = 1; page <= maxPages; page++) {
		let data;
		try {
			data = await apiGet(path, { ...params, page_size: String(pageSize), page: String(page) });
		} catch {
			break;
		}
		const results = data.results || [];
		for (const r of results) out.push(map ? map(r) : r);
		if (!data.next || results.length === 0) break;
	}
	return out;
}
/** @param {unknown} v */
export function firstUrl(v) {
	if (!v) return null;
	if (typeof v === "string") return v;
	if (Array.isArray(v) && v.length > 0) {
		const x = v[0];
		return x && typeof x === "object" ? x.url : x;
	}
	return null;
}
/** @param {unknown} v */
export function hasValue(v) {
	return Array.isArray(v) ? v.length > 0 : v !== null && v !== undefined && v !== "";
}
/**
 * Choose the first of core/annotation that has a value, else the fallback. The
 * fallback's type `T` is asserted onto the chosen raw value: this is the single
 * place normalizeTool trusts the upstream shape, so the constructed record can be
 * a checked `Tool` instead of `any`.
 * @template T
 * @param {unknown} core
 * @param {unknown} annotation
 * @param {T} fallback
 * @returns {T}
 */
export function pick(core, annotation, fallback) {
	if (hasValue(core)) return /** @type {T} */ (core);
	if (hasValue(annotation)) return /** @type {T} */ (annotation);
	return fallback;
}
/* Called lazily (not a module-level constant) so a locale catalog installed at
   boot is picked up. Named helper because normalizeTool's raw-record param is
   `t`, which shadows the i18n t() inside that function body. */
function unknownMaintainer() {
	return t("api.unknownMaintainer", "Unknown");
}
/**
 * Raw author records from the upstream API are heterogeneous (string | object |
 * null), so `a` is typed `any` here.
 * @param {any} a
 */
function normalizeAuthorObj(a) {
	if (!a) return null;
	if (typeof a === "string") return a ? { name: a, url: null, wikiUsername: null, developerUsername: null } : null;
	const name = a.name || "";
	if (!name) return null;
	return {
		name,
		url: a.url || null,
		wikiUsername: a.wiki_username || null,
		developerUsername: a.developer_username || null
	};
}
/**
 * Normalize a raw upstream tool record into the compact `Tool` shape. The raw
 * record is untyped API JSON, so `t` is `any`; the constructed object is also
 * `any` because it is mutated post-construction (weeklyViews/status/overlay
 * flags) in ways the static `Tool` interface intentionally does not model.
 * @param {any} t
 * @returns {Tool}
 */
export function normalizeTool(t) {
	const ann = t.annotations || {};
	const ra = t.author;
	const titleField = localizedField(t.title, t._language);
	const descriptionField = localizedField(t.description, t._language);
	const subtitleField = localizedField(pick(t.subtitle, ann.subtitle, null), t._language);
	const authors = Array.isArray(ra)
		? ra.map((a) => (a && a.name) || (typeof a === "string" ? a : null)).filter(Boolean)
		: typeof ra === "string" && ra
			? [ra]
			: [];
	// filter(Boolean) drops the nulls at runtime but TS can't narrow it, so assert
	// the post-filter element type (no soundness loss — the nulls are gone).
	const authorObjs = /** @type {AuthorObj[]} */ (
		Array.isArray(ra)
			? ra.map((author) => normalizeAuthorObj(author)).filter(Boolean)
			: [normalizeAuthorObj(ra)].filter(Boolean)
	);
	const deprecated = Boolean(t.deprecated || ann.deprecated);
	const experimental = Boolean(t.experimental || ann.experimental);
	/** @type {Tool} */
	const o = {
		name: t.name,
		title: titleField.value || t.name,
		titleLanguage: titleField.value ? titleField.lang : null,
		description: descriptionField.value || "",
		descriptionLanguage: descriptionField.value ? descriptionField.lang : null,
		url: pick(t.url, ann.url, ""),
		icon: pick(t.icon, ann.icon, null),
		keywords: t.keywords || [],
		maintainer: authors[0] || (t.created_by && t.created_by.username) || unknownMaintainer(),
		authors,
		authorObjs,
		wikidata: pick(t.wikidata_qid, ann.wikidata_qid, null),
		subtitle: subtitleField.value || null,
		subtitleLanguage: subtitleField.value ? subtitleField.lang : null,
		sponsor: pick(t.sponsor, ann.sponsor, []),
		replacedBy: pick(t.replaced_by, ann.replaced_by, null),
		toolType: pick(t.tool_type, ann.tool_type, null),
		license: pick(t.license, ann.license, null),
		repository: pick(t.repository, ann.repository, null),
		apiUrl: pick(t.api_url, ann.api_url, null),
		technologyUsed: pick(t.technology_used, ann.technology_used, []),
		audiences: pick(t.audiences, ann.audiences, []),
		tasks: pick(t.tasks, ann.tasks, []),
		forWikis: pick(t.for_wikis, ann.for_wikis, []),
		uiLanguages: pick(t.available_ui_languages, ann.available_ui_languages, []),
		userDocs: firstUrl(pick(t.user_docs_url, ann.user_docs_url, [])),
		devDocs: firstUrl(pick(t.developer_docs_url, ann.developer_docs_url, [])),
		feedback: firstUrl(pick(t.feedback_url, ann.feedback_url, [])),
		bugtracker: pick(t.bugtracker_url, ann.bugtracker_url, null),
		translate: pick(t.translate_url, ann.translate_url, null),
		deprecated,
		experimental,
		modified: t.modified_date || t.modified || null,
		origin: t.origin || "crawler",
		weeklyViews: 0,
		status: statusOf({ deprecated, experimental })
	};
	applyToolOverlay(o);
	INDEX[o.name] = o; // cache for quick-view
	return o;
}
/**
 * @param {string} name
 * @returns {Promise<Tool | null>}
 */
export async function getTool(name) {
	try {
		return normalizeTool(await apiGet(`/tools/${encodeURIComponent(name)}/`));
	} catch (error) {
		// A real 404 means the tool is absent → null (caller shows "not found").
		// Any other failure (5xx, network, parse) is an outage, not an absence —
		// rethrow so the router's error boundary surfaces it instead of the page
		// claiming the tool doesn't exist.
		if (error instanceof ApiError && error.status === 404) {
			return signedIn() && isNewTool(name) ? newToolBase(name) : null;
		}
		throw error;
	}
}
/** @param {string[]} names */
export async function getToolsByName(names) {
	// Batch name-resolution stays resilient: a single missing/erroring tool is
	// dropped, not fatal (unlike the single-tool getTool page above).
	const tools = await Promise.all(
		// Stryker disable next-line ArrowFunction: `() => undefined` is equivalent — the next line's `.filter(Boolean)` drops null and undefined identically.
		(names || []).map((name) => getTool(name).catch(() => null))
	);
	return tools.filter(Boolean);
}
/**
 * @param {any} l
 * @returns {ToolList}
 */
export function normalizeList(l) {
	const tools = /** @type {any[]} */ (l.tools || []).map((tool) => normalizeTool(tool));
	return {
		id: l.id,
		title: l.title || t("api.untitledList", "Untitled list"),
		description: l.description || "",
		toolCount: tools.length,
		tools,
		featured: Boolean(l.featured)
	};
}
/* ===== Backend (/v1) transport — production server sync ====================
   The only other network calls in the app: same-origin requests to our own
   backend (session probe, overlay pull, write-through pushes, and official
   Toolhub writes performed server-side with the user's OAuth grant). Kept here
   so the "network only in api.js" architecture rule stays true. */
export class BackendError extends Error {
	/**
	 * @param {number} status
	 * @param {string} path
	 * @param {any} body
	 */
	constructor(status, path, body) {
		super(`Backend ${status} ${path}`);
		this.name = "BackendError";
		this.status = status;
		this.body = body;
	}
}
/** @param {unknown} error */
export function backendErrorMessage(error) {
	if (error instanceof BackendError) {
		const body = error.body || {};
		const details = body.details || body;
		if (typeof details.message === "string") return details.message;
		if (typeof body.error === "string") return body.error;
		return JSON.stringify(details);
	}
	return error instanceof Error ? error.message : String(error);
}
/** @param {unknown} error */
export function backendErrorBody(error) {
	return error instanceof BackendError ? error.body : null;
}
/**
 * @param {string} path
 * @returns {Promise<any>} parsed JSON, or null on any non-2xx status
 */
export async function backendGetJson(path) {
	const res = await fetch(path, { headers: { Accept: "application/json" } });
	return res.ok ? res.json() : null;
}
/**
 * @param {string} method
 * @param {string} path
 * @param {any} body
 * @param {string} csrf
 * @returns {Promise<any>}
 */
export async function backendWriteJson(method, path, body, csrf) {
	const res = await fetch(path, {
		method,
		headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
		body: body === undefined ? undefined : JSON.stringify(body)
	});
	const data = res.status === 204 ? null : await res.json().catch(() => null);
	if (!res.ok) throw new BackendError(res.status, path, data);
	return data;
}
/**
 * @param {string} path
 * @param {any} body
 * @param {string} csrf
 * @returns {Promise<void>} resolves either way — overlay write-through pushes never throw
 */
export async function backendPutJson(path, body, csrf) {
	try {
		await backendWriteJson("PUT", path, body, csrf);
	} catch {
		// offline blip: the localStorage cache still holds the value
	}
}
