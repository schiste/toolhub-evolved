// SPDX-License-Identifier: GPL-3.0-or-later
import { backendGetJson, normalizeTool } from "./api.js";

/** @param {string} toolName */
export function peopleForTool(toolName) {
	return backendGetJson(`/v1/people/tools/${encodeURIComponent(toolName)}/`);
}

/** @param {string} publicId @param {{toolPage?: number, toolPageSize?: number}} [options] */
export function personById(publicId, options = {}) {
	const params = new URLSearchParams();
	if (options.toolPage && options.toolPage > 1) params.set("tool_page", String(options.toolPage));
	if (options.toolPageSize) params.set("tool_page_size", String(options.toolPageSize));
	return backendGetJson(`/v1/people/${encodeURIComponent(publicId)}/${params.size > 0 ? `?${params}` : ""}`);
}

/**
 * @typedef {{q?: string, page?: number, pageSize?: number, role?: string, verification?: string, activity?: string, project?: string, ordering?: string, contributor?: string}} PeopleDirectorySearch
 */

/** @param {PeopleDirectorySearch} search */
function directoryParams(search) {
	const params = new URLSearchParams();
	if (search.q) params.set("q", search.q);
	if (search.page && search.page > 1) params.set("page", String(search.page));
	if (search.pageSize) params.set("page_size", String(search.pageSize));
	for (const key of ["role", "verification", "activity", "project", "ordering", "contributor"]) {
		const value = search[/** @type {keyof PeopleDirectorySearch} */ (key)];
		if (value) params.set(key, String(value));
	}
	return params;
}

/**
 * Search the public community directory without exposing its backing projections.
 * @param {PeopleDirectorySearch|string} [search]
 */
export async function searchCommunity(search = {}) {
	const options = typeof search === "string" ? { q: search } : search;
	const params = directoryParams(options);
	const data = await backendGetJson(`/v1/community/${params.size > 0 ? `?${params}` : ""}`);
	if (!data) throw new Error("Community directory unavailable");
	const results = Array.isArray(data?.results) ? data.results : [];
	return {
		results,
		count: Number.isFinite(Number(data?.count)) ? Number(data.count) : results.length,
		counts: data?.counts || { people: 0, accounts: 0, tools: 0, unresolvedAttributions: 0 },
		page: Number(data?.page) || 1,
		pageSize: Number(data?.pageSize) || options.pageSize || 24,
		pageCount: Number(data?.pageCount) || 1,
		next: data?.next || null,
		previous: data?.previous || null,
		truncated: Boolean(data?.truncated),
		accountSync: data?.accountSync || { status: "unavailable", complete: false }
	};
}

/** @param {PeopleDirectorySearch|string} [search] */
export async function searchPeopleDirectory(search = {}) {
	const options = typeof search === "string" ? { q: search } : search;
	const params = directoryParams(options);
	const data = await backendGetJson(`/v1/people/${params.size > 0 ? `?${params}` : ""}`);
	if (!data) throw new Error("People directory unavailable");
	const people = Array.isArray(data?.results) ? data.results : [];
	return {
		people,
		unresolvedAttributions: Array.isArray(data?.unresolvedAttributions) ? data.unresolvedAttributions : [],
		count: Number.isFinite(Number(data?.count)) ? Number(data.count) : people.length,
		page: Number(data?.page) || 1,
		pageSize: Number(data?.pageSize) || options.pageSize || 24,
		pageCount: Number(data?.pageCount) || 1,
		next: data?.next || null,
		previous: data?.previous || null
	};
}

/** @param {Pick<PeopleDirectorySearch, "q"|"page"|"pageSize"|"role"|"project">} [search] */
export async function searchUnresolvedAttributions(search = {}) {
	const params = directoryParams(search);
	const data = await backendGetJson(`/v1/people/attributions/${params.size > 0 ? `?${params}` : ""}`);
	if (!data) throw new Error("Unresolved attribution search unavailable");
	const attributions = Array.isArray(data?.results) ? data.results : [];
	return {
		attributions,
		count: Number.isFinite(Number(data?.count)) ? Number(data.count) : attributions.length,
		page: Number(data?.page) || 1,
		pageSize: Number(data?.pageSize) || search.pageSize || 10,
		pageCount: Number(data?.pageCount) || 1,
		next: data?.next || null,
		previous: data?.previous || null
	};
}

/** @param {string} query */
export async function searchPeople(query) {
	const directory = await searchPeopleDirectory(query);
	return directory.people;
}

/**
 * Ask the backend to resolve a legacy /by/{name} route under identity policy.
 * @param {string} query
 */
export function resolvePersonHandle(query) {
	return backendGetJson(`/v1/people/resolve/?handle=${encodeURIComponent(query)}`);
}

/**
 * Compatibility helper for callers that only understand resolved-or-null.
 * @param {string} query
 */
export async function personByHandle(query) {
	const resolution = await resolvePersonHandle(query);
	return resolution?.status === "resolved" && resolution?.person?.id ? personById(resolution.person.id) : null;
}

/** @param {any} person */
export function toolsForPerson(person) {
	const rows = Array.isArray(person?.tools)
		? person.tools
		: Array.isArray(person?.tools?.results)
			? person.tools.results
			: [];
	return /** @type {Tool[]} */ (
		rows
			.filter((/** @type {any} */ row) => row?.name)
			.map((/** @type {any} */ row) => {
				const summary = row.summary && typeof row.summary === "object" ? row.summary : {};
				const tool = normalizeTool({
					name: row.name,
					title: row.name,
					description: "",
					origin: "profile_relationship",
					...summary
				});
				return {
					...tool,
					personRelationships: Array.isArray(row.relationships) ? row.relationships : [],
					profileSummaryStatus: row.summaryStatus || (summary._missingCanonical ? "missing" : "available")
				};
			})
	);
}
