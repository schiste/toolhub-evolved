// SPDX-License-Identifier: GPL-3.0-or-later
import { esc } from "../core/dom.js";
import { fmt, plural } from "../core/i18n.js";
import { synthThanks, synthUsage } from "../core/synth.js";
import { icon } from "./icon.js";

/** @param {Tool} t */
export function thanksBlock(t) {
	const thanks = synthThanks(t.name);
	return `<div class="thanks__agg">
						<span class="thanks__icon" aria-hidden="true">${icon("heart")}</span>
						<span class="thanks__score">${esc(fmt(thanks))}</span>
						<span class="thanks__count">${esc(plural(thanks, { one: "person thanked", other: "people thanked" }))}</span>
					</div>`;
}
/** @param {Tool} t */
export function usageBlock(t) {
	const u = synthUsage(t.name);
	return `<p class="usage"><strong>${fmt(u)}</strong> ${plural(u, { one: "editor used", other: "editors used" })} this in the last 30 days</p>`;
}
