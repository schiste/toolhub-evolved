// SPDX-License-Identifier: GPL-3.0-or-later
// Real, honest trust signals derived from live Toolhub data — no simulation.
// Listing completeness, curated-list endorsement, freshness, and fit-to-your-context.
// Serves tool users (evaluate/trust) and maintainers (improve-your-listing).
import { hasValue, paginate } from "./api.js";
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
   Built once per session from the (small) set of lists; the list index embeds
   each list's tools, so this is a couple of (SWR-cached) calls, memoized here. */
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
// Returns Map<toolName, [{id,title}]>; memoized for the session.
// Stryker disable next-line ArrowFunction: buildMemberships never rejects (paginate swallows per-page errors), so this .catch is unreachable; memoizeAsync also caches the single outcome, so the success and failure paths cannot both be exercised.
export const listMemberships = memoizeAsync(() => buildMemberships().catch(() => new Map()));
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
   never wiped by "Reset demo data"). Fit is an EXPLICIT match (a tool that names
   your wiki or your audience), so the cue stays meaningful rather than universal. */
const CONTEXT_KEY = "toolhub-context";
export function getUserContext() {
	try {
		return JSON.parse(/** @type {string} */ (localStorage.getItem(CONTEXT_KEY))) || {};
	} catch {
		return {};
	}
}
/** @param {{ wiki?: string, role?: string } | null | undefined} ctx */
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
 * @param {{ wiki?: string, role?: string }} [ctx]
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
/** @param {Tool[]} tools */
export async function attachEndorsements(tools) {
	const lm = await listMemberships();
	// `endorsement` is a view-attached extra not declared on the Tool interface.
	for (const t of tools) /** @type {any} */ (t).endorsement = endorsementOf(t.name, lm);
	return tools;
}
