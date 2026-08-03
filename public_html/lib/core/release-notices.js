// SPDX-License-Identifier: GPL-3.0-or-later
/* Browser-only acknowledgement state for public release notices. */
export const WHATS_NEW_NEVER_KEY = "toolhub-whats-new-never";
export const WHATS_NEW_SEEN_KEY = "toolhub-whats-new-seen";

function read(key) {
	try {
		return globalThis.localStorage?.getItem(key) || "";
	} catch {
		return "";
	}
}

/** @returns {boolean} */
export function whatsNewNever() {
	return read(WHATS_NEW_NEVER_KEY) === "1";
}

/** @param {string} id @returns {boolean} */
export function whatsNewSeen(id) {
	return Boolean(id) && read(WHATS_NEW_SEEN_KEY) === id;
}

/** @param {string} id */
export function markWhatsNewSeen(id) {
	try {
		if (id) globalThis.localStorage?.setItem(WHATS_NEW_SEEN_KEY, id);
	} catch {}
}

export function disableWhatsNewAutoOpen() {
	try {
		globalThis.localStorage?.setItem(WHATS_NEW_NEVER_KEY, "1");
	} catch {}
}
