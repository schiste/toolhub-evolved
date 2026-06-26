// SPDX-License-Identifier: GPL-3.0-or-later
import { esc } from "../core/dom.js";
import { fmt, plural } from "../core/i18n.js";
import { synthThanks, synthUsage } from "../core/synth.js";
import { icon } from "./icon.js";

/** @param {Tool} t */
export function thanksBlock(t) {
	const thanks = synthThanks(t.name);
	// Stryker disable StringLiteral: synthThanks() returns 3 + (seed % 140) ∈ [3, 142], never 1, so plural() always selects the "other" form and the singular "person thanked" is unreachable. The guard spans the template literal (the form sits on an interpolated line that cannot carry its own JS comment); the co-disabled static class names / icon arg / "people thanked" remain verified by the thanksBlock assertion.
	return `<div class="thanks__agg">
						<span class="thanks__icon" aria-hidden="true">${icon("heart")}</span>
						<span class="thanks__score">${esc(fmt(thanks))}</span>
						<span class="thanks__count">${esc(plural(thanks, { one: "person thanked", other: "people thanked" }))}</span>
					</div>`;
	// Stryker restore StringLiteral
}
/** @param {Tool} t */
export function usageBlock(t) {
	const u = synthUsage(t.name);
	// Stryker disable next-line StringLiteral: synthUsage() returns 50 + (seed % 9000) ∈ [50, 9049], never 1, so plural() always selects the "other" form and the singular "editor used" is unreachable. (Co-disables the asserted "usage"/"editors used"/"…30 days" literals on this line.)
	return `<p class="usage"><strong>${fmt(u)}</strong> ${plural(u, { one: "editor used", other: "editors used" })} this in the last 30 days</p>`;
}
