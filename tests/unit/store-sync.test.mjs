// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "vitest";
import {
	DEMO_KEYS,
	demoStore,
	setStoreSync,
	toggleFav,
	withDemoFixture,
	withSyncMuted
} from "../../public_html/lib/core/store.js";

beforeEach(() => {
	localStorage.clear();
});
afterEach(() => {
	setStoreSync(null);
});

test("a registered sync hook sees every successful set with key and value", () => {
	const seen = [];
	setStoreSync((k, v) => seen.push([k, v]));
	demoStore.set(DEMO_KEYS.favorites, ["a"]);
	toggleFav("b"); // helper mutations flow through the same hook
	assert.deepEqual(seen, [
		[DEMO_KEYS.favorites, ["a"]],
		[DEMO_KEYS.favorites, ["a", "b"]]
	]);
});

test("no hook (default) and non-function hooks are safe no-ops", () => {
	assert.equal(demoStore.set(DEMO_KEYS.favorites, []), true);
	setStoreSync("not a function");
	assert.equal(demoStore.set(DEMO_KEYS.favorites, ["x"]), true);
});

test("withSyncMuted suppresses pushes and returns the inner value", () => {
	const seen = [];
	setStoreSync((k) => seen.push(k));
	const out = withSyncMuted(() => {
		demoStore.set(DEMO_KEYS.lists, []);
		return 42;
	});
	assert.equal(out, 42);
	assert.deepEqual(seen, []);
	demoStore.set(DEMO_KEYS.lists, []); // muting is scoped, not permanent
	assert.deepEqual(seen, [DEMO_KEYS.lists]);
});

test("withSyncMuted unmutes even when the inner function throws", () => {
	const seen = [];
	setStoreSync((k) => seen.push(k));
	assert.throws(() =>
		withSyncMuted(() => {
			throw new Error("boom");
		})
	);
	demoStore.set(DEMO_KEYS.favorites, []);
	assert.deepEqual(seen, [DEMO_KEYS.favorites]);
});

test("withDemoFixture previews never push to the server", () => {
	const seen = [];
	setStoreSync((k) => seen.push(k));
	demoStore.set(DEMO_KEYS.favorites, ["kept"]);
	seen.length = 0;
	const html = withDemoFixture({ [DEMO_KEYS.favorites]: ["preview"] }, () => "rendered");
	assert.equal(html, "rendered");
	assert.deepEqual(seen, []); // neither the fixture set nor the restore pushed
	assert.deepEqual(demoStore.get(DEMO_KEYS.favorites), ["kept"]);
});

test("a failed localStorage write does not push", () => {
	const seen = [];
	setStoreSync((k) => seen.push(k));
	const original = localStorage.setItem;
	localStorage.setItem = () => {
		throw new Error("quota");
	};
	try {
		assert.equal(demoStore.set(DEMO_KEYS.favorites, ["x"]), false);
	} finally {
		localStorage.setItem = original;
	}
	assert.deepEqual(seen, []);
});
