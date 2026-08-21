// SPDX-License-Identifier: GPL-3.0-or-later
// cspell:words favourite favourites favourited unfavorited unfavourited
// Upstream Toolhub spells the list content type "toollist"; Evolved rows spell
// it "list". Both reach these feeds, so both have to be recognized.
const LIST_OBJECT_KEYS = new Set(["list", "lists", "toollist", "toollists", "tool_list", "tool_lists"]);
const SYNC_OFFICIAL = "official";
const PRIVATE_OBJECT_KEYS = new Set([
	"favorite",
	"favorites",
	"favourite",
	"favourites",
	"user_favorite",
	"user_favourite"
]);
const PRIVATE_ACTION_KEYS = new Set([
	"favorited",
	"favourited",
	"unfavorited",
	"unfavourited",
	"favorite_removed",
	"favourite_removed",
	"favorite_retried",
	"favorite_retry_failed",
	"favorite_discarded"
]);

/** @param {unknown} value */
function activityKey(value) {
	return String(value ?? "")
		.trim()
		.toLocaleLowerCase()
		.replaceAll(/[^a-z0-9]+/g, "_")
		.replaceAll(/^_+|_+$/g, "");
}

/** @param {any} row */
export function isPrivatePreferenceActivity(row) {
	if (!row || typeof row !== "object") return false;
	const objectKeys = [row.content_type, row.object_type, row.target?.type].map((value) => activityKey(value));
	if (
		objectKeys.some((key) => PRIVATE_OBJECT_KEYS.has(key) || key.includes("favorite") || key.includes("favourite"))
	) {
		return true;
	}
	for (const key of [row.action, row.comment].map((value) => activityKey(value))) {
		if (PRIVATE_ACTION_KEYS.has(key)) return true;
		const preferenceWord = key.includes("favorite") || key.includes("favourite");
		const preferenceAction = ["add", "remove", "favorited", "favourited", "unfavorited", "unfavourited"].some(
			(token) => key.includes(token)
		);
		if (preferenceWord && preferenceAction) return true;
	}
	return false;
}

/**
 * Whether one list activity row describes a list the public cannot see.
 *
 * The browser can only decide this for Evolved's own rows, which carry an
 * `officialStatus`: Evolved always writes lists upstream as published, so an
 * officially-synced row is public, while a local fallback describes a list that
 * was never published anywhere. Upstream rows arrive already vetted against the
 * published-list replica by the backend (`activity_privacy.py`), which is the
 * only side that can answer that question, so they pass through here.
 *
 * @param {any} row
 */
export function isPrivateListActivity(row) {
	if (!row || typeof row !== "object") return false;
	const objectKeys = [row.content_type, row.object_type, row.target?.type].map((value) => activityKey(value));
	if (!objectKeys.some((key) => LIST_OBJECT_KEYS.has(key))) return false;
	const officialStatus = row.officialStatus;
	if (row._evolved === true || (officialStatus ?? null) !== null) return officialStatus !== SYNC_OFFICIAL;
	return false;
}

/** @param {any} row */
export function isPrivateActivity(row) {
	return isPrivatePreferenceActivity(row) || isPrivateListActivity(row);
}

/** @param {any[]} rows */
export function publicActivityRows(rows) {
	return Array.isArray(rows) ? rows.filter((row) => !isPrivateActivity(row)) : [];
}
