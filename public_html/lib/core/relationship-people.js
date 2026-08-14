// SPDX-License-Identifier: GPL-3.0-or-later

/** @param {unknown} value */
function identityKey(value) {
	return String(value || "")
		.trim()
		.toLocaleLowerCase();
}

/** @param {any} relationship */
function observedNames(relationship) {
	const compact = Array.isArray(relationship?.observedNames) ? relationship.observedNames : [];
	const evidence = Array.isArray(relationship?.evidence)
		? relationship.evidence.map((/** @type {any} */ item) => item?.observedName)
		: [];
	return [...compact, ...evidence].map((value) => identityKey(value)).filter(Boolean);
}

/** @param {any} person @param {string} role */
export function relationshipsForRole(person, role) {
	return (Array.isArray(person?.relationships) ? person.relationships : []).filter(
		(/** @type {any} */ relationship) => relationship?.type === role || relationship?.requestedRelationship === role
	);
}

/** @param {any[]} people @param {string} role */
export function peopleForRole(people, role) {
	return (Array.isArray(people) ? people : []).filter(
		(person) => person?.id && relationshipsForRole(person, role).length > 0
	);
}

/** Resolve one label only when exactly one relationship-backed person matches. @param {any[]} people @param {string} label @param {string} role */
export function personForRelationshipLabel(people, label, role) {
	const key = identityKey(label);
	if (!key) return null;
	const matches = peopleForRole(people, role).filter((person) => {
		if (identityKey(person.displayName) === key) return true;
		if (
			(person.identifiers || []).some((/** @type {any} */ identifier) => identityKey(identifier?.value) === key)
		) {
			return true;
		}
		return relationshipsForRole(person, role).some((/** @type {any} */ relationship) =>
			observedNames(relationship).includes(key)
		);
	});
	return matches.length === 1 ? matches[0] : null;
}

/** Group relationship rows that already carry public person identity. @param {any[]} rows */
export function peopleFromRelationships(rows) {
	const byId = new Map();
	for (const relationship of Array.isArray(rows) ? rows : []) {
		const id = String(relationship?.personId || "").trim();
		if (!id) continue;
		const person = byId.get(id) || {
			id,
			displayName: String(relationship?.personName || ""),
			relationships: []
		};
		person.relationships.push(relationship);
		byId.set(id, person);
	}
	return [...byId.values()];
}
