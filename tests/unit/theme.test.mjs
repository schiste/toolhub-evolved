// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test, beforeEach } from "vitest";

// theme.js captures `darkMQ = window.matchMedia("(prefers-color-scheme: dark)")`
// at module-eval time. happy-dom returns a fresh, non-dispatchable instance per
// call, so to exercise resolve()'s matches branch and initTheme()'s OS-change
// listener we install a single controllable mock BEFORE importing the module
// (the import is dynamic so this assignment runs first) and mutate it per test.
// The mock returns null for any other query, so mutating the query string in the
// source makes darkMQ null and is observable.
const darkMQMock = {
	matches: false,
	_listeners: [],
	addEventListener(type, cb) {
		if (type === "change") this._listeners.push(cb);
	},
	addListener(cb) {
		this._listeners.push(cb);
	},
	fire() {
		for (const cb of this._listeners) cb();
	}
};
window.matchMedia = (q) => (q === "(prefers-color-scheme: dark)" ? darkMQMock : null);

// Working localStorage polyfill (the platform one is non-functional here). Kept
// identical to the other test files' so the shared global stays complete
// (clear/key/length included) for sibling files under the Stryker test runner.
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

const theme = await import("../../public_html/lib/core/theme.js");

beforeEach(() => {
	Object.defineProperty(globalThis, "localStorage", { value: makeStorage(), configurable: true, writable: true });
	Object.defineProperty(window, "localStorage", {
		value: globalThis.localStorage,
		configurable: true,
		writable: true
	});
	darkMQMock.matches = false;
	darkMQMock._listeners = [];
	darkMQMock.addEventListener = function (type, cb) {
		if (type === "change") this._listeners.push(cb);
	};
	darkMQMock.addListener = function (cb) {
		this._listeners.push(cb);
	};
	document.documentElement.removeAttribute("data-theme");
});

test("getThemeChoice returns the stored choice or 'system'", () => {
	assert.equal(theme.getThemeChoice(), "system"); // missing key
	localStorage.setItem("toolhub-theme", "light");
	assert.equal(theme.getThemeChoice(), "light");
	localStorage.setItem("toolhub-theme", "dark");
	assert.equal(theme.getThemeChoice(), "dark");
	localStorage.setItem("toolhub-theme", "bogus");
	assert.equal(theme.getThemeChoice(), "system");
});

test("applyTheme writes explicit choices verbatim, ignoring the OS preference", () => {
	darkMQMock.matches = true; // would force dark if a choice were not explicit
	theme.applyTheme("light");
	assert.equal(document.documentElement.getAttribute("data-theme"), "light");
	darkMQMock.matches = false; // would force light if a choice were not explicit
	theme.applyTheme("dark");
	assert.equal(document.documentElement.getAttribute("data-theme"), "dark");
});

test("applyTheme('system') resolves against the OS preference", () => {
	darkMQMock.matches = true;
	theme.applyTheme("system");
	assert.equal(document.documentElement.getAttribute("data-theme"), "dark");
	darkMQMock.matches = false;
	theme.applyTheme("system");
	assert.equal(document.documentElement.getAttribute("data-theme"), "light");
});

test("applyTheme defaults its argument to the stored choice", () => {
	localStorage.setItem("toolhub-theme", "dark");
	darkMQMock.matches = false; // proves the stored 'dark' (not the OS) was used
	theme.applyTheme();
	assert.equal(document.documentElement.getAttribute("data-theme"), "dark");
});

test("setThemeChoice persists explicit choices and applies them immediately", () => {
	theme.setThemeChoice("light");
	assert.equal(localStorage.getItem("toolhub-theme"), "light");
	assert.equal(document.documentElement.getAttribute("data-theme"), "light");

	theme.setThemeChoice("dark");
	assert.equal(localStorage.getItem("toolhub-theme"), "dark");
	assert.equal(document.documentElement.getAttribute("data-theme"), "dark");
});

test("setThemeChoice('system') clears the stored key and follows the OS", () => {
	localStorage.setItem("toolhub-theme", "light");
	darkMQMock.matches = true;
	theme.setThemeChoice("system");
	assert.equal(localStorage.getItem("toolhub-theme"), null);
	assert.equal(document.documentElement.getAttribute("data-theme"), "dark");
});

test("initTheme applies the current choice and registers an OS-change listener", () => {
	localStorage.setItem("toolhub-theme", "system");
	darkMQMock.matches = false;
	darkMQMock.addListener = undefined; // only addEventListener is available -> no legacy fallback
	theme.initTheme();
	assert.equal(document.documentElement.getAttribute("data-theme"), "light");
	assert.equal(darkMQMock._listeners.length, 1);

	// OS flips to dark while the choice is "system" -> the listener re-applies
	darkMQMock.matches = true;
	darkMQMock.fire();
	assert.equal(document.documentElement.getAttribute("data-theme"), "dark");
});

test("the OS-change listener does nothing unless the choice is 'system'", () => {
	localStorage.setItem("toolhub-theme", "light");
	darkMQMock.matches = false;
	theme.initTheme();
	assert.equal(document.documentElement.getAttribute("data-theme"), "light");
	// OS flips to dark, but the explicit "light" choice wins
	darkMQMock.matches = true;
	darkMQMock.fire();
	assert.equal(document.documentElement.getAttribute("data-theme"), "light");
});

test("initTheme falls back to the legacy addListener API", () => {
	localStorage.setItem("toolhub-theme", "system");
	darkMQMock.matches = false;
	darkMQMock.addEventListener = undefined; // force the addListener branch
	theme.initTheme();
	assert.equal(darkMQMock._listeners.length, 1);
	darkMQMock.matches = true;
	darkMQMock.fire();
	assert.equal(document.documentElement.getAttribute("data-theme"), "dark");
});

test("initTheme tolerates a media query lacking listener APIs", () => {
	localStorage.setItem("toolhub-theme", "light");
	darkMQMock.matches = false;
	// Neither registration API exists: initTheme must guard both calls and not throw.
	// (A mutated `if (true)` / `else if (true)` would attempt to call undefined.)
	darkMQMock.addEventListener = undefined;
	darkMQMock.addListener = undefined;
	theme.initTheme();
	assert.equal(document.documentElement.getAttribute("data-theme"), "light");
	assert.equal(darkMQMock._listeners.length, 0);
});
