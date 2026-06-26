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
	// Stryker disable next-line ConditionalExpression,LogicalOperator,EqualityOperator: tools only reach here via toolsByAuthor → normalizeTool, which guarantees authorObjs and authors are simultaneously empty or populated and that authorObjs carries a superset of the data. Given that invariant, only the false-variant (always-fallback, dropping url/wiki) is behavioral — and it is killed by the profile assertions; the remaining guard mutants are output-equivalent.
	if (tool.authorObjs && tool.authorObjs.length > 0) return tool.authorObjs;
	// Stryker disable next-line LogicalOperator,ArrayDeclaration,ArrowFunction,ObjectLiteral: the fallback only runs for author-less tools (authors === []), so the `|| []` default, its map callback, and the `{ name }` object are never evaluated with data; only the conditional-collapse (true.map throwing) is observable and is killed by the author-less tool test.
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
	// Stryker disable next-line ArrayDeclaration: toolsByAuthor always passes an array (paginate result or [] from .catch), so the `|| []` fallback array is never used.
	const entry = { name: requestedName, tools: tools || [], profile: {} };
	// Stryker disable next-line ArrayDeclaration: `tools` is always an array here, so the `|| []` fallback array is never used.
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
	// Stryker disable ArrowFunction: the .catch handler is reachable only if paginate rejects (a normalizeTool throw), and there `() => []` vs `() => undefined` is indistinguishable because entryFromTools normalizes the arg with `tools || []`.
	const tools = await paginate(
		"/search/tools/",
		{ author__term: name, ordering: "-score" },
		{ pageSize: 100, maxPages: 50, map: normalizeTool }
	).catch(() => []);
	// Stryker restore ArrowFunction
	return entryFromTools(name, tools);
}
