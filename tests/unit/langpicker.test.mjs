// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { beforeEach, test } from "vitest";
import {
	closeLangMenu,
	renderLangPicker,
	selectionNote,
	showLangNote,
	toggleLangMenu
} from "../../public_html/lib/organisms/langpicker.js";
import { esc } from "../../public_html/lib/core/dom.js";
import { localeDir } from "../../public_html/lib/core/i18n.js";
import { icon } from "../../public_html/lib/atoms/icon.js";

// Hardcoded copies of the in-file constants so a source mutation to them is not
// masked by the oracle reading the same mutated value.
const ACTIVE = "en";
const LANGUAGES = [
	["en", "English", "English"],
	["fr", "Français", "French"],
	["de", "Deutsch", "German"],
	["es", "Español", "Spanish"],
	["it", "Italiano", "Italian"],
	["pt", "Português", "Portuguese"],
	["nl", "Nederlands", "Dutch"],
	["pl", "Polski", "Polish"],
	["ru", "Русский", "Russian"],
	["uk", "Українська", "Ukrainian"],
	["sv", "Svenska", "Swedish"],
	["cs", "Čeština", "Czech"],
	["fi", "Suomi", "Finnish"],
	["el", "Ελληνικά", "Greek"],
	["tr", "Türkçe", "Turkish"],
	["ar", "العربية", "Arabic"],
	["he", "עברית", "Hebrew"],
	["fa", "فارسی", "Persian"],
	["ur", "اردو", "Urdu"],
	["hi", "हिन्दी", "Hindi"],
	["bn", "বাংলা", "Bengali"],
	["ta", "தமிழ்", "Tamil"],
	["th", "ไทย", "Thai"],
	["vi", "Tiếng Việt", "Vietnamese"],
	["id", "Bahasa Indonesia", "Indonesian"],
	["ja", "日本語", "Japanese"],
	["ko", "한국어", "Korean"],
	["zh", "中文", "Chinese"]
];

function activeEntry() {
	return LANGUAGES.find(([code]) => code === ACTIVE) || LANGUAGES[0];
}

function langPickerOracle() {
	const [, autonym] = activeEntry();
	return `\n\t\t<button class="lang__btn" id="lang-btn" type="button" aria-haspopup="true" aria-expanded="false" aria-controls="lang-menu" title="Choose a language">\n\t\t\t${icon("language", "lang__globe")}\n\t\t\t<span class="lang__current">${esc(autonym)}</span>\n\t\t\t${icon("chevronDown", "lang__caret")}\n\t\t</button>\n\t\t<div class="lang__menu" id="lang-menu" role="menu" aria-labelledby="lang-btn" hidden>\n\t\t\t<ul class="lang__list" role="none">\n\t\t\t\t${LANGUAGES.map(
		([code, native, english]) => {
			const isActive = code === ACTIVE;
			return `<li role="none"><button type="button" role="menuitemradio" aria-checked="${isActive}" class="lang__opt${isActive ? " is-active" : ""}" data-lang="${esc(code)}" data-lang-name="${esc(english)}" lang="${esc(code)}" dir="${localeDir(code)}">\n\t\t\t\t\t\t<span class="lang__native">${esc(native)}</span>\n\t\t\t\t\t\t<span class="lang__english">${esc(english)}</span>\n\t\t\t\t\t\t${isActive ? icon("check", "lang__check") : ""}\n\t\t\t\t\t</button></li>`;
		}
	).join(
		""
	)}\n\t\t\t</ul>\n\t\t\t<p class="lang__note" id="lang-note" role="status" aria-live="polite" hidden></p>\n\t\t</div>`;
}

/** Compare two HTML strings after identical DOM serialization. */
function htmlEqual(actual, expected, msg) {
	const a = document.createElement("div");
	const b = document.createElement("div");
	a.innerHTML = actual;
	b.innerHTML = expected;
	assert.equal(a.innerHTML, b.innerHTML, msg);
}

beforeEach(() => {
	document.body.innerHTML = "";
});

test("selectionNote exact copy for a named language", () => {
	assert.equal(
		selectionNote("French"),
		`<strong>French</strong> isn’t available yet. In the real Toolhub, languages are translated through translatewiki.net — this prototype is English only for now.`
	);
});

test("selectionNote escapes the name and handles null", () => {
	assert.equal(
		selectionNote("<b> & 'x'"),
		`<strong>&lt;b&gt; &amp; &#39;x&#39;</strong> isn’t available yet. In the real Toolhub, languages are translated through translatewiki.net — this prototype is English only for now.`
	);
	assert.equal(
		selectionNote(null),
		`<strong></strong> isn’t available yet. In the real Toolhub, languages are translated through translatewiki.net — this prototype is English only for now.`
	);
});

test("renderLangPicker no-ops when #langpicker is absent", () => {
	renderLangPicker();
	assert.equal(document.body.innerHTML, "");
});

test("renderLangPicker emits the exact picker markup", () => {
	document.body.innerHTML = `<div id="langpicker"></div>`;
	renderLangPicker();
	const el = /** @type {HTMLElement} */ (document.querySelector("#langpicker"));
	htmlEqual(el.innerHTML, langPickerOracle());
	// English is the active entry: its option is checked and active.
	const en = /** @type {HTMLElement} */ (el.querySelector('[data-lang="en"]'));
	assert.equal(en.getAttribute("aria-checked"), "true");
	assert.ok(en.classList.contains("is-active"));
	const fr = /** @type {HTMLElement} */ (el.querySelector('[data-lang="fr"]'));
	assert.equal(fr.getAttribute("aria-checked"), "false");
	assert.ok(!fr.classList.contains("is-active"));
	// Active option has a check icon; inactive does not.
	assert.ok(en.querySelector(".lang__check"));
	assert.equal(fr.querySelector(".lang__check"), null);
});

function menuFixture() {
	document.body.innerHTML = `
		<button id="lang-btn" aria-expanded="false"></button>
		<div id="lang-menu" hidden>
			<button class="lang__opt" data-lang="en"></button>
			<button class="lang__opt" data-lang="fr"></button>
		</div>
		<p id="lang-note" hidden>old</p>`;
}

test("closeLangMenu hides menu, resets aria-expanded and note", () => {
	menuFixture();
	const m = /** @type {HTMLElement} */ (document.querySelector("#lang-menu"));
	const b = /** @type {HTMLElement} */ (document.querySelector("#lang-btn"));
	const note = /** @type {HTMLElement} */ (document.querySelector("#lang-note"));
	m.hidden = false;
	b.setAttribute("aria-expanded", "true");
	note.hidden = false;
	closeLangMenu();
	assert.equal(m.hidden, true);
	assert.equal(b.getAttribute("aria-expanded"), "false");
	assert.equal(note.hidden, true);
});

test("closeLangMenu tolerates missing elements", () => {
	document.body.innerHTML = "";
	assert.doesNotThrow(() => closeLangMenu());
});

test("toggleLangMenu opens a hidden menu and focuses first option", () => {
	menuFixture();
	const m = /** @type {HTMLElement} */ (document.querySelector("#lang-menu"));
	const b = /** @type {HTMLElement} */ (document.querySelector("#lang-btn"));
	const first = /** @type {HTMLElement} */ (document.querySelector(".lang__opt"));
	toggleLangMenu();
	assert.equal(m.hidden, false);
	assert.equal(b.getAttribute("aria-expanded"), "true");
	assert.equal(document.activeElement, first);
});

test("toggleLangMenu closes an open menu and hides the note", () => {
	menuFixture();
	const m = /** @type {HTMLElement} */ (document.querySelector("#lang-menu"));
	const b = /** @type {HTMLElement} */ (document.querySelector("#lang-btn"));
	const note = /** @type {HTMLElement} */ (document.querySelector("#lang-note"));
	m.hidden = false;
	b.setAttribute("aria-expanded", "true");
	note.hidden = false;
	const opt = /** @type {HTMLElement} */ (document.querySelector(".lang__opt"));
	opt.focus();
	const before = document.activeElement;
	toggleLangMenu();
	assert.equal(m.hidden, true);
	assert.equal(b.getAttribute("aria-expanded"), "false");
	assert.equal(note.hidden, true);
	// On close it returns before touching focus.
	assert.equal(document.activeElement, before);
});

test("toggleLangMenu no-ops without a menu", () => {
	document.body.innerHTML = `<button id="lang-btn"></button>`;
	assert.doesNotThrow(() => toggleLangMenu());
});

test("toggleLangMenu opens even when the button is missing", () => {
	// `if (b)` guard with b absent: a mutant forcing it true throws on null.
	document.body.innerHTML = `<div id="lang-menu" hidden><button class="lang__opt">en</button></div>`;
	const m = /** @type {HTMLElement} */ (document.querySelector("#lang-menu"));
	const first = /** @type {HTMLElement} */ (document.querySelector(".lang__opt"));
	assert.doesNotThrow(() => toggleLangMenu());
	assert.equal(m.hidden, false);
	assert.equal(document.activeElement, first);
});

test("toggleLangMenu closes even when the note is missing", () => {
	// Closing path `if (note)` guard with note absent: a mutant forcing it true throws.
	document.body.innerHTML = `
		<button id="lang-btn" aria-expanded="true"></button>
		<div id="lang-menu"><button class="lang__opt">en</button></div>`;
	const m = /** @type {HTMLElement} */ (document.querySelector("#lang-menu"));
	const b = /** @type {HTMLElement} */ (document.querySelector("#lang-btn"));
	m.hidden = false; // open -> toggling closes it
	assert.doesNotThrow(() => toggleLangMenu());
	assert.equal(m.hidden, true);
	assert.equal(b.getAttribute("aria-expanded"), "false");
});

test("toggleLangMenu opens an option-less menu without focusing", () => {
	// Opening path `if (first)` guard with no option: a mutant forcing it true throws.
	document.body.innerHTML = `
		<button id="lang-btn" aria-expanded="false"></button>
		<div id="lang-menu" hidden><span>no options</span></div>`;
	const m = /** @type {HTMLElement} */ (document.querySelector("#lang-menu"));
	document.body.focus();
	const before = document.activeElement;
	assert.doesNotThrow(() => toggleLangMenu());
	assert.equal(m.hidden, false);
	assert.equal(document.activeElement, before);
});

test("showLangNote fills and reveals the note", () => {
	document.body.innerHTML = `<p id="lang-note" hidden></p>`;
	const note = /** @type {HTMLElement} */ (document.querySelector("#lang-note"));
	showLangNote("German");
	assert.equal(note.hidden, false);
	htmlEqual(note.innerHTML, selectionNote("German"));
});

test("showLangNote no-ops when the note is absent", () => {
	document.body.innerHTML = "";
	assert.doesNotThrow(() => showLangNote("German"));
});
