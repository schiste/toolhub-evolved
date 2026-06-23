// SPDX-License-Identifier: GPL-3.0-or-later
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

export function parseHash() {
	let h = location.hash.replace(/^#/, "");
	if (!h || h === "/") return { path: "/" };
	const [path] = h.split("?");
	return { path };
}
