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

/** @param {string} query */
export async function searchPeopleDirectory(query) {
	const data = await backendGetJson(`/v1/people/?q=${encodeURIComponent(query)}&limit=50`);
	return {
		people: Array.isArray(data?.results) ? data.results : [],
		unresolvedAttributions: Array.isArray(data?.unresolvedAttributions) ? data.unresolvedAttributions : []
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
