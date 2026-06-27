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

test("plural binds to the loaded locale's CLDR categories (ru few/many)", async () => {
	const i18n = await loadI18n("ru");
	const forms = { one: "ONE", few: "FEW", many: "MANY", other: "OTHER" };
	// Russian: 1 → one, 2-4 → few, 5-20 → many (CLDR-stable across ICU versions).
	assert.equal(i18n.plural(1, forms), "ONE");
	assert.equal(i18n.plural(3, forms), "FEW");
	assert.equal(i18n.plural(7, forms), "MANY");
	// countLabel threads the same locale plural through a formatted count.
	assert.equal(i18n.countLabel(3, "элемент", "элементов"), `${i18n.fmt(3)} элементов`);
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
