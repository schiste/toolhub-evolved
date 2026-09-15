// SPDX-License-Identifier: GPL-3.0-or-later

/*
 * Cache policy is deliberately independent from the API transport. Keeping
 * endpoint classification and retention limits here means reads, persistence,
 * and invalidation all consult the same small set of pure rules.
 */
export const API_BASE = "/v1/catalog";
export const API_RECENT_TTL_MS = 5 * 60 * 1000;
export const API_SEARCH_TTL_MS = 30 * 60 * 1000;
export const API_DETAIL_TTL_MS = 6 * 60 * 60 * 1000;
export const API_CRAWLER_TTL_MS = 6 * 60 * 60 * 1000;
export const API_CONFIG_TTL_MS = 24 * 60 * 60 * 1000;
export const API_DEFAULT_TTL_MS = 15 * 60 * 1000;
export const API_STALE_IF_ERROR_MS = 24 * 60 * 60 * 1000;
export const API_STORAGE_MAX_ENTRIES = 48;
export const API_STORAGE_MAX_CHARS = 240000;
export const API_STORAGE_TOTAL_MAX_CHARS = 1200000;
export const API_PERSIST_IDLE_TIMEOUT_MS = 2000;
export const API_PERSIST_FALLBACK_MS = 400;
export const API_PERSISTENT_MAX_AGE_MS = API_CONFIG_TTL_MS + API_STALE_IF_ERROR_MS;

export const SERVER_CACHE_HEADER = "X-Toolhub-Evolved-Cache";
export const SERVER_STALE_CACHE = "stale";
export const SERVER_STALE_FOLLOWUP_MS = 1200;

export const BACKEND_SEARCH_TTL_MS = 5 * 1000;
export const BACKEND_GRAPH_TTL_MS = 5 * 60 * 1000;
export const BACKEND_HOME_TTL_MS = 5 * 60 * 1000;

export const DETAIL_COLLECTIONS = new Set(["tools", "lists"]);
export const TOOL_AGGREGATE_PATHS = new Set([
	"/v1/catalog/search/tools/",
	"/v1/catalog/search/facets/",
	"/v1/catalog/ui/home/"
]);
export const LIST_COLLECTION_PATH = "/v1/catalog/lists/";
export const RECENT_COLLECTION_PATH = "/v1/catalog/recent/";
export const CRAWLER_RUNS_PATH = "/v1/catalog/crawler/runs/";
export const CONFIG_PATHS = new Set([
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

/** @param {string} url */
export function apiPath(url) {
	const path = new URL(url, "https://toolhub-evolved.local").pathname;
	return path.endsWith("/") ? path : `${path}/`;
}

/** @param {string} url */
export function apiPathParts(url) {
	return apiPath(url)
		.split("/")
		.filter(Boolean)
		.map((part) => decodeURIComponent(part));
}

/** @param {string} url */
export function apiResourceParts(url) {
	const parts = apiPathParts(url);
	if (parts[0] === "v1" && parts[1] === "catalog") return parts.slice(2);
	return parts[0] === "api" ? parts.slice(1) : parts;
}

/** @param {string} path */
export function isDetailPath(path) {
	const parts = apiResourceParts(path);
	return parts.length === 2 && DETAIL_COLLECTIONS.has(parts[0]) && Boolean(parts[1]);
}

/**
 * @param {unknown} value
 * @returns {string | null}
 */
export function cleanCacheId(value) {
	if (value === null || value === undefined) return null;
	const text = String(value).trim();
	return text || null;
}

/**
 * @param {any} object
 * @param {...string} keys
 * @returns {string | null}
 */
export function objectStringValue(object, ...keys) {
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
export function matchesToolCache(url, toolNames) {
	const path = apiPath(url);
	if (path === RECENT_COLLECTION_PATH || TOOL_AGGREGATE_PATHS.has(path)) return toolNames.size > 0;
	const parts = apiResourceParts(url);
	return parts.length >= 2 && parts[0] === "tools" && toolNames.has(parts[1]);
}

/**
 * @param {string} url
 * @param {Set<string>} listIds
 */
export function matchesListCache(url, listIds) {
	const path = apiPath(url);
	if (path === RECENT_COLLECTION_PATH || path === LIST_COLLECTION_PATH) return listIds.size > 0;
	const parts = apiResourceParts(url);
	return parts.length >= 2 && parts[0] === "lists" && listIds.has(parts[1]);
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

/**
 * @param {string} path
 * @returns {number}
 */
export function backendGetFreshMs(path) {
	const url = new URL(path, location.origin);
	if (url.pathname === "/v1/search/tools/") return BACKEND_SEARCH_TTL_MS;
	if (url.pathname === "/v1/home/") return BACKEND_HOME_TTL_MS;
	return url.pathname === "/v1/graph/" ? BACKEND_GRAPH_TTL_MS : 0;
}
