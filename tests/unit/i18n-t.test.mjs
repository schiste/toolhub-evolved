// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { afterEach, test } from "vitest";
import {
	AVAILABLE_LOCALES,
	BOOT_MESSAGES,
	LOCALE_KEY,
	localizedField,
	pickLocalized,
	setLocale,
	setMessages,
	t,
	tData,
	tWithElements
} from "../../public_html/lib/core/i18n.js";

afterEach(() => {
	setMessages({});
	localStorage.removeItem(LOCALE_KEY);
});

test("t returns the English fallback when no catalog is installed", () => {
	assert.equal(t("x.hello", "Hello"), "Hello");
});

test("t has tiny boot-critical English fallbacks when a caller has no catalog fallback", () => {
	assert.equal(BOOT_MESSAGES["router.loadingToolhubData"], "Loading Toolhub data");
	assert.equal(t("router.loadingToolhubData"), "Loading Toolhub data");
	assert.equal(t("x.unknown"), "x.unknown");
});

test("t prefers the installed catalog and fills params after lookup", () => {
	setMessages({ "x.greet": "Bonjour {name} ({name})" });
	assert.equal(t("x.greet", "Hello {name} ({name})", { name: "Ada" }), "Bonjour Ada (Ada)");
	// params also apply to the fallback path
	assert.equal(t("x.missing", "{n} tools", { n: 3 }), "3 tools");
});

test("tData resolves markup-extracted shell messages", () => {
	assert.equal(tData("shell.skipToContent", "Skip to content"), "Skip to content");
	setMessages({ "shell.skipToContent": "Aller au contenu" });
	assert.equal(tData("shell.skipToContent", "Skip to content"), "Aller au contenu");
});

test("tWithElements escapes text and inserts caller-owned element placeholders", () => {
	assert.equal(
		tWithElements(
			"x.inlineCode",
			"Add {toolinfo} for {name}.",
			{ toolinfo: "<code>toolinfo.json</code>" },
			{
				name: "Ada & Co"
			}
		),
		"Add <code>toolinfo.json</code> for Ada &amp; Co."
	);
	setMessages({ "x.inlineCode": "{name}: add {toolinfo}." });
	assert.equal(
		tWithElements(
			"x.inlineCode",
			"Add {toolinfo} for {name}.",
			{ toolinfo: "<code>toolinfo.json</code>" },
			{
				name: "Ada & Co"
			}
		),
		"Ada &amp; Co: add <code>toolinfo.json</code>."
	);
	assert.equal(tWithElements("x.unknown", "Keep {missing}.", {}), "Keep {missing}.");
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

test("localizedField returns the chosen value and language metadata", () => {
	assert.deepEqual(localizedField("plain", "fr"), { value: "plain", lang: "fr" });
	assert.deepEqual(localizedField("plain", "bad language"), { value: "plain", lang: null });
	assert.deepEqual(localizedField({ fr: "Français" }, "de"), { value: "Français", lang: "fr" });
	assert.deepEqual(localizedField({ pt_br: "Português" }, "de"), { value: "Português", lang: "pt-BR" });
	assert.deepEqual(localizedField({}, "fr"), { value: "", lang: null });
});
