// SPDX-License-Identifier: GPL-3.0-or-later
import { $$, esc } from "../core/dom.js";
import { isFav } from "../core/store.js";

export function favBtn(name, opts) {
	opts = opts || {};
	const on = isFav(name);
	const txt = opts.label ? `<span class="favbtn__t">${on ? "Saved" : "Save"}</span>` : "";
	return `<button class="favbtn${on ? " is-on" : ""}${opts.cls ? " " + opts.cls : ""}" type="button" data-fav="${esc(name)}" aria-pressed="${on}" aria-label="${on ? "Remove from favorites" : "Save to favorites"}"><span class="favbtn__ic" aria-hidden="true">${on ? "★" : "☆"}</span>${txt}</button>`;
}
// Reflect a toggled favorite on its button(s) in place (no full re-render).
export function syncFavButtons(name, on) {
	$$("[data-fav]").filter((b) => b.getAttribute("data-fav") === name).forEach((b) => {
		b.classList.toggle("is-on", on);
		b.setAttribute("aria-pressed", String(on));
		b.setAttribute("aria-label", on ? "Remove from favorites" : "Save to favorites");
		const ic = b.querySelector(".favbtn__ic"); if (ic) ic.textContent = on ? "★" : "☆";
		const t = b.querySelector(".favbtn__t"); if (t) t.textContent = on ? "Saved" : "Save";
	});
}
