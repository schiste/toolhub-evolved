// SPDX-License-Identifier: GPL-3.0-or-later
import { expOn, signedIn, USER } from "./session.js";
import { toolEditsMap, toolAnnosMap, toolNewMap } from "./store.js";
import { synthViews } from "./synth.js";

/* Tool cache for O(1) detail / quick-view lookups; filled by normalizeTool()
   as live data arrives (search results, lists, tool pages). No snapshot. */
/** @type {Record<string, Tool>} */
export const INDEX = {};

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
		Object.assign(o, e);
		// `edited`/`annotated`/`status` (object) are runtime extras the static
		// Tool interface doesn't model; cast through any for these writes.
		/** @type {any} */ (o).edited = true;
	}
	const a = toolAnnosMap()[o.name];
	if (a) {
		Object.assign(o, a);
		/** @type {any} */ (o).annotated = true;
	}
	if (e || a) o.status = /** @type {any} */ (statusOf(o)); // flags may have changed
	return o;
}
// Build a compact tool object for a net-new demo submission, then overlay edits.
/**
 * @param {string} name
 * @returns {Tool | null}
 */
export function newToolBase(name) {
	const rec = toolNewMap()[name];
	if (!rec) return null;
	const o = Object.assign(
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
	);
	o.weeklyViews = synthViews(name);
	o.status = statusOf(o);
	INDEX[name] = o;
	return applyToolOverlay(o);
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
/* In-memory stale-while-revalidate cache for GET reads. Keyed by full URL, it
   lives only for the session (a full page reload starts fresh, so the catalog is
   still "live on load"). A cache hit returns instantly — no spinner on revisits —
   and, once the entry is older than API_TTL_MS, a background refresh updates it
   for next time. Concurrent requests for the same URL share one in-flight fetch. */
const API_TTL_MS = 30000;
const apiCache = new Map(); // url -> { data, ts }
const apiInflight = new Map(); // url -> Promise<data>
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
 * @returns {Promise<any>}
 */
async function fetchJson(url, attempts = API_RETRIES) {
	let lastError;
	for (let attempt = 1; attempt <= attempts; attempt += 1) {
		let res;
		try {
			res = await fetch(url, { headers: { Accept: "application/json" } });
		} catch (error) {
			lastError = error; // network-layer failure → retry
			if (attempt >= attempts) throw error;
			await sleep(200 * 2 ** (attempt - 1));
			continue;
		}
		if (res.ok) return res.json();
		if (!RETRYABLE_STATUS.has(res.status) || attempt >= attempts) throw new ApiError(res.status, url);
		await sleep(200 * 2 ** (attempt - 1));
	}
	throw lastError;
}
/** @param {string} url */
function apiFetch(url) {
	if (apiInflight.has(url)) return apiInflight.get(url);
	const p = fetchJson(url)
		.then((data) => {
			apiCache.set(url, { data, ts: Date.now() });
			return data;
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
	const hit = apiCache.get(url);
	if (hit) {
		if (Date.now() - hit.ts >= API_TTL_MS) apiFetch(url).catch(() => {}); // revalidate in background
		return hit.data;
	}
	return apiFetch(url);
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
		title: t.title || t.name,
		description: t.description || "",
		url: pick(t.url, ann.url, ""),
		icon: pick(t.icon, ann.icon, null),
		keywords: t.keywords || [],
		maintainer: authors[0] || (t.created_by && t.created_by.username) || "Unknown",
		authors,
		authorObjs,
		wikidata: pick(t.wikidata_qid, ann.wikidata_qid, null),
		subtitle: pick(t.subtitle, ann.subtitle, null),
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
		weeklyViews: synthViews(t.name),
		status: statusOf({ deprecated, experimental })
	};
	if (expOn()) applyToolOverlay(o); // Lane B: edits/annotations overload the live record
	INDEX[o.name] = o; // cache for quick-view
	return o;
}
/**
 * @param {string} name
 * @returns {Promise<Tool | null>}
 */
export async function getTool(name) {
	if (signedIn() && isNewTool(name)) return newToolBase(name);
	try {
		return normalizeTool(await apiGet(`/tools/${encodeURIComponent(name)}/`));
	} catch (error) {
		// A real 404 means the tool is absent → null (caller shows "not found").
		// Any other failure (5xx, network, parse) is an outage, not an absence —
		// rethrow so the router's error boundary surfaces it instead of the page
		// claiming the tool doesn't exist.
		if (error instanceof ApiError && error.status === 404) return null;
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
		title: l.title || "Untitled list",
		description: l.description || "",
		toolCount: tools.length,
		tools,
		featured: Boolean(l.featured)
	};
}
