// SPDX-License-Identifier: GPL-3.0-or-later
import { normalizeTool, paginate } from "./api.js";
import { normStr } from "./util.js";

function authorRecords(tool) {
	if (tool.authorObjs && tool.authorObjs.length) return tool.authorObjs;
	return (tool.authors || []).map((name) => ({ name }));
}

export function authorProfileUrl(profile) {
	if (profile && profile.url) return profile.url;
	if (profile && profile.wikiUsername) return "https://meta.wikimedia.org/wiki/User:" + encodeURIComponent(profile.wikiUsername);
	return null;
}

function entryFromTools(requestedName, tools) {
	const key = normStr(requestedName);
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

export async function toolsByAuthor(name) {
	const tools = await paginate("/search/tools/", { author__term: name, ordering: "-score" }, { pageSize: 100, maxPages: 50, map: normalizeTool })
		.catch(() => []);
	return entryFromTools(name, tools);
}
