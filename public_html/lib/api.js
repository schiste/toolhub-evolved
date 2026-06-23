// SPDX-License-Identifier: GPL-3.0-or-later
import { expOn, signedIn, USER } from "./account.js";
import { toolEditsMap, toolAnnosMap, toolNewMap } from "./store.js";
import { synthViews } from "./synth.js";

export function isNewTool(name) { return !!toolNewMap()[name]; }
export function applyToolOverlay(o) {
	const e = toolEditsMap()[o.name]; if (e) { Object.assign(o, e); o.edited = true; }
	const a = toolAnnosMap()[o.name]; if (a) { Object.assign(o, a); o.annotated = true; }
	if (e || a) o.status = statusOf(o); // flags may have changed
	return o;
}
// Build a compact tool object for a net-new demo submission, then overlay edits.
export function newToolBase(name) {
	const rec = toolNewMap()[name]; if (!rec) return null;
	const o = Object.assign({
		name, keywords: [], authors: [], audiences: [], tasks: [], forWikis: [], uiLanguages: [],
		technologyUsed: [], maintainer: USER.name, deprecated: false, experimental: false, origin: "api",
	}, rec);
	o.weeklyViews = synthViews(name);
	o.status = statusOf(o);
	INDEX[name] = o;
	return applyToolOverlay(o);
}
export function statusOf(t) { return t.deprecated ? { level: "red", label: "Deprecated" } : t.experimental ? { level: "yellow", label: "Experimental" } : { level: "green", label: "Healthy" }; }
/* Tool cache for O(1) detail / quick-view lookups; filled by normalizeTool()
   as live data arrives (search results, lists, tool pages). No snapshot. */
export const INDEX = {};

/* ===================================================================== LIVE API
   Every read goes through the same-origin proxy (/api → toolhub.wikimedia.org/api).
   Tool/list objects are normalized to the compact shape the views/cards expect.
   There is no bundled snapshot — the catalog is always the live one. */
export const API_BASE = "/api";
export async function apiGet(path, params) {
	const qs = params ? "?" + new URLSearchParams(params).toString() : "";
	const res = await fetch(API_BASE + path + qs, { headers: { Accept: "application/json" } });
	if (!res.ok) throw new Error("API " + res.status + " " + path);
	return res.json();
}
export function firstUrl(v) {
	if (!v) return null;
	if (typeof v === "string") return v;
	if (Array.isArray(v) && v.length) { const x = v[0]; return x && typeof x === "object" ? x.url : x; }
	return null;
}
export function hasValue(v) { return Array.isArray(v) ? v.length > 0 : v != null && v !== ""; }
export function pick(core, annotation, fallback) {
	if (hasValue(core)) return core;
	if (hasValue(annotation)) return annotation;
	return fallback;
}
export function normalizeTool(t) {
	const ann = t.annotations || {};
	const ra = t.author;
	const authors = Array.isArray(ra)
		? ra.map((a) => (a && a.name) || (typeof a === "string" ? a : null)).filter(Boolean)
		: typeof ra === "string" && ra ? [ra] : [];
	const o = {
		name: t.name, title: t.title || t.name, description: t.description || "", url: pick(t.url, ann.url, ""), icon: pick(t.icon, ann.icon, null),
		keywords: t.keywords || [], maintainer: authors[0] || (t.created_by && t.created_by.username) || "Unknown", authors,
		toolType: pick(t.tool_type, ann.tool_type, null), license: pick(t.license, ann.license, null),
		repository: pick(t.repository, ann.repository, null), apiUrl: pick(t.api_url, ann.api_url, null),
		technologyUsed: pick(t.technology_used, ann.technology_used, []),
		audiences: pick(t.audiences, ann.audiences, []), tasks: pick(t.tasks, ann.tasks, []),
		forWikis: pick(t.for_wikis, ann.for_wikis, []), uiLanguages: pick(t.available_ui_languages, ann.available_ui_languages, []),
		userDocs: firstUrl(pick(t.user_docs_url, ann.user_docs_url, [])),
		devDocs: firstUrl(pick(t.developer_docs_url, ann.developer_docs_url, [])),
		feedback: firstUrl(pick(t.feedback_url, ann.feedback_url, [])),
		bugtracker: pick(t.bugtracker_url, ann.bugtracker_url, null), translate: pick(t.translate_url, ann.translate_url, null),
		deprecated: !!(t.deprecated || ann.deprecated), experimental: !!(t.experimental || ann.experimental), modified: t.modified_date || t.modified || null,
		origin: t.origin || "crawler",
	};
	o.weeklyViews = synthViews(o.name);
	o.status = statusOf(o);
	if (expOn()) applyToolOverlay(o); // Lane B: edits/annotations overload the live record
	INDEX[o.name] = o; // cache for quick-view
	return o;
}
export async function getTool(name) {
	if (signedIn() && isNewTool(name)) return newToolBase(name);
	try { return normalizeTool(await apiGet("/tools/" + encodeURIComponent(name) + "/")); }
	catch (e) { return null; }
}
export async function getToolsByName(names) { return (await Promise.all((names || []).map(getTool))).filter(Boolean); }
export function normalizeList(l) {
	const tools = (l.tools || []).map(normalizeTool);
	return {
		id: l.id, title: l.title || "Untitled list", description: l.description || "",
		toolCount: tools.length, tools, featured: !!l.featured,
	};
}
