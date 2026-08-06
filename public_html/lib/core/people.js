// SPDX-License-Identifier: GPL-3.0-or-later
import { backendGetJson, getToolsByName } from "./api.js";

/** @param {string} toolName */
export function peopleForTool(toolName) {
	return backendGetJson(`/v1/people/tools/${encodeURIComponent(toolName)}/`);
}

/** @param {string} publicId */
export function personById(publicId) {
	return backendGetJson(`/v1/people/${encodeURIComponent(publicId)}/`);
}

/**
 * @typedef {{q?: string, page?: number, pageSize?: number, role?: string, verification?: string, activity?: string, project?: string, ordering?: string}} PeopleDirectorySearch
 */

/** @param {PeopleDirectorySearch} search */
function directoryParams(search) {
	const params = new URLSearchParams();
	if (search.q) params.set("q", search.q);
	if (search.page && search.page > 1) params.set("page", String(search.page));
	if (search.pageSize) params.set("page_size", String(search.pageSize));
	for (const key of ["role", "verification", "activity", "project", "ordering"]) {
		const value = search[/** @type {keyof PeopleDirectorySearch} */ (key)];
		if (value) params.set(key, String(value));
	}
	return params;
}

/** @param {PeopleDirectorySearch|string} [search] */
export async function searchPeopleDirectory(search = {}) {
	const options = typeof search === "string" ? { q: search } : search;
	const params = directoryParams(options);
	const data = await backendGetJson(`/v1/people/${params.size > 0 ? `?${params}` : ""}`);
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
export async function toolsForPerson(person) {
	const relationships = new Map(
		(Array.isArray(person?.tools) ? person.tools : [])
			.filter((/** @type {any} */ tool) => tool?.name)
			.map((/** @type {any} */ tool) => [tool.name, Array.isArray(tool.relationships) ? tool.relationships : []])
	);
	const tools = /** @type {Tool[]} */ (await getToolsByName([...relationships.keys()]));
	return tools.map((tool) => ({ ...tool, personRelationships: relationships.get(tool.name) || [] }));
}
