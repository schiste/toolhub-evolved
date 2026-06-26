// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { beforeEach, test } from "vitest";
// Side-effecting import FIRST: installs a working localStorage before i18n.js
// reads it at module-evaluation time (LOCALE = appLocale()).
import { installStorage } from "./_storage-setup.mjs";
import * as i18n from "../../public_html/lib/core/i18n.js";
import { esc } from "../../public_html/lib/core/dom.js";

beforeEach(() => {
	installStorage();
});

// The module computes LOCALE from localStorage at import time; localStorage is
// empty in a fresh happy-dom env, so LOCALE === "en" and the Intl formatters are
// bound to "en". The expected strings below are the real "en" outputs.

test("DEFAULT_LOCALE and RTL_LANGS are the expected constants", () => {
	assert.equal(i18n.DEFAULT_LOCALE, "en");
	for (const lang of ["ar", "arc", "ckb", "dv", "fa", "ha", "he", "khw", "ks", "ku", "ps", "sd", "ug", "ur", "yi"]) {
		assert.equal(i18n.localeDir(lang), "rtl", `${lang} should be RTL`);
	}
});

test("appLocale reads storage, defaults to en, and normalizes underscores", () => {
	localStorage.removeItem("toolhub-locale");
	assert.equal(i18n.appLocale(), "en");
	localStorage.setItem("toolhub-locale", "he");
	assert.equal(i18n.appLocale(), "he");
	localStorage.setItem("toolhub-locale", "pt_BR");
	assert.equal(i18n.appLocale(), "pt-BR");
	localStorage.removeItem("toolhub-locale");
});

test("localeDir splits on '-', lowercases, and defaults to ltr", () => {
	assert.equal(i18n.localeDir("ar"), "rtl");
	assert.equal(i18n.localeDir("ar-EG"), "rtl");
	assert.equal(i18n.localeDir("AR"), "rtl");
	assert.equal(i18n.localeDir("en"), "ltr");
	assert.equal(i18n.localeDir("de-DE"), "ltr");
	assert.equal(i18n.localeDir("EN-us"), "ltr");
});

test("applyLocaleAttrs writes lang and dir onto the document element", () => {
	document.documentElement.lang = "zz";
	document.documentElement.dir = "rtl";
	i18n.applyLocaleAttrs();
	assert.equal(document.documentElement.lang, "en");
	assert.equal(document.documentElement.dir, "ltr");
});

test("fmt and compactFmt format en numbers and coerce junk to 0", () => {
	assert.equal(i18n.fmt(1234), "1,234");
	assert.equal(i18n.fmt(7), "7");
	assert.equal(i18n.fmt(0), "0");
	assert.equal(i18n.fmt(null), "0");
	assert.equal(i18n.fmt("nope"), "0");
	assert.equal(i18n.compactFmt(1500), "1.5K");
	assert.equal(i18n.compactFmt(1234567), "1.2M");
	assert.equal(i18n.compactFmt(7), "7");
	assert.equal(i18n.compactFmt(null), "0");
});

test("plural selects the en category and falls back through other/one/empty", () => {
	assert.equal(i18n.plural(1, { one: "ONE", other: "OTHER" }), "ONE");
	assert.equal(i18n.plural(2, { one: "ONE", other: "OTHER" }), "OTHER");
	assert.equal(i18n.plural(-1, { one: "ONE", other: "OTHER" }), "ONE");
	assert.equal(i18n.plural(2, { one: "ONE" }), "ONE"); // no other => one
	assert.equal(i18n.plural(2, {}), ""); // nothing => empty
});

test("countLabel pairs formatted count with the right plural form", () => {
	assert.equal(i18n.countLabel(1, "view", "views"), "1 view");
	assert.equal(i18n.countLabel(5, "view", "views"), "5 views");
	assert.equal(i18n.countLabel(7, "view", "views"), "7 views");
	assert.equal(i18n.countLabel(0, "view", "views"), "0 views");
	assert.equal(i18n.countLabel("x", "view", "views"), "0 views");
});

test("views combines compact count with the plural noun", () => {
	assert.equal(i18n.views(1), "1 view");
	assert.equal(i18n.views(5), "5 views");
	assert.equal(i18n.views(0), "0 views");
	assert.equal(i18n.views(1500), "1.5K views");
});

test("relativeTime walks day/month/year tiers around a fixed now", () => {
	const realNow = Date.now;
	const now = Date.parse("2026-06-25T00:00:00Z");
	Date.now = () => now;
	try {
		assert.equal(i18n.relativeTime(""), "");
		assert.equal(i18n.relativeTime(null), "");
		assert.equal(i18n.relativeTime("not-a-date"), "");

		const iso = (ms) => new Date(now + ms).toISOString();
		const DAY = 86400000;
		assert.equal(i18n.relativeTime(iso(0)), "today");
		// sub-day but rounds to a non-zero day: still in the < 1 day tier => "today"
		// (the day tier would round to -1 => "yesterday").
		assert.equal(i18n.relativeTime(iso(-0.6 * DAY)), "today");
		assert.equal(i18n.relativeTime(iso(-DAY)), "yesterday"); // exactly 1 day boundary
		assert.equal(i18n.relativeTime(iso(-5 * DAY)), "5 days ago");
		assert.equal(i18n.relativeTime(iso(-30 * DAY)), "last month"); // exactly 30-day boundary
		assert.equal(i18n.relativeTime(iso(-60 * DAY)), "2 months ago");
		assert.equal(i18n.relativeTime(iso(-365 * DAY)), "last year"); // exactly 365-day boundary
		assert.equal(i18n.relativeTime(iso(-800 * DAY)), "2 years ago");
	} finally {
		Date.now = realNow;
	}
});

test("relTime prefixes a non-empty relative time with 'Updated '", () => {
	const realNow = Date.now;
	const now = Date.parse("2026-06-25T00:00:00Z");
	Date.now = () => now;
	try {
		assert.equal(i18n.relTime(new Date(now).toISOString()), "Updated today");
		assert.equal(i18n.relTime(""), "");
		assert.equal(i18n.relTime("not-a-date"), "");
	} finally {
		Date.now = realNow;
	}
});

test("timeTag builds a <time> element, honoring class and explicit text", () => {
	const realNow = Date.now;
	const now = Date.parse("2026-06-25T00:00:00Z");
	Date.now = () => now;
	const dtf = new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short" });
	try {
		assert.equal(i18n.timeTag(""), "");
		assert.equal(i18n.timeTag("not-a-date"), "");
		// null is caught only by the `!iso` guard: new Date(null) is the epoch (a
		// VALID date), so without the guard it would render a <time> tag.
		assert.equal(i18n.timeTag(null), "");
		assert.equal(i18n.timeTag(undefined), "");

		const isoIn = "2026-05-01T12:00:00Z";
		const date = new Date(isoIn);
		const title = esc(dtf.format(date));
		const dt = esc(date.toISOString());

		// explicit text, no class
		assert.equal(i18n.timeTag(isoIn, null, "Custom"), `<time datetime="${dt}" title="${title}">Custom</time>`);
		// explicit text, with class (class is escaped)
		assert.equal(
			i18n.timeTag(isoIn, "a&b", "Custom"),
			`<time class="a&amp;b" datetime="${dt}" title="${title}">Custom</time>`
		);
		// label text is escaped
		assert.equal(i18n.timeTag(isoIn, null, "<x>"), `<time datetime="${dt}" title="${title}">&lt;x&gt;</time>`);
		// default label falls back to relativeTime
		assert.equal(
			i18n.timeTag(new Date(now).toISOString(), null),
			`<time datetime="${esc(new Date(now).toISOString())}" title="${esc(dtf.format(new Date(now)))}">today</time>`
		);
	} finally {
		Date.now = realNow;
	}
});

test("updatedTimeTag uses the 'Updated …' relative label", () => {
	const realNow = Date.now;
	const now = Date.parse("2026-06-25T00:00:00Z");
	Date.now = () => now;
	const dtf = new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short" });
	try {
		const d = new Date(now);
		assert.equal(
			i18n.updatedTimeTag(d.toISOString()),
			`<time datetime="${esc(d.toISOString())}" title="${esc(dtf.format(d))}">Updated today</time>`
		);
		assert.equal(i18n.updatedTimeTag(""), "");
	} finally {
		Date.now = realNow;
	}
});

test("LOCALE is the resolved default locale", () => {
	assert.equal(i18n.LOCALE, "en");
});
