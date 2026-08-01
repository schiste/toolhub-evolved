// SPDX-License-Identifier: GPL-3.0-or-later
// cspell:words favourite favourites favourited unfavorited unfavourited
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

/** @param {any[]} rows */
export function publicActivityRows(rows) {
	return Array.isArray(rows) ? rows.filter((row) => !isPrivatePreferenceActivity(row)) : [];
}
