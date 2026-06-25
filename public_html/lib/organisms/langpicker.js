// SPDX-License-Identifier: GPL-3.0-or-later
import { esc } from "../core/dom.js";
import { localeDir } from "../core/i18n.js";
import { icon } from "../atoms/icon.js";

// The active locale of this prototype. The real Toolhub UI is localised through
// translatewiki.net (the Wikimedia translation platform), but this demo ships
// English copy only — so the picker is honest about that (see selectionNote).
const ACTIVE = "en";

// A representative slice of the languages Toolhub is translated into on
// translatewiki.net. Each entry is [code, autonym (native name), English name].
// Ordered to put the most-used Wikimedia content languages first; the list is
// illustrative, not exhaustive (translatewiki carries 300+).
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

// The "small popin" copy shown after a language is chosen. This is the product
// voice of the prototype, so it lives in one place and is easy to retune.
export function selectionNote(englishName) {
	return `<strong>${esc(englishName)}</strong> isn’t available yet. In the real Toolhub, languages are translated through translatewiki.net — this prototype is English only for now.`;
}

export function renderLangPicker() {
	const el = document.querySelector("#langpicker");
	if (!el) return;
	const [, autonym] = activeEntry();
	el.innerHTML = `
		<button class="lang__btn" id="lang-btn" type="button" aria-haspopup="true" aria-expanded="false" aria-controls="lang-menu" title="Choose a language">
			${icon("language", "lang__globe")}
			<span class="lang__current">${esc(autonym)}</span>
			${icon("chevronDown", "lang__caret")}
		</button>
		<div class="lang__menu" id="lang-menu" role="menu" aria-labelledby="lang-btn" hidden>
			<ul class="lang__list" role="none">
				${LANGUAGES.map(([code, native, english]) => {
					const isActive = code === ACTIVE;
					return `<li role="none"><button type="button" role="menuitemradio" aria-checked="${isActive}" class="lang__opt${isActive ? " is-active" : ""}" data-lang="${esc(code)}" data-lang-name="${esc(english)}" lang="${esc(code)}" dir="${localeDir(code)}">
						<span class="lang__native">${esc(native)}</span>
						<span class="lang__english">${esc(english)}</span>
						${isActive ? icon("check", "lang__check") : ""}
					</button></li>`;
				}).join("")}
			</ul>
			<p class="lang__note" id="lang-note" role="status" aria-live="polite" hidden></p>
		</div>`;
}

export function closeLangMenu() {
	const m = document.querySelector("#lang-menu"),
		b = document.querySelector("#lang-btn"),
		note = document.querySelector("#lang-note");
	if (m) m.hidden = true;
	if (b) b.setAttribute("aria-expanded", "false");
	if (note) note.hidden = true; // reset the popin so it re-announces next time
}

export function toggleLangMenu() {
	const m = document.querySelector("#lang-menu"),
		b = document.querySelector("#lang-btn");
	if (!m) return;
	const willOpen = m.hidden;
	m.hidden = !willOpen;
	b.setAttribute("aria-expanded", String(willOpen));
	if (!willOpen) {
		const note = document.querySelector("#lang-note");
		if (note) note.hidden = true;
		return;
	}
	const first = m.querySelector(".lang__opt");
	if (first) first.focus();
}

// Reveal the "not available yet" popin for the chosen language without changing
// the active locale — the prototype stays English only.
export function showLangNote(englishName) {
	const note = document.querySelector("#lang-note");
	if (!note) return;
	note.innerHTML = selectionNote(englishName);
	note.hidden = false;
}
