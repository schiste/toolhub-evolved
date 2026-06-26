// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test } from "vitest";
import { installStorage } from "./_storage-setup.mjs";

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
