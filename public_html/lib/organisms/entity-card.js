// SPDX-License-Identifier: GPL-3.0-or-later
import { dirAttrs, esc } from "../core/dom.js";

/**
 * Render non-tool search results through the catalog card grammar.
 *
 * The component owns escaping and structure. Callers only adapt domain facts
 * into the card's semantic slots.
 *
 * @param {{
 *  kind: string,
 *  kindDetail?: string,
 *  title: string,
 *  href?: string,
 *  visual: string,
 *  subtitle?: string,
 *  description?: string,
 *  metrics?: Array<{label: string, value: string, detail?: string}>,
 *  tags?: Array<{label: string, className?: string}>,
 *  signals?: Array<{label: string, className?: string}>,
 *  className?: string,
 *  dataName?: string,
 *  static?: boolean
 * }} card
 */
export function entityCard(card) {
	const classes = ["tcard", "entity-card", card.className || "", card.static ? "entity-card--static" : ""]
		.filter(Boolean)
		.join(" ");
	const title = card.href
		? `<a class="tcard__title" href="${esc(card.href)}"${dirAttrs(card.title)}>${esc(card.title)}</a>`
		: `<span class="tcard__title"${dirAttrs(card.title)}>${esc(card.title)}</span>`;
	const tags = (card.tags || [])
		.map(
			(tag) =>
				`<span class="tag entity-card__tag${tag.className ? ` ${esc(tag.className)}` : ""}"${dirAttrs(tag.label)}>${esc(tag.label)}</span>`
		)
		.join("");
	const signals = (card.signals || [])
		.map(
			(signal) =>
				`<span class="${esc(signal.className || "signal signal--compact")}"${dirAttrs(signal.label)}>${esc(signal.label)}</span>`
		)
		.join("");
	const metrics = (card.metrics || [])
		.map(
			(metric) =>
				`<div class="entity-card__metric"><dt${dirAttrs(metric.label)}>${esc(metric.label)}</dt><dd${dirAttrs(metric.value)}><strong>${esc(metric.value)}</strong>${metric.detail ? `<small${dirAttrs(metric.detail)}>${esc(metric.detail)}</small>` : ""}</dd></div>`
		)
		.join("");
	return `<article class="${classes}"${card.dataName ? ` data-entity-name="${esc(card.dataName)}"` : ""}>
		<div class="tcard__topline"><span class="tcard__meta">${esc(card.kind)}</span><span class="tcard__topmeta">${esc(card.kindDetail || "")}</span></div>
		<div class="tcard__head">
			${card.visual}
			<div class="tcard__heading">${title}${card.subtitle ? `<div class="tcard__maint entity-card__subtitle"${dirAttrs(card.subtitle)}>${esc(card.subtitle)}</div>` : ""}</div>
		</div>
		<p class="tcard__desc"${dirAttrs(card.description || "")}>${esc(card.description || "")}</p>
		${metrics ? `<dl class="entity-card__metrics">${metrics}</dl>` : ""}
		<div class="tcard__tags entity-card__tags">${tags}</div>
		<div class="tcard__signals entity-card__signals">${signals ? `<div class="tcard__signal-row entity-card__signal-row">${signals}</div>` : ""}</div>
	</article>`;
}
