// SPDX-License-Identifier: GPL-3.0-or-later
import { dirAttrs, esc } from "../core/dom.js";
import { demoLists } from "../core/store.js";

// "Save to a list" control: a native <details> menu of the user's demo lists.
export function saveToListControl(name) {
	const items = demoLists().map((l) => {
		const inIt = (l.tools || []).indexOf(name) !== -1;
		return `<button class="savemenu__item${inIt ? " is-on" : ""}" type="button" data-listadd="${esc(l.id)}" data-tn="${esc(name)}" aria-pressed="${inIt}"><span class="savemenu__mark" aria-hidden="true">${inIt ? "✓" : "＋"}</span> <span${dirAttrs(l.title)}>${esc(l.title || "Untitled list")}</span></button>`;
	}).join("") || '<p class="savemenu__empty">No lists yet.</p>';
	return `<details class="savemenu">
		<summary class="btn btn--outline"><span aria-hidden="true">🔖</span> Save to a list</summary>
		<div class="savemenu__pop">${items}<a class="savemenu__new" href="#/lists/create"><span aria-hidden="true">＋</span> New list…</a></div>
	</details>`;
}
