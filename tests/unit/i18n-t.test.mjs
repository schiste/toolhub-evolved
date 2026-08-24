// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { afterEach, test } from "vitest";
import { AVAILABLE_LOCALES } from "../../public_html/lib/core/available-locales.js";
import {
	BOOT_MESSAGES,
	LOCALE_KEY,
	localizedField,
	pickLocalized,
	pseudoLocalize,
	setLocale,
	setKnownMessageKeys,
	setMessages,
	t,
	tData,
	tWithElements
} from "../../public_html/lib/core/i18n.js";

// These tests exercise the resolver itself, so they address it with keys like
// `x.p` that stand for "some message" and deliberately do not name a real one.
// The suite-wide key set (./_i18n-keys.mjs) exists to make a key that no
// catalog carries visible everywhere else; here that is the subject matter.
setKnownMessageKeys(null);

afterEach(() => {
	setMessages({});
	setKnownMessageKeys(null);
	localStorage.removeItem(LOCALE_KEY);
});

test("a restricted key set renders a key the catalog cannot translate as a marker", () => {
	// What the rest of the suite relies on: with the key set installed the key
	// reaches the output, so a call site that names a key no catalog carries
	// stops rendering its English and starts failing the assertion under it.
	setKnownMessageKeys(["x.known"]);

	assert.equal(t("x.known", "Known"), "Known");
	assert.equal(t("x.absent", "Known"), "[unknown i18n key x.absent]");
	assert.equal(t("", "Known"), "[unknown i18n key ]");
});

test("the marker replaces every resolution, not just the ones with a fallback", () => {
	// tData and tWithElements resolve the same way, and a boot message is only
	// exempt because the generated catalog carries every one of its keys too.
	setKnownMessageKeys(["x.known"]);

	assert.equal(tData("x.absent", "Known"), "[unknown i18n key x.absent]");
	assert.equal(tWithElements("x.absent", "Known"), "[unknown i18n key x.absent]");
	assert.equal(t("router.loadingPage"), "[unknown i18n key router.loadingPage]");
});

test("clearing the key set accepts any key again, which is how the app runs", () => {
	setKnownMessageKeys(["x.known"]);
	setKnownMessageKeys(null);

	assert.equal(t("x.absent", "Known"), "Known");
});

test("an empty key set restricts every key rather than none", () => {
	// `[]` and `null` are both falsy-adjacent shapes a caller could pass; only
	// null means "do not restrict", so the two must not collapse together.
	setKnownMessageKeys([]);

	assert.equal(t("x.known", "Known"), "[unknown i18n key x.known]");
});

test("t returns the English fallback when no catalog is installed", () => {
	assert.equal(t("x.hello", "Hello"), "Hello");
});

test("t has tiny boot-critical English fallbacks when a caller has no catalog fallback", () => {
	assert.equal(BOOT_MESSAGES["router.loadingPage"], "Loading page");
	assert.equal(t("router.loadingPage"), "Loading page");
	assert.equal(t("x.unknown"), "x.unknown");
});

test("pseudoLocalize accents, brackets, expands, and preserves parameters", () => {
	assert.equal(pseudoLocalize("Open $1 tools"), "[Öƥḗƞ $1 ŧǿǿļş~~~~]");
	assert.equal(pseudoLocalize("$1"), "[$1]");
	assert.equal(pseudoLocalize(""), "");
});

test("t prefers the installed catalog and fills params after lookup", () => {
	setMessages({ "x.greet": "Bonjour $1 ($1)" });
	assert.equal(t("x.greet", "Hello $1 ($1)", "Ada"), "Bonjour Ada (Ada)");
	// params also apply to the fallback path
	assert.equal(t("x.missing", "$1 tools", 3), "3 tools");
	// translations control word order — the whole point of positional params
	setMessages({ "x.order": "$2 before $1" });
	assert.equal(t("x.order", "$1 before $2", "a", "b"), "b before a");
});

test("setMessages drops @metadata and non-string entries from a catalog", () => {
	// translatewiki writes @metadata into every catalog it produces.
	setMessages({ "@metadata": { authors: ["Ada"] }, "x.ok": "Bonjour", "x.bad": 42 });
	assert.equal(t("@metadata", "fallback"), "fallback");
	assert.equal(t("x.ok", "Hello"), "Bonjour");
	assert.equal(t("x.bad", "Hello"), "Hello");
});

test("tData resolves markup-extracted shell messages", () => {
	assert.equal(tData("shell.skipToContent", "Skip to content"), "Skip to content");
	setMessages({ "shell.skipToContent": "Aller au contenu" });
	assert.equal(tData("shell.skipToContent", "Skip to content"), "Aller au contenu");
});

test("tWithElements escapes text and inserts only caller-owned markup", () => {
	const code = { html: "<code>toolinfo.json</code>" };
	assert.equal(
		tWithElements("x.inlineCode", "Add $1 for $2.", code, "Ada & Co"),
		"Add <code>toolinfo.json</code> for Ada &amp; Co."
	);
	// The translation reorders; the trusted/escaped split follows the parameter.
	setMessages({ "x.inlineCode": "$2: add $1." });
	assert.equal(
		tWithElements("x.inlineCode", "Add $1 for $2.", code, "Ada & Co"),
		"Ada &amp; Co: add <code>toolinfo.json</code>."
	);
	// A plain string is escaped even where an element was expected, so neither a
	// translator nor live API data can introduce markup.
	assert.equal(tWithElements("x.plain", "Add $1.", "<b>no</b>"), "Add &lt;b&gt;no&lt;/b&gt;.");
	assert.equal(tWithElements("x.unknown", "Keep $1."), "Keep $1.");
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
	assert.ok(AVAILABLE_LOCALES.includes("en-x-pseudo"));
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
