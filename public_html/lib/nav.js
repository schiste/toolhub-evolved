// SPDX-License-Identifier: GPL-3.0-or-later
import { dirAttrs, esc } from "./dom.js";
import { fmt } from "./i18n.js";
import { signedIn } from "./account.js";

export function toolHref(name) { return `#/tools/${encodeURIComponent(name)}`; }
export function listHref(id) { return `#/lists/${encodeURIComponent(id)}`; }
/* ------------------------------------------------------------- static cfg */
// Personas = WHO you are → real `audiences` facet values (audiences__term).
export const PERSONAS = [
	["✏️", "Editors", "editor"], ["💻", "Developers", "developer"],
	["📖", "Readers", "reader"], ["🔬", "Researchers", "researcher"],
	["🛡️", "Admins", "admin"], ["👥", "Organizers", "organizer"],
];
// Needs = WHAT you want to do → real `tasks` facet values (tasks__term).
export const NEEDS = [
	["✏️", "Edit content", "editing"], ["✨", "Create content", "creating"],
	["🗂️", "Categorize content", "categorizing"], ["🖼️", "Upload media", "uploading"],
	["📊", "Analyze data", "analysis"], ["🔄", "Convert & transform", "converting"],
	["📖", "Read & browse", "reading"],
];
export const STEPS = [
	["🔍", "1. Find a tool", "Search or browse by task, audience or category."],
	["🔖", "2. Try it out", "Most tools are free and open for everyone."],
	["💬", "3. Learn & connect", "Read docs, join discussions and ask for help."],
	["❤️", "4. Contribute back", "Share feedback or submit a tool for others."],
];

/* ---- Search / Browse (T2): facets + sort + pagination ------------------ */
export const FACET_BUCKET_LIMIT = 10;
// Facet groups we surface (a subset of the API's 11), in display order.
export const FACET_GROUPS = [
	{ field: "tool_type", label: "Tool type" }, { field: "keywords", label: "Keywords" },
	{ field: "audiences", label: "Audience" }, { field: "tasks", label: "Task" },
	{ field: "ui_language", label: "Interface language" },
	{ field: "license", label: "License" }, { field: "wiki", label: "Works on wiki" },
];
export function renderFacetGroup(g, facets, selected) {
	const wrap = facets && facets["_filter_" + g.field];
	const inner = wrap && wrap[g.field];
	if (!inner) return "";
	const param = inner.meta && inner.meta.param;
	const buckets = (inner.buckets || []).filter((b) => b.key !== "--" && b.doc_count > 0).slice(0, FACET_BUCKET_LIMIT);
	if (!buckets.length || !param) return "";
	const rows = buckets.map((b) => {
		const checked = selected.has(param + "=" + b.key) ? " checked" : "";
		return `<label class="facet"><input type="checkbox" data-facet="${esc(param)}" value="${esc(b.key)}"${checked}> <span${dirAttrs(b.key)}>${esc(b.key)}</span> <span class="facet__n">${fmt(b.doc_count)}</span></label>`;
	}).join("");
	return `<div class="facet-group"><h2 class="facet-group__title">${esc(g.label)}</h2>${rows}</div>`;
}
export function renderPager(page, pages) {
	if (pages <= 1) return "";
	const btn = (p, label, dis, cur) => `<button class="pager__btn${cur ? " is-current" : ""}" type="button" ${dis ? "disabled" : ""} data-page="${p}"${cur ? ' aria-current="page"' : ""}>${label}</button>`;
	let out = btn(page - 1, "‹ Prev", page <= 1), last = 0;
	const win = [];
	for (let p = 1; p <= pages; p++) if (p === 1 || p === pages || Math.abs(p - page) <= 2) win.push(p);
	win.forEach((p) => { if (p - last > 1) out += '<span class="pager__gap">…</span>'; out += btn(p, p, false, p === page); last = p; });
	return out + btn(page + 1, "Next ›", page >= pages);
}
export function parseHash() {
	let h = location.hash.replace(/^#/, "");
	if (!h || h === "/") return { path: "/" };
	const [path] = h.split("?");
	return { path };
}
let signInFallback = null;
export function setSignInFallback(fn) { signInFallback = fn; }
export function requireSignIn(viewFn, title, lead) { return signedIn() ? viewFn() : signInFallback(title, lead); }
