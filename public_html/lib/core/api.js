// SPDX-License-Identifier: GPL-3.0-or-later
import { hasValue } from "./util.js";
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

export const READ_TIMEOUT_MS = 12_000;

/**
 * Bound every read that can gate route or account rendering. Timeout failures
 * reject through the existing error paths, so the UI can recover instead of
 * leaving its initial busy state in place forever.
 * @param {RequestInfo | URL} input
 * @param {RequestInit} [init]
 * @returns {Promise<Response>}
 */
export function fetchRead(input, init = {}) {
	const controller = new AbortController();
	const callerSignal = init.signal;
	let timedOut = false;
	const abortFromCaller = () => controller.abort(callerSignal?.reason);
	if (callerSignal?.aborted) abortFromCaller();
	else callerSignal?.addEventListener("abort", abortFromCaller, { once: true });
	const timer = setTimeout(() => {
		timedOut = true;
		controller.abort();
	}, READ_TIMEOUT_MS);
	return fetch(input, { ...init, signal: controller.signal })
		.catch((error) => {
			if (timedOut) throw new DOMException("Read timed out", "TimeoutError");
			throw error;
		})
		.finally(() => {
			clearTimeout(timer);
			callerSignal?.removeEventListener("abort", abortFromCaller);
		});
}

/* Tool cache for O(1) detail / quick-view lookups; filled by normalizeTool()
   as local replica data arrives (search results, lists, tool pages). */
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
	"toolhubStatus",
	"toolhubCode",
	"validationErrors",
	"baseRevision",
	"fieldStatuses",
	"reviewStatus",
	"viewerOwned"
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
		/** @type {any} */ (o).editToolhubResponse = e.toolhubResponse;
		/** @type {any} */ (o).editToolhubStatus = e.toolhubStatus;
		/** @type {any} */ (o).editToolhubCode = e.toolhubCode;
		/** @type {any} */ (o).editViewerOwned = e.viewerOwned;
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
		/** @type {any} */ (o).annotationToolhubResponse = a.toolhubResponse;
		/** @type {any} */ (o).annotationToolhubStatus = a.toolhubStatus;
		/** @type {any} */ (o).annotationToolhubCode = a.toolhubCode;
		/** @type {any} */ (o).annotationViewerOwned = a.viewerOwned;
	}
	if (e || a) o.status = /** @type {any} */ (statusOf(o)); // flags may have changed
	return o;
}
// Build a compact tool object from a locally-registered record (the project
// database that complements the replicated catalog), then overlay edits.
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
					lifecycle: "",
					origin: "api"
				},
				rec
			)
		)
	);
	o.name = name;
	o.weeklyViews = 0;
	/** @type {any} */ (o).viewerOwned = rec.viewerOwned;
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
 * Rank what is worth saying about a tool, most consequential first.
 *
 * Deprecated and experimental come first because a maintainer said them about
 * their own tool. Archived is below both because nobody said it: it is this
 * codebase's observation that nothing it can see loads the tool, and a
 * maintainer's own claim about their work outranks our reading of the traffic.
 * @param {{ deprecated: boolean; experimental: boolean; lifecycle?: string }} t
 * @returns {ToolStatus}
 */
export function statusOf(t) {
	return t.deprecated
		? { level: "red", label: "Deprecated" }
		: t.experimental
			? { level: "yellow", label: "Experimental" }
			: t.lifecycle === "archived"
				? { level: "grey", label: "Archived" }
				: { level: "green", label: "Healthy" };
}
/* ================================================================= LOCAL CATALOG API
   Every product read comes from the same-origin, versioned local replica.
   Toolhub network access belongs to scheduled synchronization and authenticated
   writes; it is never part of rendering a page. */
const API_BASE = "/v1/catalog";
/* Browser cache for anonymous local-catalog GET reads. Keyed by full
   same-origin catalog URL. Hot entries live in memory; a bounded public-data copy
   also lives in localStorage so hard refreshes can render useful content before
   the live API refresh finishes. /v1 session, OAuth, overlay, and write calls use
   the backend* helpers below and never enter this cache. */
/* These mirror the server policy in proxy/backend/api_cache.py — the shared
   cache invalidates on Toolhub's recent-change feed, so freshness is a backstop
   rather than the mechanism, and short windows only bought revalidations.
   tests/proxy/test_app.py fails if the two sides drift apart. */
const API_RECENT_TTL_MS = 5 * 60 * 1000;
const API_SEARCH_TTL_MS = 30 * 60 * 1000;
const API_DETAIL_TTL_MS = 6 * 60 * 60 * 1000;
const API_CRAWLER_TTL_MS = 6 * 60 * 60 * 1000;
const API_CONFIG_TTL_MS = 24 * 60 * 60 * 1000;
const API_DEFAULT_TTL_MS = 15 * 60 * 1000;
const API_STALE_IF_ERROR_MS = 24 * 60 * 60 * 1000;
const API_STORAGE_MAX_ENTRIES = 48;
const API_STORAGE_MAX_CHARS = 240000;
/* Total budget across all persisted entries. The per-entry cap alone allowed
   48 x 240000 chars, far past any browser's ~5MB origin quota — and a quota
   failure is silent, so the cache would simply stop updating and every reload
   would start cold. Kept well under quota to leave room for the overlay,
   membership, and owner caches that share it. */
const API_STORAGE_TOTAL_MAX_CHARS = 1200000;
const API_PERSIST_IDLE_TIMEOUT_MS = 2000;
const API_PERSIST_FALLBACK_MS = 400;
const API_PERSISTENT_MAX_AGE_MS = API_CONFIG_TTL_MS + API_STALE_IF_ERROR_MS;
const SERVER_CACHE_HEADER = "X-Toolhub-Evolved-Cache";
const SERVER_STALE_CACHE = "stale";
const SERVER_STALE_FOLLOWUP_MS = 1200;
const apiCache = new Map(); // url -> { data, ts }
const apiInflight = new Map(); // url -> Promise<data>
const BACKEND_SEARCH_TTL_MS = 5 * 1000;
const BACKEND_GRAPH_TTL_MS = 5 * 60 * 1000;
/* The landing page is one composed payload now, so a refresh repaint would
   otherwise refetch the whole thing. Matches the server's own freshness. */
const BACKEND_HOME_TTL_MS = 5 * 60 * 1000;
const backendGetCache = new Map(); // path -> { data, ts }
const backendGetInflight = new Map(); // path -> Promise<data>
/** @type {Map<string, ReturnType<typeof setTimeout>>} */
const apiServerStaleFollowups = new Map();
let apiCacheLoaded = false;
let apiPersistScheduled = false;
const DETAIL_COLLECTIONS = new Set(["tools", "lists"]);
const TOOL_AGGREGATE_PATHS = new Set([
	"/v1/catalog/search/tools/",
	"/v1/catalog/search/facets/",
	"/v1/catalog/ui/home/"
]);
const LIST_COLLECTION_PATH = "/v1/catalog/lists/";
const RECENT_COLLECTION_PATH = "/v1/catalog/recent/";
const CRAWLER_RUNS_PATH = "/v1/catalog/crawler/runs/";
const CONFIG_PATHS = new Set([
	"/v1/catalog/",
	"/v1/catalog/schema/",
	"/v1/catalog/audiences/",
	"/v1/catalog/content-types/",
	"/v1/catalog/licenses/",
	"/v1/catalog/origins/",
	"/v1/catalog/tasks/",
	"/v1/catalog/tool-types/",
	"/v1/catalog/technology-used/",
	"/v1/catalog/wikis/"
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
/** @param {string} url */
function apiResourceParts(url) {
	const parts = apiPathParts(url);
	if (parts[0] === "v1" && parts[1] === "catalog") return parts.slice(2);
	return parts[0] === "api" ? parts.slice(1) : parts;
}
/** @param {string} path */
function isDetailPath(path) {
	const parts = apiResourceParts(path);
	return parts.length === 2 && DETAIL_COLLECTIONS.has(parts[0]) && Boolean(parts[1]);
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
	const parts = apiResourceParts(url);
	return parts.length >= 2 && parts[0] === "tools" && toolNames.has(parts[1]);
}
/**
 * @param {string} url
 * @param {Set<string>} listIds
 */
function matchesListCache(url, listIds) {
	const path = apiPath(url);
	if (path === RECENT_COLLECTION_PATH || path === LIST_COLLECTION_PATH) return listIds.size > 0;
	const parts = apiResourceParts(url);
	return parts.length >= 2 && parts[0] === "lists" && listIds.has(parts[1]);
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
	if (path === RECENT_COLLECTION_PATH || path === "/api/recent/") {
		return { freshMs: API_RECENT_TTL_MS, staleIfErrorMs: API_STALE_IF_ERROR_MS };
	}
	if (
		path === "/v1/catalog/search/tools/" ||
		path === "/v1/catalog/search/facets/" ||
		path === "/api/search/tools/"
	) {
		return { freshMs: API_SEARCH_TTL_MS, staleIfErrorMs: API_STALE_IF_ERROR_MS };
	}
	if (path === CRAWLER_RUNS_PATH) return { freshMs: API_CRAWLER_TTL_MS, staleIfErrorMs: API_STALE_IF_ERROR_MS };
	if (isDetailPath(path)) return { freshMs: API_DETAIL_TTL_MS, staleIfErrorMs: API_STALE_IF_ERROR_MS };
	if (CONFIG_PATHS.has(path) || CONFIG_PATHS.has(path.replace(/^\/api\//, "/v1/catalog/"))) {
		return { freshMs: API_CONFIG_TTL_MS, staleIfErrorMs: API_STALE_IF_ERROR_MS };
	}
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
/**
 * Serialize the live cache into a storage payload under a total char budget.
 *
 * Newest first, so the budget is spent on what a reload is most likely to need.
 * Each entry is stringified exactly once and its JSON reused verbatim in the
 * payload — measuring with one JSON.stringify and writing with another meant
 * serializing the whole cache twice.
 * @returns {string}
 */
function serializeApiCache() {
	const fresh = [...apiCache.entries()]
		.filter(([url, entry]) => {
			if (!url.startsWith(API_BASE)) return false;
			const policy = apiCachePolicy(url);
			return Date.now() - entry.ts <= policy.freshMs + policy.staleIfErrorMs;
		})
		.sort((a, b) => b[1].ts - a[1].ts)
		.slice(0, API_STORAGE_MAX_ENTRIES);
	const parts = [];
	let total = 0;
	for (const [url, entry] of fresh) {
		let dataJson;
		try {
			dataJson = JSON.stringify(entry.data);
		} catch {
			continue; // a payload we cannot serialize is simply not persisted
		}
		if (typeof dataJson !== "string" || dataJson.length > API_STORAGE_MAX_CHARS) continue;
		const part = `[${JSON.stringify(url)},{"data":${dataJson},"ts":${entry.ts}}]`;
		if (total + part.length > API_STORAGE_TOTAL_MAX_CHARS) break;
		parts.push(part);
		total += part.length + 1; // + the joining comma
	}
	return `{"entries":[${parts.join(",")}]}`;
}
function writeApiCacheToStorage() {
	apiPersistScheduled = false;
	try {
		publicApiCacheSave(serializeApiCache());
	} catch {
		return;
	}
}
/**
 * Queue one storage write for the next idle moment.
 *
 * This used to run synchronously on every API response: serializing the cache
 * twice and handing localStorage a multi-megabyte string, on the main thread,
 * while the view was rendering. Coalescing means a burst of responses (a route
 * that fetches several endpoints, plus background revalidations) costs one
 * write instead of one per response.
 */
function persistApiCache() {
	if (apiPersistScheduled) return;
	apiPersistScheduled = true;
	if (typeof requestIdleCallback === "function") {
		requestIdleCallback(writeApiCacheToStorage, { timeout: API_PERSIST_IDLE_TIMEOUT_MS });
	} else {
		setTimeout(writeApiCacheToStorage, API_PERSIST_FALLBACK_MS);
	}
}
/**
 * Write any queued cache payload to storage now.
 *
 * A debounced write that only ever runs when the browser is idle would lose the
 * newest responses for anyone who navigates away promptly — the exact visit
 * whose data the next load wants most. Called on pagehide, and by tests that
 * need the write to have happened.
 */
export function flushApiCache() {
	if (apiPersistScheduled) writeApiCacheToStorage();
}
if (typeof addEventListener === "function") {
	// pagehide, not unload: it fires for bfcache navigations too, and is the
	// event browsers still guarantee for "the page is going away".
	addEventListener("pagehide", flushApiCache);
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
			res = await fetchRead(url, { headers: { Accept: "application/json" } });
			markFrontendTimingOnce("first-api-response", {
				url,
				status: res.status,
				cache: responseHeader(res, SERVER_CACHE_HEADER)
			});
		} catch (error) {
			lastError = error; // network-layer failure → retry
			if (
				error &&
				typeof error === "object" &&
				/** @type {{ name?: unknown }} */ (error).name === "TimeoutError"
			) {
				throw error;
			}
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
/**
 * Report whether a read is already answerable from cache, without fetching.
 *
 * Lets a view tell a genuinely cold read from a warm one, so it can pay for a
 * local-first first paint only when there is nothing cached to serve.
 * @param {string} path
 * @param {Record<string, string>} [params]
 * @returns {boolean}
 */
export function apiCached(path, params) {
	const qs = params ? `?${new URLSearchParams(params).toString()}` : "";
	const url = API_BASE + path + qs;
	loadPersistentApiCache();
	const hit = apiCache.get(url);
	if (!hit) return false;
	const policy = apiCachePolicy(url);
	return Date.now() - hit.ts <= policy.freshMs + policy.staleIfErrorMs;
}
/**
 * Fetch a same-origin JSON URL and expose the raw Response. This keeps
 * network ownership in core while letting developer tools inspect status and
 * headers that apiGet intentionally abstracts away.
 *
 * @param {string} url
 * @param {RequestInit} [init]
 * @returns {Promise<Response>}
 */
export function apiGetResponse(url, init = {}) {
	return fetchRead(url, { ...init, headers: { ...init.headers, Accept: "application/json" } });
}
export function clearApiCache() {
	apiCache.clear();
	apiInflight.clear();
	backendGetCache.clear();
	backendGetInflight.clear();
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
function invalidateListCollectionApiCache() {
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
 *
 * Page 1 tells us `count`, which is enough to know how many pages exist — so
 * the rest are fetched concurrently rather than one round trip at a time.
 * Walking `next` serially meant a multi-page crawl cost the sum of its pages;
 * on a cold cache that was seconds of upstream latency before anything
 * depending on it could render. Falls back to the serial `next` walk when the
 * endpoint does not report a usable count.
 *
 * @param {string} path
 * @param {Record<string, string>} [params]
 * @param {{ pageSize?: number, maxPages?: number, map?: (item: any) => any }} [options]
 *   `map` (optional) transforms each raw item.
 * @returns {Promise<any[]>}
 */
export async function paginate(path, params = {}, { pageSize = 100, maxPages = 10, map } = {}) {
	/** @param {number} page */
	const fetchPage = (page) => apiGet(path, { ...params, page_size: String(pageSize), page: String(page) });
	/** @param {any[]} results @param {any[]} into */
	const collect = (results, into) => {
		for (const r of results) into.push(map ? map(r) : r);
	};

	/** @type {any[]} */
	const out = [];
	let first;
	try {
		first = await fetchPage(1);
	} catch {
		return out;
	}
	const firstResults = first.results || [];
	collect(firstResults, out);
	if (!first.next || firstResults.length === 0) return out;

	const count = Number(first.count);
	if (Number.isFinite(count) && count > 0) {
		const lastPage = Math.min(maxPages, Math.ceil(count / pageSize));
		const rest = [];
		for (let page = 2; page <= lastPage; page++) rest.push(page);
		const pages = await Promise.all(rest.map((page) => fetchPage(page).catch(() => null)));
		for (const data of pages) {
			if (data) collect(data.results || [], out);
		}
		return out;
	}

	// No usable count: walk `next` one page at a time, as before.
	for (let page = 2; page <= maxPages; page++) {
		let data;
		try {
			data = await fetchPage(page);
		} catch {
			break;
		}
		const results = data.results || [];
		collect(results, out);
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
	// Not from any toolinfo, which is what the underscore says: the backend
	// writes it for records it synthesized from a wiki, and leaves it off
	// everything the official catalog supplied.
	const lifecycle = typeof t._lifecycle === "string" ? t._lifecycle : "";
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
		lifecycle,
		modified: t.modified_date || t.modified || null,
		origin: t.origin || "crawler",
		catalogProjection: t._catalogProjection || null,
		cachedIconUrl: t._cachedIconUrl || null,
		accountRelationships: Array.isArray(t.accountRelationships) ? t.accountRelationships : [],
		accountPerson: t.accountPerson && typeof t.accountPerson.id === "string" ? { ...t.accountPerson } : undefined,
		relationshipPeople: Array.isArray(t.relationshipPeople) ? t.relationshipPeople : [],
		weeklyViews: 0,
		status: statusOf({ deprecated, experimental, lifecycle })
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
	const projectionPending = backendGetJson(`/v1/catalog/tools/${encodeURIComponent(name)}/projection/`).catch(
		() => null
	);
	const withProjection = async (/** @type {any} */ raw) => {
		const projection = await projectionPending;
		if (!projection || !projection.record) return normalizeTool(raw);
		return normalizeTool({
			...raw,
			...projection.record,
			_catalogProjection: projection,
			_cachedIconUrl: projection.asset?.url || null
		});
	};
	try {
		return withProjection(await apiGet(`/tools/${encodeURIComponent(name)}/`));
	} catch (error) {
		// A real 404 means the tool is absent → null (caller shows "not found").
		// Any other failure (5xx, network, parse) is an outage, not an absence —
		// rethrow so the router's error boundary surfaces it instead of the page
		// claiming the tool doesn't exist.
		if (error instanceof ApiError && error.status === 404) {
			return signedIn() && isNewTool(name) ? newToolBase(name) : null;
		}
		const fallback = await cachedCanonicalTools({ names: [name], limit: 1 }).catch(() => []);
		if (fallback[0]) {
			return withProjection(fallback[0].canonicalRecord || fallback[0]);
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
 * Read structured canonical Toolhub records from Evolved's local database.
 * This is intentionally same-origin `/v1` data, not an upstream `/api` call.
 * @param {{ names?: string[], q?: string, limit?: number }} [options]
 * @returns {Promise<Tool[]>}
 */
export async function cachedCanonicalTools(options = {}) {
	const params = new URLSearchParams();
	const names = (options.names || []).filter(Boolean);
	if (names.length > 0) params.set("names", names.join(","));
	if (options.q) params.set("q", options.q);
	params.set("limit", String(options.limit || names.length || 24));
	const data = await backendGetJson(`/v1/canonical/tools/?${params.toString()}`);
	const rows = Array.isArray(data?.results) ? data.results : [];
	return rows
		.map((/** @type {any} */ row) => {
			if (!row || !row.record) return null;
			const tool = normalizeTool(row.record);
			tool.canonicalRecord = row.record;
			return tool;
		})
		.filter(Boolean);
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
/**
 * Turn a backend or network failure into an actionable message for a person.
 * This intentionally accepts local-fallback response objects as well as thrown
 * errors because official writes can be persisted locally after an upstream
 * rejection.
 * @param {unknown} error
 * @returns {string}
 */
export function backendErrorExplanation(error) {
	const isBackendError = error instanceof BackendError;
	const object = error && typeof error === "object" ? /** @type {any} */ (error) : null;
	const body = isBackendError ? error.body || {} : object || {};
	const status = isBackendError
		? error.status
		: Number.isFinite(Number(object?.status))
			? Number(object.status)
			: null;
	const details = body.details && typeof body.details === "object" ? body.details : body;
	const rawMessage = [
		body.lastError,
		details.message,
		details.detail,
		body.error,
		error instanceof Error ? error.message : null
	].find((value) => typeof value === "string" && value.trim());
	const message = rawMessage ? rawMessage.trim() : "The request could not be completed.";
	const normalized = message.toLowerCase();
	const validationErrors = Array.isArray(body.validationErrors)
		? body.validationErrors
				.map((/** @type {any} */ item) => {
					if (typeof item === "string") return item.trim();
					if (!item || typeof item !== "object") return "";
					const field = item.field || item.name;
					const detail = item.message || item.detail || item.error;
					return detail ? `${field ? `${field}: ` : ""}${detail}`.trim() : "";
				})
				.filter(Boolean)
		: [];
	const prefix = status ? `HTTP ${status}: ` : "";

	if (
		body.reauth ||
		status === 401 ||
		/oauth grant|sign[- ]in is required|authorization has expired/.test(normalized)
	) {
		return `${prefix}Your Toolhub sign-in or authorization has expired. Sign in again, grant Toolhub write access, and retry.`;
	}
	if (status === 403 && /csrf|security session/.test(normalized)) {
		return `${prefix}This page's security session is stale. Reload the page and try again; if it persists, sign in again.`;
	}
	if (status === 403 || /permission|not allowed|forbidden/.test(normalized)) {
		return `${prefix}${message} You are signed in, but this account is not allowed to perform this action. Check your Toolhub permissions or use the account that owns the tool.`;
	}
	if (status === 429) {
		return `${prefix}Too many requests were sent. Wait a moment before trying again.`;
	}
	if ((status === 400 || status === 422) && validationErrors.length > 0) {
		return `${prefix}Toolhub rejected the submitted data. Fix these fields: ${validationErrors.join("; ")}.`;
	}
	if (status === 502 || status === 503 || status === 504 || /unavailable|timed out|timeout/.test(normalized)) {
		return `${prefix}Toolhub is temporarily unavailable. No official change was published; wait a moment and retry.`;
	}
	if (
		!isBackendError &&
		(error instanceof TypeError || /network|fetch|failed to fetch|load failed/.test(normalized))
	) {
		return "Could not reach Toolhub Evolved. Check your connection, VPN, or content blocker, then retry.";
	}
	return `${prefix}${message} No official change was published; retry or report this error if it continues.`;
}
/** @param {unknown} error */
export function backendErrorBody(error) {
	return error instanceof BackendError ? error.body : null;
}
/**
 * @param {string} path
 * @returns {number}
 */
function backendGetFreshMs(path) {
	const url = new URL(path, location.origin);
	if (url.pathname === "/v1/search/tools/") return BACKEND_SEARCH_TTL_MS;
	if (url.pathname === "/v1/home/") return BACKEND_HOME_TTL_MS;
	return url.pathname === "/v1/graph/" ? BACKEND_GRAPH_TTL_MS : 0;
}
/**
 * @param {string} path
 * @returns {Promise<any>} parsed JSON, or null on any non-2xx status
 */
export async function backendGetJson(path) {
	const freshMs = backendGetFreshMs(path);
	if (freshMs > 0) {
		const cached = backendGetCache.get(path);
		if (cached && Date.now() - cached.ts < freshMs) return cached.data;
		const inflight = backendGetInflight.get(path);
		if (inflight) return inflight;
	}
	const request = fetchRead(path, { headers: { Accept: "application/json" } })
		.then((res) => (res.ok ? res.json() : null))
		.then((data) => {
			if (freshMs > 0) backendGetCache.set(path, { data, ts: Date.now() });
			return data;
		})
		.finally(() => {
			backendGetInflight.delete(path);
		});
	if (freshMs > 0) backendGetInflight.set(path, request);
	return request;
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
