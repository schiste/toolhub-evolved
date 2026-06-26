// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test, beforeEach, afterAll } from "vitest";
import * as session from "../../public_html/lib/core/session.js";

// This Node/happy-dom build ships a non-functional `localStorage` (its
// getItem/setItem/removeItem are not callable), so install a faithful,
// Object.keys()-enumerable Storage polyfill before each test (see store.test.mjs
// for the full rationale). A fresh instance per test also isolates persisted flags.
function makeStorage() {
	const data = Object.create(null);
	const api = {
		getItem(key) {
			const k = String(key);
			return Object.prototype.hasOwnProperty.call(data, k) ? data[k] : null;
		},
		setItem(k, v) {
			data[String(k)] = String(v);
		},
		removeItem(k) {
			delete data[String(k)];
		},
		clear() {
			for (const k of Object.keys(data)) delete data[k];
		},
		key(i) {
			return Object.keys(data)[i] ?? null;
		},
		get length() {
			return Object.keys(data).length;
		}
	};
	return new Proxy(api, {
		ownKeys() {
			return Object.keys(data);
		},
		getOwnPropertyDescriptor(_t, p) {
			return Object.prototype.hasOwnProperty.call(data, p)
				? { enumerable: true, configurable: true, writable: true, value: data[p] }
				: Reflect.getOwnPropertyDescriptor(api, p);
		},
		has(_t, p) {
			return p in api || Object.prototype.hasOwnProperty.call(data, p);
		}
	});
}

beforeEach(() => {
	Object.defineProperty(globalThis, "localStorage", { value: makeStorage(), configurable: true, writable: true });
	Object.defineProperty(window, "localStorage", {
		value: globalThis.localStorage,
		configurable: true,
		writable: true
	});
	session.setAuthRender(() => {});
});

// Leave experimental mode off so this file's in-memory flag does not leak into
// sibling test files that share the process under the Stryker test runner.
afterAll(() => {
	session.applyExp(false);
});

// Runs first, before any applyExp call, so it observes the module's initial
// in-memory flag (let expActive = false) rather than a value set by a test.
test("experimental mode is off by default", () => {
	assert.equal(session.expOn(), false);
	assert.equal(session.signedIn(), false);
});

test("exported identity constants are exact", () => {
	assert.equal(session.EXP_KEY, "toolhub-exp");
	assert.equal(session.AUTH_KEY, "toolhub-auth");
	assert.deepEqual(session.USER, { name: "Ada Lovelace" });
	assert.equal(session.USER.name, "Ada Lovelace");
});

test("expStored reads the persisted opt-in flag", () => {
	assert.equal(session.expStored(), false); // missing key
	localStorage.setItem("toolhub-exp", "on");
	assert.equal(session.expStored(), true);
	localStorage.setItem("toolhub-exp", "off");
	assert.equal(session.expStored(), false);
});

test("setExpStored persists exactly 'on' or 'off'", () => {
	session.setExpStored(true);
	assert.equal(localStorage.getItem("toolhub-exp"), "on");
	assert.equal(session.expStored(), true);
	session.setExpStored(false);
	assert.equal(localStorage.getItem("toolhub-exp"), "off");
	assert.equal(session.expStored(), false);
});

test("applyExp coerces to boolean and expOn reflects it", () => {
	session.applyExp(1);
	assert.equal(session.expOn(), true);
	session.applyExp(0);
	assert.equal(session.expOn(), false);
	session.applyExp("x");
	assert.equal(session.expOn(), true);
	session.applyExp("");
	assert.equal(session.expOn(), false);
});

test("signedIn requires experiments on AND auth not opted out", () => {
	// exp off, no auth-out marker -> still signed out (the && short-circuits)
	session.applyExp(false);
	assert.equal(session.signedIn(), false);
	// exp on, no marker -> signed in
	session.applyExp(true);
	assert.equal(session.signedIn(), true);
	// exp on, but explicitly signed out -> false
	localStorage.setItem("toolhub-auth", "out");
	assert.equal(session.signedIn(), false);
	// any other marker value counts as signed in
	localStorage.setItem("toolhub-auth", "in");
	assert.equal(session.signedIn(), true);
});

test("setAuth toggles the persisted out-marker and refreshes via authRender", () => {
	let calls = 0;
	session.setAuthRender(() => {
		calls += 1;
	});
	// sign out: writes the "out" marker
	session.setAuth(false);
	assert.equal(localStorage.getItem("toolhub-auth"), "out");
	assert.equal(calls, 1);
	// sign in: removes the marker
	session.setAuth(true);
	assert.equal(localStorage.getItem("toolhub-auth"), null);
	assert.equal(calls, 2);
});

test("setAuthRender ignores non-functions and installs callable renderers", () => {
	let calls = 0;
	session.setAuthRender(() => {
		calls += 1;
	});
	session.setAuth(true);
	assert.equal(calls, 1);
	// a non-function replaces the renderer with a safe no-op (no throw, no call)
	session.setAuthRender(null);
	session.setAuth(true);
	assert.equal(calls, 1);
	session.setAuthRender("not a function");
	session.setAuth(false);
	assert.equal(calls, 1);
});
