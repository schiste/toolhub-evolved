// SPDX-License-Identifier: GPL-3.0-or-later
import { normalizeTool, paginate } from "./api.js";
import { normStr } from "./util.js";

/**
 * @typedef {{ name?: string | null, url?: string | null, wikiUsername?: string | null }} AuthorRecord
 */

/**
 * @param {Tool} tool
 * @returns {AuthorRecord[]}
 */
function authorRecords(tool) {
	if (tool.authorObjs && tool.authorObjs.length > 0) return tool.authorObjs;
	return (tool.authors || []).map((name) => ({ name }));
}

/** @param {{ url?: string | null, wikiUsername?: string | null } | null | undefined} profile */
export function authorProfileUrl(profile) {
	if (profile && profile.url) return profile.url;
	if (profile && profile.wikiUsername) {
		return `https://meta.wikimedia.org/wiki/User:${encodeURIComponent(profile.wikiUsername)}`;
	}
	return null;
}

/**
 * @param {string} requestedName
 * @param {Tool[]} tools
 */
function entryFromTools(requestedName, tools) {
	const key = normStr(requestedName);
	/** @type {{ name: string, tools: Tool[], profile: { url?: string, wikiUsername?: string } }} */
	const entry = { name: requestedName, tools: tools || [], profile: {} };
	for (const tool of tools || []) {
		for (const author of authorRecords(tool)) {
			if (normStr(author && author.name) !== key) continue;
			entry.name = author.name || requestedName;
			if (!entry.profile.url && author.url) entry.profile.url = author.url;
			if (!entry.profile.wikiUsername && author.wikiUsername) entry.profile.wikiUsername = author.wikiUsername;
		}
	}
	return entry;
}

/** @param {string} name */
export async function toolsByAuthor(name) {
	const tools = await paginate(
		"/search/tools/",
		{ author__term: name, ordering: "-score" },
		{ pageSize: 100, maxPages: 50, map: normalizeTool }
	).catch(() => []);
	return entryFromTools(name, tools);
}
