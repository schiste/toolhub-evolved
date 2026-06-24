// SPDX-License-Identifier: GPL-3.0-or-later
export function toolHref(name) { return `#/tools/${encodeURIComponent(name)}`; }
export function listHref(id) { return `#/lists/${encodeURIComponent(id)}`; }
export function authorHref(name) { return `#/by/${encodeURIComponent(name)}`; }
export function graphHref() { return "#/graph"; }
/* ------------------------------------------------------------- static cfg */
// Personas = WHO you are → real `audiences` facet values (audiences__term).
export const PERSONAS = [
	["edit", "Editors", "editor"], ["code", "Developers", "developer"],
	["book", "Readers", "reader"], ["research", "Researchers", "researcher"],
	["admin", "Admins", "admin"], ["group", "Organizers", "organizer"],
];
// Needs = WHAT you want to do → real `tasks` facet values (tasks__term).
export const NEEDS = [
	["edit", "Edit content", "editing"], ["add", "Create content", "creating"],
	["tag", "Categorize content", "categorizing"], ["upload", "Upload media", "uploading"],
	["analyze", "Analyze data", "analysis"], ["convert", "Convert & transform", "converting"],
	["book", "Read & browse", "reading"],
];

export function parseHash() {
	let h = location.hash.replace(/^#/, "");
	if (!h || h === "/") return { path: "/" };
	const [path] = h.split("?");
	return { path };
}
