// SPDX-License-Identifier: GPL-3.0-or-later
import { esc } from "../core/dom.js";
import { countLabel, fmt, plural } from "../core/i18n.js";
import { starString, synthReviews, synthUsage } from "../core/synth.js";

export function reviewsBlock(t) {
	const r = synthReviews(t.name);
	return `<div class="reviews__agg">
						<span class="reviews__stars" aria-hidden="true">${starString(r.rating)}</span>
						<span class="reviews__score">${r.rating.toFixed(1)}</span>
						<span class="reviews__count">· ${esc(countLabel(r.count, "review", "reviews"))}</span>
					</div>`;
}
export function usageBlock(t) {
	const u = synthUsage(t.name);
	return `<p class="usage"><strong>${fmt(u)}</strong> ${plural(u, { one: "editor used", other: "editors used" })} this in the last 30 days</p>`;
}
