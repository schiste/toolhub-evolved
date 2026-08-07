// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test, vi } from "vitest";
import { installStorage } from "./_storage-setup.mjs";

// Load a fresh copy of i18n.js bound to `locale` (LOCALE + the Intl formatters
// are evaluated at module load, so the registry must be reset per locale).
async function loadI18n(locale) {
	installStorage();
	localStorage.setItem("toolhub-locale", locale);
	vi.resetModules();
	return import("../../public_html/lib/core/i18n.js");
}

// i18n.js evaluates LOCALE and constructs the Intl formatters at MODULE LOAD.
// Mutations that make those Intl constructors throw (invalid locale/options) or
// that break appLocale() abort the module import. A *static* import of i18n in
// another test file turns that into a file-load error, which the Stryker vitest
// runner does not attribute as a kill. Importing i18n DYNAMICALLY inside a test
// turns the load failure into a normal test failure (the await rejects), so
// these import-time mutants are detected.
test("i18n module loads with valid Intl config and a working en default", async () => {
	installStorage();
	// Seed a valid stored locale so LOCALE is "en" regardless of DEFAULT_LOCALE,
	// isolating the Intl-option mutants (which throw) from the locale mutants.
	localStorage.setItem("toolhub-locale", "en");
	const i18n = await import("../../public_html/lib/core/i18n.js");

	// Formatters constructed with valid options produce the expected en output.
	assert.equal(i18n.fmt(1500), "1,500");
	assert.equal(i18n.compactFmt(1500), "1.5K");
	assert.equal(i18n.relativeTime(new Date().toISOString()), "today");
	const tag = i18n.timeTag("2026-05-01T12:00:00Z", null, "x");
	assert.ok(/^<time datetime="[^"]+" title="[^"]+">x<\/time>$/.test(tag), tag);

	// appLocale falls back to the "en" default when nothing is stored.
	localStorage.removeItem("toolhub-locale");
	assert.equal(i18n.appLocale(), "en");
	localStorage.setItem("toolhub-locale", "pt_BR");
	assert.equal(i18n.appLocale(), "pt-BR");
	localStorage.removeItem("toolhub-locale");
});

test("{{PLURAL:}} binds to the loaded locale's CLDR categories (ru one/few/many)", async () => {
	const i18n = await loadI18n("ru");
	const msg = "{{PLURAL:$1|ONE|FEW|MANY|OTHER}}";
	// Russian: 1 → one, 2-4 → few, 5-20 → many (CLDR-stable across ICU versions).
	assert.equal(i18n.t("x.ru", msg, 1), "ONE");
	assert.equal(i18n.t("x.ru", msg, 3), "FEW");
	assert.equal(i18n.t("x.ru", msg, 7), "MANY");
	// A two-form English source read in Russian keeps rendering (last form) —
	// the translation supplies few/many, which the old one/other pair could not.
	assert.equal(i18n.t("x.ruEn", "{{PLURAL:$1|item|items}}", 3), "items");
	localStorage.removeItem("toolhub-locale");
});

test("{{PLURAL:}} covers all six Arabic forms, which a one/other pair cannot", async () => {
	const i18n = await loadI18n("ar");
	const msg = "{{PLURAL:$1|ZERO|ONE|TWO|FEW|MANY|OTHER}}";
	assert.equal(i18n.t("x.ar", msg, 0), "ZERO");
	assert.equal(i18n.t("x.ar", msg, 1), "ONE");
	assert.equal(i18n.t("x.ar", msg, 2), "TWO");
	assert.equal(i18n.t("x.ar", msg, 3), "FEW");
	assert.equal(i18n.t("x.ar", msg, 11), "MANY");
	assert.equal(i18n.t("x.ar", msg, 100), "OTHER");
	localStorage.removeItem("toolhub-locale");
});

test("pseudolocale transforms chrome fallbacks without transforming params", async () => {
	const i18n = await loadI18n("en-x-pseudo");
	assert.equal(i18n.LOCALE, i18n.PSEUDO_LOCALE);
	assert.equal(i18n.localeDir(i18n.LOCALE), "ltr");
	assert.equal(i18n.t("x.greet", "Hello $1", "Ada"), "[Ħḗļļǿ Ada~~]");
	assert.equal(i18n.t("x.unknown"), "x.unknown");
	localStorage.removeItem("toolhub-locale");
});

test("pseudolocale transforms boot messages without fetching a catalog", async () => {
	const i18n = await loadI18n("en-x-pseudo");
	assert.equal(i18n.t("router.loadingToolhubData"), "[Ŀǿåḓīƞĝ Ţǿǿļħûƀ ḓåŧå~~~~~~]");
	localStorage.removeItem("toolhub-locale");
});

test("number + RTL formatting follow the loaded non-en locale", async () => {
	const ru = await loadI18n("ru");
	// ru groups thousands with a space, not the en comma — proves the formatter is
	// locale-bound, without asserting the exact (ICU-version-specific) separator.
	assert.notEqual(ru.fmt(1500), "1,500");
	assert.match(ru.fmt(1500), /1\D?500/);

	const ar = await loadI18n("ar");
	assert.equal(ar.localeDir(ar.LOCALE), "rtl");
	assert.equal(ar.appLocale(), "ar");
	localStorage.removeItem("toolhub-locale");
});
