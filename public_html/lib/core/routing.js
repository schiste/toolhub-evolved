// SPDX-License-Identifier: GPL-3.0-or-later
/** @param {string} name */
export function toolHref(name) {
	return `/tools/${encodeURIComponent(name)}`;
}
/** @param {string} id */
export function listHref(id) {
	return `/lists/${encodeURIComponent(id)}`;
}
/** @param {string} name */
export function authorHref(name) {
	return `/by/${encodeURIComponent(name)}`;
}
/* ------------------------------------------------------------- static cfg */
// Personas = WHO you are → real `audiences` facet values (audiences__term).
export const PERSONAS = [
	["edit", "Editors", "editor"],
	["code", "Developers", "developer"],
	["book", "Readers", "reader"],
	["research", "Researchers", "researcher"],
	["admin", "Admins", "admin"],
	["group", "Organizers", "organizer"]
];
// Needs = WHAT you want to do → real `tasks` facet values (tasks__term).
export const NEEDS = [
	["edit", "Edit content", "editing"],
	["add", "Create content", "creating"],
	["tag", "Categorize content", "categorizing"],
	["upload", "Upload media", "uploading"],
	["analyze", "Analyze data", "analysis"],
	["convert", "Convert & transform", "converting"],
	["book", "Read & browse", "reading"]
];

export function parseRoute() {
	// Stryker disable next-line StringLiteral: location.pathname is never the empty string in a browser (it is at minimum "/"), so the `|| "/"` fallback is unreachable.
	const path = location.pathname || "/";
	// Stryker disable next-line ConditionalExpression,StringLiteral: `path` is never "" (the `|| "/"` above guarantees it), so the `path === ""` branch is dead code — the ternary always returns `path`.
	return { path: path === "" ? "/" : path };
}

export function normalizeLegacyHashRoute() {
	if (!location.hash.startsWith("#/")) return false;
	// Stryker disable next-line StringLiteral: the 2nd arg is the legacy (ignored) history title; mutating it has no observable effect.
	history.replaceState({}, "", location.hash.slice(1));
	return true;
}

/**
 * @param {string} href
 * @param {{ replace?: boolean }} [opts]
 */
export function navigateTo(href, opts = {}) {
	const url = new URL(href, location.href);
	if (url.origin !== location.origin) {
		location.href = href;
		return;
	}
	const next = url.pathname + url.search;
	const current = location.pathname + location.search;
	if (next !== current) {
		// Stryker disable next-line StringLiteral: the 2nd arg is the legacy (ignored) history title; mutating it has no observable effect. (The method-name strings are exercised by the push/replace tests.)
		history[opts.replace ? "replaceState" : "pushState"]({}, "", next);
	}
	window.dispatchEvent(new Event("toolhub:navigate"));
}
