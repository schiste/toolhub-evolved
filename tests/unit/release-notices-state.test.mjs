// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { beforeEach, test, vi } from "vitest";
import {
	WHATS_NEW_COLLAPSED_KEY,
	WHATS_NEW_NEVER_KEY,
	WHATS_NEW_SEEN_KEY,
	clearWhatsNewCollapsed,
	disableWhatsNewAutoOpen,
	markWhatsNewCollapsed,
	markWhatsNewSeen,
	whatsNewCollapsed,
	whatsNewForced,
	whatsNewNever,
	whatsNewSeen
} from "../../public_html/lib/core/release-notices.js";

beforeEach(() => {
	localStorage.clear();
	window.history.replaceState({}, "", "/");
	vi.restoreAllMocks();
});

test("release notice preferences round-trip through browser storage", () => {
	assert.equal(whatsNewNever(), false);
	assert.equal(whatsNewCollapsed(), false);
	assert.equal(whatsNewSeen("release-1"), false);
	assert.equal(whatsNewSeen(""), false);

	disableWhatsNewAutoOpen();
	markWhatsNewCollapsed();
	markWhatsNewSeen("release-1");
	assert.equal(localStorage.getItem(WHATS_NEW_NEVER_KEY), "1");
	assert.equal(localStorage.getItem(WHATS_NEW_COLLAPSED_KEY), "1");
	assert.equal(localStorage.getItem(WHATS_NEW_SEEN_KEY), "release-1");
	assert.equal(whatsNewNever(), true);
	assert.equal(whatsNewCollapsed(), true);
	assert.equal(whatsNewSeen("release-1"), true);

	clearWhatsNewCollapsed();
	assert.equal(whatsNewCollapsed(), false);
});

test("forced release notices require the explicit query value", () => {
	window.history.replaceState({}, "", "/?whats-new=1");
	assert.equal(whatsNewForced(), true);
	window.history.replaceState({}, "", "/?whats-new=0");
	assert.equal(whatsNewForced(), false);
});

test("release notice state fails closed when storage is unavailable", () => {
	const getItem = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
		throw new Error("storage disabled");
	});
	assert.equal(whatsNewNever(), false);
	assert.equal(whatsNewCollapsed(), false);
	assert.equal(whatsNewSeen("release-1"), false);
	getItem.mockRestore();

	vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
		throw new Error("storage disabled");
	});
	assert.doesNotThrow(() => disableWhatsNewAutoOpen());
	assert.doesNotThrow(() => markWhatsNewCollapsed());
	assert.doesNotThrow(() => markWhatsNewSeen("release-1"));
	assert.doesNotThrow(() => markWhatsNewSeen(""));

	vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
		throw new Error("storage disabled");
	});
	assert.doesNotThrow(() => clearWhatsNewCollapsed());
});
