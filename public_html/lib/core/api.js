// SPDX-License-Identifier: GPL-3.0-or-later
import { isNewTool, newToolBase, normalizeTool } from "./tool-normalizer.js";
import {
	API_BASE,
	API_PERSISTENT_MAX_AGE_MS,
	API_PERSIST_FALLBACK_MS,
	API_PERSIST_IDLE_TIMEOUT_MS,
	API_STORAGE_MAX_CHARS,
	API_STORAGE_MAX_ENTRIES,
	API_STORAGE_TOTAL_MAX_CHARS,
	LIST_COLLECTION_PATH,
	RECENT_COLLECTION_PATH,
	SERVER_CACHE_HEADER,
	SERVER_STALE_CACHE,
	SERVER_STALE_FOLLOWUP_MS,
	apiCachePolicy,
	apiPath,
	backendGetFreshMs,
	cleanCacheId,
	matchesListCache,
	matchesToolCache,
	objectStringValue
} from "./api-cache-policy.js";
import { markFrontendTiming, markFrontendTimingOnce } from "./diagnostics.js";
import { signedIn } from "./session.js";
import {
	publicApiCacheClear,
	publicApiCacheLoad,
	publicApiCacheSave,
	recentOwnerCacheDelete
} from "./store.js";

export {
	INDEX,
	applyToolOverlay,
	firstUrl,
	isNewTool,
	localToolBase,
	newToolBase,
	normalizeList,
	normalizeTool,
	pick,
	statusOf
} from "./tool-normalizer.js";
export { apiCachePolicy } from "./api-cache-policy.js";

export const READ_TIMEOUT_MS = 12_000;

/**
 * A read index.html started before this bundle existed.
 *
 * The shell knows the route while app.js is still downloading, so for the few
 * pages whose first paint waits on one slow read it issues that read straight
 * away and parks the promise on `window` (see the route-hints block there).
 * Claiming it here, at the transport layer, rather than at apiGet's level means
 * every caching, retry, timing and stale-revalidate decision above stays
 * exactly where it was: the shell contributes a head start, not a second code
 * path through the API.
 *
 * Single use. A Response body can only be read once, and a retry after a failed
 * preflight has to go back to the network rather than replay the failure.
 * @param {RequestInfo | URL} input
 * @returns {Promise<Response> | undefined}
 */
function takePreflight(input) {
	const started = /** @type {{ __preflight?: Map<string, Promise<Response>> }} */ (globalThis).__preflight;
	if (!started || typeof input !== "string") return undefined;
	const warm = started.get(input);
	if (warm) started.delete(input);
	return warm;
}

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
	const warm = takePreflight(input);
	// A preflight runs on its own connection and cannot be cancelled from here,
	// so the timeout is honoured by abandoning it rather than aborting it. The
	// orphaned response is simply discarded.
	const request = warm
		? Promise.race([
				warm,
				new Promise((_resolve, reject) => {
					if (controller.signal.aborted) {
						reject(controller.signal.reason);
					} else {
						controller.signal.addEventListener("abort", () => reject(controller.signal.reason), {
							once: true
						});
					}
				})
			])
		: fetch(input, { ...init, signal: controller.signal });
	return request
		.catch((error) => {
			if (timedOut) throw new DOMException("Read timed out", "TimeoutError");
			throw error;
		})
		.finally(() => {
			clearTimeout(timer);
			callerSignal?.removeEventListener("abort", abortFromCaller);
		});
}

/* ================================================================= LOCAL CATALOG API
   Every product read comes from the same-origin, versioned local replica.
   Toolhub network access belongs to scheduled synchronization and authenticated
   writes; it is never part of rendering a page. */
/* Browser cache for anonymous local-catalog GET reads. Keyed by full
   same-origin catalog URL. Hot entries live in memory; a bounded public-data copy
   also lives in localStorage so hard refreshes can render useful content before
   the live API refresh finishes. /v1 session, OAuth, overlay, and write calls use
   the backend* helpers below and never enter this cache. */
/* These mirror the server policy in proxy/backend/api_cache.py — the shared
   cache invalidates on Toolhub's recent-change feed, so freshness is a backstop
   rather than the mechanism, and short windows only bought revalidations.
   tests/proxy/test_app.py fails if the two sides drift apart. */
const apiCache = new Map(); // url -> { data, ts }
const apiInflight = new Map(); // url -> Promise<data>
/* The landing page is one composed payload now, so a refresh repaint would
   otherwise refetch the whole thing. Matches the server's own freshness. */
const backendGetCache = new Map(); // path -> { data, ts }
const backendGetInflight = new Map(); // path -> Promise<data>
/** @type {Map<string, ReturnType<typeof setTimeout>>} */
const apiServerStaleFollowups = new Map();
let apiCacheLoaded = false;
let apiPersistScheduled = false;
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
 * Browsing withholds archived tools unless `includeArchived` says otherwise,
 * matching what `/search/tools/` does — this is the fallback the search and home
 * views use when that request fails, and a fallback with a wider population
 * would answer an outage with tools the live page never lists. Fetching by
 * `names` is unaffected: naming a row is asking for it on purpose. `statuses`
 * carries the rest of the Status group the same way; null means the caller
 * expressed no preference, which the API reads as every kind.
 * @param {{ names?: string[], q?: string, limit?: number, includeArchived?: boolean, statuses?: string[] | null }} [options]
 * @returns {Promise<Tool[]>}
 */
export async function cachedCanonicalTools(options = {}) {
	const params = new URLSearchParams();
	const names = (options.names || []).filter(Boolean);
	if (names.length > 0) params.set("names", names.join(","));
	if (options.q) params.set("q", options.q);
	if (options.includeArchived) params.set("include_archived", "1");
	// Sent only when it narrows something, and by the same rule the live search
	// uses: an absent `status` is every kind, and an empty one is none. The
	// fallback answers the reader's filters or it answers a different question.
	if (options.statuses) params.set("status", options.statuses.join(","));
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
