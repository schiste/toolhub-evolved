// SPDX-License-Identifier: GPL-3.0-or-later
import { backendGetJson, getToolsByName } from "./api.js";
import { normStr } from "./util.js";

/** @param {string} toolName */
export function peopleForTool(toolName) {
	return backendGetJson(`/v1/people/tools/${encodeURIComponent(toolName)}/`);
}

/** @param {string} publicId */
export function personById(publicId) {
	return backendGetJson(`/v1/people/${encodeURIComponent(publicId)}/`);
}

/** @param {string} query */
export async function searchPeople(query) {
	const data = await backendGetJson(`/v1/people/?q=${encodeURIComponent(query)}&limit=50`);
	return Array.isArray(data?.results) ? data.results : [];
}

/**
 * Resolve a legacy /by/{name} route without treating that name as an id.
 * @param {string} query
 */
export async function personByHandle(query) {
	const key = normStr(query);
	const candidates = await searchPeople(query);
	const person = candidates.find(
		(/** @type {any} */ candidate) =>
			normStr(candidate?.displayName) === key ||
			candidate?.identifiers?.some((/** @type {any} */ identifier) => normStr(identifier?.value) === key)
	);
	return person?.id ? personById(person.id) : null;
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
