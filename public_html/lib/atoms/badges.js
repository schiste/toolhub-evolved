// SPDX-License-Identifier: GPL-3.0-or-later
import { esc } from "../core/dom.js";
import { views } from "../core/i18n.js";
import { synthHealth } from "../core/synth.js";
import { icon } from "./icon.js";

export function statusBadge(t) {
	const st = t.status || { level: "green", label: "Healthy" };
	return (t.deprecated || t.experimental) ? `<span class="status status--${st.level}"><span class="dot dot--${st.level}"></span>${esc(st.label)}</span>` : "";
}
export function healthBadge(t) {
	const h = synthHealth(t.name);
	return `<span class="status status--${h.level} experimental"><span class="dot dot--${h.level}"></span>${esc(h.label)}</span>`;
}
export function popularityBadge(t) { return `<span class="views experimental">${icon("popular")} ${views(t.weeklyViews)}</span>`; }
