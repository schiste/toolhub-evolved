// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "vitest";
import { installStorage } from "./_storage-setup.mjs";
import { saveToListControl } from "../../public_html/lib/molecules/savemenu.js";
import { icon } from "../../public_html/lib/atoms/icon.js";

let store;
beforeEach(() => {
	store = installStorage();
});
afterEach(() => {
	store.clear();
});

const LISTS_KEY = "thdemo:lists";

const wrap = (items) =>
	'<details class="savemenu">' +
	"\n\t\t" +
	`<summary class="btn btn--outline">${icon("bookmark")} Save to a list</summary>` +
	"\n\t\t" +
	`<div class="savemenu__pop">${items}<a class="savemenu__new" href="/lists/create">${icon("add")} New list…</a></div>` +
	"\n\t" +
	"</details>";

test("saveToListControl() shows an empty-state message when there are no lists", () => {
	assert.equal(saveToListControl("toolA"), wrap('<p class="savemenu__empty">No lists yet.</p>'));
});

test("saveToListControl() renders a button per list, marking membership", () => {
	store.setItem(
		LISTS_KEY,
		JSON.stringify([
			{ id: "l1", title: "Favs", tools: ["toolA"] },
			{ id: "l2", title: "", tools: [] },
			{ id: "l3", tools: ["x"] }
		])
	);
	const itemOn =
		`<button class="savemenu__item is-on" type="button" data-listadd="l1" data-tn="toolA" aria-pressed="true">` +
		`<span class="savemenu__mark" aria-hidden="true">${icon("check")}</span> <span dir="auto">Favs</span></button>`;
	const itemEmptyTitle =
		`<button class="savemenu__item" type="button" data-listadd="l2" data-tn="toolA" aria-pressed="false">` +
		`<span class="savemenu__mark" aria-hidden="true">${icon("add")}</span> <span>Untitled list</span></button>`;
	const itemNoTitle =
		`<button class="savemenu__item" type="button" data-listadd="l3" data-tn="toolA" aria-pressed="false">` +
		`<span class="savemenu__mark" aria-hidden="true">${icon("add")}</span> <span>Untitled list</span></button>`;
	assert.equal(saveToListControl("toolA"), wrap(itemOn + itemEmptyTitle + itemNoTitle));
});

test("saveToListControl() treats a tool-less list as not containing the tool", () => {
	// l has no `tools`, so `(l.tools || [])` must be []. The probe name matches the
	// ArrayDeclaration sentinel, so a non-empty fallback would flip membership on.
	store.setItem(LISTS_KEY, JSON.stringify([{ id: "l1", title: "X" }]));
	const item =
		`<button class="savemenu__item" type="button" data-listadd="l1" data-tn="Stryker was here" aria-pressed="false">` +
		`<span class="savemenu__mark" aria-hidden="true">${icon("add")}</span> <span dir="auto">X</span></button>`;
	assert.equal(saveToListControl("Stryker was here"), wrap(item));
});
