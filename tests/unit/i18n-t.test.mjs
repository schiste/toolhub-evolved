// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { afterEach, test } from "vitest";
import {
	AVAILABLE_LOCALES,
	LOCALE_KEY,
	pickLocalized,
	setLocale,
	setMessages,
	t
} from "../../public_html/lib/core/i18n.js";

afterEach(() => {
	setMessages({});
	localStorage.removeItem(LOCALE_KEY);
});

test("t returns the English fallback when no catalog is installed", () => {
	assert.equal(t("x.hello", "Hello"), "Hello");
});

test("t prefers the installed catalog and fills params after lookup", () => {
	setMessages({ "x.greet": "Bonjour {name} ({name})" });
	assert.equal(t("x.greet", "Hello {name} ({name})", { name: "Ada" }), "Bonjour Ada (Ada)");
	// params also apply to the fallback path
	assert.equal(t("x.missing", "{n} tools", { n: 3 }), "3 tools");
});

test("setMessages ignores non-object catalogs", () => {
	setMessages("garbage");
	assert.equal(t("x.hello", "Hello"), "Hello");
	setMessages(null);
	assert.equal(t("x.hello", "Hello"), "Hello");
});

test("setLocale persists the choice under the locale key", () => {
	setLocale("fr");
	assert.equal(localStorage.getItem(LOCALE_KEY), "fr");
});

test("English always ships as an available locale", () => {
	assert.ok(AVAILABLE_LOCALES.includes("en"));
});

test("pickLocalized passes plain values through and resolves language maps", () => {
	assert.equal(pickLocalized("plain"), "plain");
	assert.equal(pickLocalized(null), null);
	assert.deepEqual(pickLocalized(["a"]), ["a"]);
	assert.equal(pickLocalized({ en: "English", fr: "Français" }), "English"); // active locale is en
	assert.equal(pickLocalized({ fr: "Français" }), "Français"); // any-value fallback
	assert.equal(pickLocalized({}), "");
});
