// SPDX-License-Identifier: GPL-3.0-or-later
// Real, honest trust signals derived from live Toolhub data — no simulation.
// Listing completeness, curated-list endorsement, freshness, and fit-to-your-context.
// Serves tool users (evaluate/trust) and maintainers (improve-your-listing).
import { backendGetJson, hasValue, paginate } from "./api.js";
import { toolSummaryCacheRead, toolSummaryCacheWrite } from "./store.js";
import { memoizeAsync } from "./util.js";

/* ---- Listing completeness --------------------------------------------------
   What fraction of the toolinfo a maintainer could fill is actually filled.
   Doubles as a user quality cue and a maintainer checklist. */
/** @type {Array<{ key: string, label: string, ok: (t: Tool) => boolean }>} */
const COMPLETENESS_FIELDS = [
	{ key: "description", label: "Description", ok: (t) => hasValue(t.description) && t.description.length >= 30 },
	{ key: "url", label: "Tool URL", ok: (t) => hasValue(t.url) },
	{ key: "repository", label: "Source repository", ok: (t) => hasValue(t.repository) },
	{ key: "license", label: "License", ok: (t) => hasValue(t.license) },
	{ key: "keywords", label: "Keywords", ok: (t) => (t.keywords || []).length > 0 },
	{
		key: "audienceOrTask",
		label: "Audience or task tagged",
		ok: (t) => (t.audiences || []).length > 0 || (t.tasks || []).length > 0
	},
	{ key: "docs", label: "Documentation", ok: (t) => hasValue(t.userDocs) || hasValue(t.devDocs) },
	{ key: "icon", label: "Icon", ok: (t) => hasValue(t.icon) },
	{ key: "contact", label: "Issue tracker or feedback", ok: (t) => hasValue(t.bugtracker) || hasValue(t.feedback) }
];
/** @param {Tool} t */
export function completeness(t) {
	const items = COMPLETENESS_FIELDS.map((f) => ({ key: f.key, label: f.label, ok: Boolean(f.ok(t)) }));
	const filled = items.filter((i) => i.ok).length;
	return { filled, total: items.length, items };
}

/* ---- Freshness ------------------------------------------------------------
   Is the listing recently maintained? Derived from the real modified date. */
const FRESH_MS = 18 * 30 * 24 * 60 * 60 * 1000; // ~18 months
/** @param {Tool} t */
export function freshness(t) {
	const d = t.modified ? new Date(t.modified) : null;
	if (!d || Number.isNaN(d.getTime())) return { known: false, fresh: false };
	return { known: true, fresh: Date.now() - d.getTime() < FRESH_MS };
}

/* ---- Endorsement: curated-list membership ---------------------------------
   The honest "popularity" proxy — how many published lists include the tool.
   Built from the list index. Keep a bounded browser copy because this derived
   map is safe to reuse across deploys and otherwise forces a sequential crawl
   on every fresh SPA process. */
const LIST_MEMBERSHIPS_CACHE_KEY = "toolhub-list-memberships:v1";
const LIST_MEMBERSHIPS_FRESH_MS = 15 * 60 * 1000;
const LIST_MEMBERSHIPS_STALE_MS = 24 * 60 * 60 * 1000;
const LIST_MEMBERSHIPS_MAX_CHARS = 450000;

/**
 * @returns {{ map: Map<string, Array<{ id: string, title: string }>>, ageMs: number } | null}
 */
function readMembershipCache() {
	try {
		const raw = JSON.parse(localStorage.getItem(LIST_MEMBERSHIPS_CACHE_KEY) || "null");
		if (!raw || typeof raw.ts !== "number" || !Array.isArray(raw.entries)) return null;
		const ageMs = Date.now() - raw.ts;
		if (ageMs < 0 || ageMs > LIST_MEMBERSHIPS_STALE_MS) return null;
		const map = new Map();
		for (const entry of raw.entries) {
			if (!Array.isArray(entry) || typeof entry[0] !== "string" || !Array.isArray(entry[1])) continue;
			const lists = entry[1]
				.filter(
					(list) =>
						list &&
						(typeof list.id === "string" || typeof list.id === "number") &&
						typeof list.title === "string"
				)
				.map((list) => ({ id: String(list.id), title: list.title }));
			map.set(entry[0], lists);
		}
		return { map, ageMs };
	} catch {
		return null;
	}
}

/** @param {Map<string, Array<{ id: string, title: string }>>} map */
function writeMembershipCache(map) {
	try {
		const payload = JSON.stringify({ ts: Date.now(), entries: [...map.entries()] });
		if (payload.length <= LIST_MEMBERSHIPS_MAX_CHARS) {
			localStorage.setItem(LIST_MEMBERSHIPS_CACHE_KEY, payload);
		}
	} catch {}
}

async function buildMemberships() {
	const map = new Map();
	const lists = await paginate("/lists/", {}, { pageSize: 50, maxPages: 10 });
	for (const l of lists) {
		if (l.published === false) continue; // count only public/curated lists
		// Stryker disable next-line ArrayDeclaration: the `|| []` fallback only triggers for tool-less lists; a non-empty fallback array's string element has no `.name`, so it is skipped by the `if (!name)` guard — same result as the empty fallback.
		for (const tool of l.tools || []) {
			const name = tool && tool.name;
			if (!name) continue;
			if (!map.has(name)) map.set(name, []);
			map.get(name).push({ id: l.id, title: l.title || "Untitled list" });
		}
	}
	return map;
}
// Returns Map<toolName, [{id,title}]>; memoized for the session. A stale
// browser map is returned immediately while a background rebuild updates the
// next page load, keeping derived badges non-blocking after deploys.
/** @type {Map<string, Array<{ id: string, title: string }>> | null} */
let seededMemberships = null;
/**
 * Prime the membership map from a payload the server already composed.
 *
 * The landing page used to derive this itself by crawling every page of
 * /api/lists/ — two requests that also gated the most-listed ordering.
 * @param {Record<string, Array<{ id: string, title: string }>>} endorsements
 * @returns {void}
 */
export function seedListMemberships(endorsements) {
	const map = new Map();
	for (const [name, lists] of Object.entries(endorsements || {})) {
		if (name && Array.isArray(lists)) map.set(name, lists);
	}
	if (map.size === 0) return;
	writeMembershipCache(map);
	// listMemberships() is memoized for the session, so the seed has to be what
	// that memo resolves to — otherwise the deferred crawl still runs.
	seededMemberships = map;
}
export const listMemberships = memoizeAsync(async () => {
	if (seededMemberships) return seededMemberships;
	const cached = readMembershipCache();
	if (cached) {
		if (cached.ageMs > LIST_MEMBERSHIPS_FRESH_MS) {
			buildMemberships()
				.then(writeMembershipCache)
				.catch(() => {});
		}
		return cached.map;
	}
	const map = await buildMemberships().catch(() => new Map());
	if (map.size > 0) writeMembershipCache(map);
	return map;
});
/**
 * @param {string} name
 * @param {Map<string, Array<{ id: string, title: string }>>} map
 */
export function endorsementOf(name, map) {
	const lists = (map && map.get(name)) || [];
	return { count: lists.length, lists };
}

/* ---- Fit to your context --------------------------------------------------
   Honest local personalization: who you are / where you work. Stored on its own
   key so it persists independently of the experimental Lane-B overlay (and is
   never wiped by overlay/account cleanup). Fit is an EXPLICIT match (a tool that names
   your wiki or your audience), so the cue stays meaningful rather than universal. */
const CONTEXT_KEY = "toolhub-context";
/** @returns {UserContext} */
export function getUserContext() {
	try {
		return JSON.parse(/** @type {string} */ (localStorage.getItem(CONTEXT_KEY))) || {};
	} catch {
		return {};
	}
}
/** @param {UserContext | null | undefined} ctx */
export function setUserContext(ctx) {
	try {
		if (ctx && (ctx.wiki || ctx.role)) {
			localStorage.setItem(CONTEXT_KEY, JSON.stringify({ wiki: ctx.wiki || "", role: ctx.role || "" }));
		} else {
			localStorage.removeItem(CONTEXT_KEY);
		}
	} catch {}
}
export function hasContext() {
	const c = getUserContext();
	return Boolean(c.wiki || c.role);
}
// Wiki match is explicit: an exact id, or a "*.suffix" family entry (e.g.
// "*.wikipedia.org" fits "en.wikipedia.org"). "*" (all wikis) is NOT a specific
// fit, so the cue stays meaningful instead of matching everything.
/**
 * @param {string[]} forWikis
 * @param {string} wiki
 */
export function wikiMatches(forWikis, wiki) {
	// Stryker disable next-line ArrayDeclaration: forWikis is always an array from normalizeTool; the `|| []` fallback only fires for a null forWikis, and a non-empty fallback's sentinel string can only match the impossible wiki id "Stryker was here".
	return (forWikis || []).some((w) => w === wiki || (w.startsWith("*.") && wiki.endsWith(w.slice(1))));
}
/**
 * @param {Tool} t
 * @param {UserContext} [ctx]
 */
export function fitsContext(t, ctx) {
	const activeCtx = ctx || getUserContext();
	const wiki = activeCtx.wiki ? wikiMatches(t.forWikis, activeCtx.wiki) : false;
	// Stryker disable next-line ArrayDeclaration: t.audiences is always an array from normalizeTool; the `|| []` fallback only fires for a tool lacking audiences, and the mutated sentinel only matches the impossible role "Stryker was here".
	const role = activeCtx.role ? (t.audiences || []).includes(activeCtx.role) : false;
	return { wiki, role, fits: wiki || role };
}

/* ---- View helpers (shared by the card-grid views) ------------------------- */
// Stable-sort tools so context-fitting ones lead, but only when a context is
// set (otherwise the original order is preserved). Fit is computed once per tool.
/** @param {Tool[]} tools */
export function rankFitsFirst(tools) {
	if (!hasContext()) return tools;
	const fit = new Map(tools.map((t) => /** @type {[Tool, number]} */ ([t, fitsContext(t).fits ? 1 : 0])));
	// Stryker disable ArithmeticOperator: the `a[1] - b[1]` index tiebreak only orders items within an equal-fit group by original position, which V8's stable sort already preserves; `a[1] + b[1]` (always >= 0) leaves that stable order intact, so it is equivalent.
	return tools
		.map((t, i) => /** @type {[Tool, number]} */ ([t, i]))
		.sort((a, b) => (fit.get(b[0]) || 0) - (fit.get(a[0]) || 0) || a[1] - b[1])
		.map((x) => x[0]);
	// Stryker restore ArithmeticOperator
}
// Attach `.endorsement` to each tool from the (memoized) membership map.
/**
 * @param {Tool[]} tools
 * @param {{ defer?: boolean }} [opts]
 */
export async function attachEndorsements(tools, opts = {}) {
	if (opts.defer) {
		const cached = readMembershipCache();
		const lm = cached ? cached.map : new Map();
		for (const t of tools) /** @type {any} */ (t).endorsement = endorsementOf(t.name, lm);
		// A cold membership cache must never hold up a route. listMemberships()
		// deduplicates the crawl; the event lets the active view repaint counts.
		listMemberships()
			.then((fresh) => {
				for (const t of tools) /** @type {any} */ (t).endorsement = endorsementOf(t.name, fresh);
				if (typeof document !== "undefined") {
					document.dispatchEvent(new CustomEvent("toolhub:endorsements-refresh"));
				}
			})
			.catch(() => {});
		return tools;
	}
	const lm = await listMemberships();
	// `endorsement` is a view-attached extra not declared on the Tool interface.
	for (const t of tools) /** @type {any} */ (t).endorsement = endorsementOf(t.name, lm);
	return tools;
}

const EVOLVED_SUMMARY_TTL_MS = 5 * 60 * 1000;
/* How long to leave a not-yet-materialized summary alone. Long enough that a
   render loop cannot form, short enough that the background builder's results
   still show up on the next navigation. */
const EVOLVED_SUMMARY_MISSING_BACKOFF_MS = 60 * 1000;
/* How long a route may wait for summaries it does not already have before
   painting without them. The endpoint reads only local data, so this covers a
   normal round trip with room to spare while staying well inside the page's
   own load budget. */
export const EVOLVED_SUMMARY_GRACE_MS = 250;
const EVOLVED_SUMMARY_BATCH_SIZE = 24;
const EVOLVED_SUMMARY_IDLE_TIMEOUT_MS = 2200;
const EVOLVED_SUMMARY_IDLE_FALLBACK_MS = 700;
/** @type {Map<string, { summary: any, ts: number }>} */
const evolvedSummaryCache = new Map();
/* Names the backend has no materialized summary for yet, with the time we last
   asked. Without this, "not in the response" reads as "still stale" and every
   render asks again — and because each answer that carries any new summary
   emits a refresh event, and that event re-renders the whole route, the route's
   own requests are re-issued too. That is a feedback loop with no damping: it
   was re-requesting /v1/me/tools/ about 1.5 times a second, which is what
   saturated the webservice. Backing off makes the loop terminate. */
/** @type {Map<string, number>} */
const evolvedSummaryMissing = new Map();
/** @type {Map<string, Promise<void>>} */
const evolvedSummaryInflight = new Map();
let evolvedSummaryHydrated = false;
/**
 * Pull summaries stored by an earlier page load into the in-memory map, so the
 * first render of a route can already carry health scores. Called at the point
 * of use rather than on import: a route that shows no tool cards should not pay
 * for the parse.
 * @returns {void}
 */
function hydrateEvolvedSummaries() {
	if (evolvedSummaryHydrated) return;
	evolvedSummaryHydrated = true;
	for (const [name, entry] of Object.entries(toolSummaryCacheRead())) {
		if (!evolvedSummaryCache.has(name)) evolvedSummaryCache.set(name, entry);
	}
}
let evolvedSummaryPersistScheduled = false;
/** @returns {void} */
function persistEvolvedSummaries() {
	if (evolvedSummaryPersistScheduled) return;
	evolvedSummaryPersistScheduled = true;
	scheduleIdle(() => {
		evolvedSummaryPersistScheduled = false;
		toolSummaryCacheWrite(Object.fromEntries(evolvedSummaryCache));
	});
}
/**
 * @param {any} a
 * @param {any} b
 * @returns {boolean}
 */
function sameSummary(a, b) {
	try {
		return JSON.stringify(a) === JSON.stringify(b);
	} catch {
		return false;
	}
}
/**
 * Prime summaries from a payload the server already composed, so the landing
 * page does not need the second round trip that used to follow the tool list.
 * @param {Record<string, any>} summaries
 * @returns {void}
 */
export function seedEvolvedSummaries(summaries) {
	const ts = Date.now();
	let seeded = false;
	for (const [name, summary] of Object.entries(summaries || {})) {
		if (!name || !summary) continue;
		evolvedSummaryMissing.delete(name);
		evolvedSummaryCache.set(name, { summary, ts });
		seeded = true;
	}
	// Keep what the landing page composed, so the next route reuses it instead
	// of asking for the same summaries again.
	if (seeded) persistEvolvedSummaries();
}
/** @type {Set<string>} */
const evolvedSummaryPending = new Set();
let evolvedSummaryScheduled = false;

/** @param {string[]} names */
function emitEvolvedSummaryRefresh(names) {
	if (typeof document === "undefined" || typeof CustomEvent === "undefined") return;
	document.dispatchEvent(new CustomEvent("toolhub:evolved-summaries-refresh", { detail: { names } }));
}

/**
 * @param {string[]} names
 * @param {{ emit?: boolean, emitWhen?: () => boolean }} [opts]
 * @returns {Promise<void>}
 */
function refreshEvolvedSummaries(names, opts = {}) {
	/** @type {Array<Promise<void>>} */
	const pending = [];
	/** @type {string[]} */
	const batch = [];
	for (const name of names) {
		if (!name) continue;
		const inflight = evolvedSummaryInflight.get(name);
		if (inflight) pending.push(inflight);
		else batch.push(name);
		if (batch.length >= EVOLVED_SUMMARY_BATCH_SIZE) break;
	}
	if (batch.length === 0) return Promise.allSettled(pending).then(() => undefined);
	const params = new URLSearchParams({ names: batch.join(",") });
	const request = backendGetJson(`/v1/tools/summaries/?${params.toString()}`)
		.then((data) => {
			const results = data && typeof data.results === "object" ? data.results : {};
			const updated = [];
			let stored = false;
			for (const name of batch) {
				const summary = results[name];
				if (!summary) {
					// Not materialized yet. Remember that, so the next render does
					// not ask again immediately — see evolvedSummaryMissing.
					evolvedSummaryMissing.set(name, Date.now());
					continue;
				}
				const previous = evolvedSummaryCache.get(name);
				evolvedSummaryMissing.delete(name);
				evolvedSummaryCache.set(name, { summary, ts: Date.now() });
				stored = true;
				// Now that summaries survive the page, most refreshes confirm the
				// score already on screen. Emitting for those would repaint the
				// whole route to draw the same number, so only report changes.
				if (!previous || !sameSummary(previous.summary, summary)) updated.push(name);
			}
			if (stored) persistEvolvedSummaries();
			// Decided at resolution time, not call time: a caller that waited for
			// this and gave up needs the late answer to repaint, while one that
			// got it before rendering does not.
			const shouldEmit = opts.emitWhen ? opts.emitWhen() : opts.emit !== false;
			if (shouldEmit && updated.length > 0) emitEvolvedSummaryRefresh(updated);
		})
		.catch(() => {
			// Health summaries are additive; cards remain valid without them.
		})
		.finally(() => {
			for (const name of batch) {
				if (evolvedSummaryInflight.get(name) === request) evolvedSummaryInflight.delete(name);
			}
		});
	for (const name of batch) evolvedSummaryInflight.set(name, request);
	pending.push(request);
	return Promise.allSettled(pending).then(() => undefined);
}

/** @param {() => void} callback */
function scheduleIdle(callback) {
	if (typeof requestIdleCallback === "function") {
		requestIdleCallback(callback, { timeout: EVOLVED_SUMMARY_IDLE_TIMEOUT_MS });
	} else {
		setTimeout(callback, EVOLVED_SUMMARY_IDLE_FALLBACK_MS);
	}
}

function drainScheduledEvolvedSummaries() {
	evolvedSummaryScheduled = false;
	const batch = [...evolvedSummaryPending].slice(0, EVOLVED_SUMMARY_BATCH_SIZE);
	for (const name of batch) evolvedSummaryPending.delete(name);
	refreshEvolvedSummaries(batch).finally(() => {
		if (evolvedSummaryPending.size > 0) scheduleEvolvedSummaryRefresh([]);
	});
}

/** @param {string[]} names */
function scheduleEvolvedSummaryRefresh(names) {
	for (const name of names) {
		if (name) evolvedSummaryPending.add(name);
	}
	if (evolvedSummaryScheduled || evolvedSummaryPending.size === 0) return;
	evolvedSummaryScheduled = true;
	scheduleIdle(drainScheduledEvolvedSummaries);
}

/**
 * Attach local Evolved health/maintainer summaries for visible tool cards.
 * The endpoint reads only Evolved's local database, so this never blocks on
 * official Toolhub after the canonical/summary cache has been populated.
 * Only the name is read, so a caller that has one before it has the record —
 * the tool route, which takes it from the URL — can start this early.
 *
 * `graceMs` is the cache-first mode: whatever is already known attaches
 * synchronously, the rest is given a short bounded wait so it can make the
 * first paint, and anything slower than that arrives as a normal background
 * refresh. Use it on routes that render tool cards; it degrades to today's
 * deferred behaviour rather than holding up the page.
 * @template {{ name: string }} T
 * @param {T[]} tools
 * @param {{ waitForFresh?: boolean, defer?: boolean, graceMs?: number }} [opts]
 * @returns {Promise<T[]>}
 */
export async function attachEvolvedSummaries(tools, opts = {}) {
	const names = [...new Set((tools || []).map((tool) => tool && tool.name).filter(Boolean))].slice(0, 50);
	if (names.length === 0) return tools;
	// Before deciding what is stale, recover what an earlier page load stored:
	// these attach synchronously below and so land in the first paint.
	hydrateEvolvedSummaries();
	const now = Date.now();
	const stale = [];
	for (const tool of tools) {
		const cached = evolvedSummaryCache.get(tool.name);
		if (cached) /** @type {any} */ (tool).evolvedSummary = cached.summary;
		if (cached && now - cached.ts <= EVOLVED_SUMMARY_TTL_MS) continue;
		// A name the backend has already told us it has not materialized is not
		// worth re-asking on every render; wait out the backoff first.
		const askedAt = evolvedSummaryMissing.get(tool.name);
		if (askedAt !== undefined && now - askedAt <= EVOLVED_SUMMARY_MISSING_BACKOFF_MS) continue;
		stale.push(tool.name);
	}
	if (opts.graceMs !== undefined) {
		// Nothing stale resolves immediately, so a fully cached route pays no
		// grace period at all.
		let late = false;
		const pending = refreshEvolvedSummaries(stale, { emitWhen: () => late });
		/** @type {ReturnType<typeof setTimeout> | undefined} */
		let timer;
		await Promise.race([
			pending.finally(() => clearTimeout(timer)),
			new Promise((resolve) => {
				timer = setTimeout(resolve, opts.graceMs);
			})
		]);
		// Past this point the answer is too late for the first paint, so let it
		// repaint instead of arriving silently.
		late = true;
		for (const tool of tools) {
			const cached = evolvedSummaryCache.get(tool.name);
			if (cached) /** @type {any} */ (tool).evolvedSummary = cached.summary;
		}
	} else if (opts.waitForFresh) {
		await refreshEvolvedSummaries(stale, { emit: false });
		for (const tool of tools) {
			const cached = evolvedSummaryCache.get(tool.name);
			if (cached) /** @type {any} */ (tool).evolvedSummary = cached.summary;
		}
	} else if (opts.defer === false) {
		refreshEvolvedSummaries(stale);
	} else {
		scheduleEvolvedSummaryRefresh(stale);
	}
	return tools;
}
