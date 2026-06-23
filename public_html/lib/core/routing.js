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
	["🔍", "1. Find a tool", "Search, or browse by the task, audience, or wiki you work on."],
	["🔖", "2. Open it", "Most tools run in the browser with your Wikimedia login — nothing to install."],
	["💬", "3. Ask and learn", "Read the docs, join the discussion, and get help from maintainers."],
	["❤️", "4. Contribute back", "Report an issue, suggest an edit, or publish your own tool."],
];

export function parseHash() {
	let h = location.hash.replace(/^#/, "");
	if (!h || h === "/") return { path: "/" };
	const [path] = h.split("?");
	return { path };
}
