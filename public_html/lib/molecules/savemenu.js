// SPDX-License-Identifier: GPL-3.0-or-later
import { dirAttrs, esc } from "../core/dom.js";
import { demoLists } from "../core/store.js";
import { icon } from "../atoms/icon.js";

// "Save to a list" control: a native <details> menu of the user's demo lists.
/**
 * @param {string} name
 * @returns {string}
 */
export function saveToListControl(name) {
	const items =
		demoLists()
			.map(
				/** @param {{ id: string; title?: string; tools?: string[] }} l */ (l) => {
					const inIt = (l.tools || []).includes(name);
					return `<button class="savemenu__item${inIt ? " is-on" : ""}" type="button" data-listadd="${esc(l.id)}" data-tn="${esc(name)}" aria-pressed="${inIt}"><span class="savemenu__mark" aria-hidden="true">${inIt ? icon("check") : icon("add")}</span> <span${dirAttrs(l.title)}>${esc(l.title || "Untitled list")}</span></button>`;
				}
			)
			.join("") || '<p class="savemenu__empty">No lists yet.</p>';
	return `<details class="savemenu">
		<summary class="btn btn--outline">${icon("bookmark")} Save to a list</summary>
		<div class="savemenu__pop">${items}<a class="savemenu__new" href="/lists/create">${icon("add")} New list…</a></div>
	</details>`;
}
