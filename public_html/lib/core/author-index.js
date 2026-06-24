// SPDX-License-Identifier: GPL-3.0-or-later
import { loadAllTools } from "./similarity.js";
import { memoizeAsync, normStr } from "./util.js";

function authorRecords(tool) {
	if (tool.authorObjs && tool.authorObjs.length) return tool.authorObjs;
	return (tool.authors || []).map((name) => ({ name }));
}

export function authorProfileUrl(profile) {
	if (profile && profile.url) return profile.url;
	if (profile && profile.wikiUsername) return "https://meta.wikimedia.org/wiki/User:" + encodeURIComponent(profile.wikiUsername);
	return null;
}

function buildAuthorIndex(tools) {
	const index = new Map();
	for (const tool of tools || []) {
		const seenForTool = new Set();
		for (const author of authorRecords(tool)) {
			const name = author && author.name;
			const key = normStr(name);
			if (!key || seenForTool.has(key)) continue;
			seenForTool.add(key);
			if (!index.has(key)) index.set(key, { name, tools: [], profile: {} });
			const entry = index.get(key);
			if (!entry.tools.some((t) => t.name === tool.name)) entry.tools.push(tool);
			if (!entry.profile.url && author.url) entry.profile.url = author.url;
			if (!entry.profile.wikiUsername && author.wikiUsername) entry.profile.wikiUsername = author.wikiUsername;
		}
	}
	return index;
}

export const authorIndex = memoizeAsync(() => loadAllTools().then(buildAuthorIndex));

export async function toolsByAuthor(name) {
	const index = await authorIndex();
	return index.get(normStr(name)) || { name, tools: [], profile: {} };
}
