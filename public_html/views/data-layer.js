// SPDX-License-Identifier: GPL-3.0-or-later
import { esc } from "../lib/core/dom.js";
import { mountJsonReport } from "../lib/organisms/json-report.js";
import { t } from "../lib/core/i18n.js";
import { button } from "../lib/atoms/button.js";
import { loadingRegion, skeletonLine } from "../lib/molecules/skeleton.js";

export const STYLESHEET = "/styles/data-layer.css";

const SKELETON_ROWS = 8;

/** @param {unknown} value */
function count(value) {
	return new Intl.NumberFormat().format(Number(value) || 0);
}

/** @param {unknown} value */
function dateLabel(value) {
	const date = new Date(String(value || ""));
	return Number.isNaN(date.getTime())
		? t("dataLayer.dateUnavailable", "Date unavailable")
		: new Intl.DateTimeFormat(undefined, { dateStyle: "long", timeStyle: "short" }).format(date);
}

/** @param {string} value */
function fieldLabel(value) {
	return value.replaceAll(/[_-]+/g, " ").replace(/^./, (letter) => letter.toUpperCase());
}

/**
 * The four buckets, in reading order, with the label and the one-line claim
 * each makes about who supplied a value.
 * @param {string} bucket
 */
function bucketLabel(bucket) {
	switch (bucket) {
		case "human":
			return t("dataLayer.bucketHuman", "Human");
		case "toolinfo":
			return t("dataLayer.bucketToolinfo", "Toolinfo");
		case "code":
			return t("dataLayer.bucketCode", "Code analysis");
		case "ai":
			return t("dataLayer.bucketAi", "AI generated");
		default:
			return bucket;
	}
}

/** @param {string} bucket */
function bucketBlurb(bucket) {
	switch (bucket) {
		case "human":
			return t(
				"dataLayer.bucketHumanBlurb",
				"A person wrote this: a reviewed local correction, or a fact declared on a wiki."
			);
		case "toolinfo":
			return t(
				"dataLayer.bucketToolinfoBlurb",
				"A machine-readable toolinfo record declared it — the official catalog or a feed it points at."
			);
		case "code":
			return t(
				"dataLayer.bucketCodeBlurb",
				"Read off the source code by static analysis. Nobody asserted it, but it can fill an empty field."
			);
		case "ai":
			return t(
				"dataLayer.bucketAiBlurb",
				"Written by a language model. Fill-only: it never replaces a value another source stated."
			);
		default:
			return "";
	}
}

/**
 * One stacked bar of per-bucket counts, plus the unfilled remainder.
 * @param {Record<string, number>} primary @param {number} total @param {number} filled
 */
function stackedBar(primary, total, filled) {
	if (!total) return "";
	const segments = ["human", "toolinfo", "code", "ai"]
		.map((bucket) => ({ bucket, value: Number(primary?.[bucket]) || 0 }))
		.filter((segment) => segment.value > 0)
		.map(
			(segment) =>
				`<span class="data-layer-bar__seg data-layer-bar__seg--${esc(segment.bucket)}" style="--share:${(segment.value * 100) / total}" title="${esc(`${bucketLabel(segment.bucket)}: ${count(segment.value)}`)}"></span>`
		)
		.join("");
	const missing = Math.max(0, total - filled);
	const rest =
		missing > 0
			? `<span class="data-layer-bar__seg data-layer-bar__seg--missing" style="--share:${(missing * 100) / total}" title="${esc(`${t("dataLayer.missing", "Not filled")}: ${count(missing)}`)}"></span>`
			: "";
	return `<div class="data-layer-bar" role="img" aria-label="${esc(barLabel(primary, missing))}">${segments}${rest}</div>`;
}

/** @param {Record<string, number>} primary @param {number} missing */
function barLabel(primary, missing) {
	const parts = ["human", "toolinfo", "code", "ai"]
		.filter((bucket) => (Number(primary?.[bucket]) || 0) > 0)
		.map((bucket) => `${bucketLabel(bucket)} ${count(primary[bucket])}`);
	if (missing > 0) parts.push(`${t("dataLayer.missing", "Not filled")} ${count(missing)}`);
	return parts.join(", ");
}

/** @param {any} payload */
function legendHTML(payload) {
	const sources = payload?.sourcesByBucket || {};
	const confidence = payload?.sourceConfidence || {};
	return `<section class="data-layer-legend" aria-labelledby="data-layer-legend-title">
		<h2 id="data-layer-legend-title">${esc(t("dataLayer.legendTitle", "Where a value can come from"))}</h2>
		<p class="data-layer-legend__intro">${esc(t("dataLayer.legendIntro", "Each field is attributed to the single highest-confidence source that supplied its effective value."))}</p>
		<dl class="data-layer-legend__list">
			${["human", "toolinfo", "code", "ai"]
				.map((bucket) => {
					const names = Array.isArray(sources[bucket]) ? sources[bucket] : [];
					const chips = names
						.map(
							(name) =>
								`<li><code>${esc(name)}</code><span>${esc(String(confidence[name] ?? "—"))}</span></li>`
						)
						.join("");
					return `<div class="data-layer-legend__item">
						<dt><span class="data-layer-swatch data-layer-swatch--${esc(bucket)}" aria-hidden="true"></span>${esc(bucketLabel(bucket))}</dt>
						<dd><p>${esc(bucketBlurb(bucket))}</p><ul class="data-layer-sources">${chips}</ul></dd>
					</div>`;
				})
				.join("")}
		</dl>
	</section>`;
}

/** @param {any} payload */
function summaryHTML(payload) {
	const overall = payload?.overall || {};
	const tools = Number(payload?.tools) || 0;
	const primary = overall?.primary || {};
	const filled = Number(overall?.filled) || 0;
	const slots = Number(overall?.slots) || 0;
	return `<section class="data-layer-summary" aria-labelledby="data-layer-summary-title">
		<h2 id="data-layer-summary-title">${esc(t("dataLayer.summaryTitle", "Overall filling"))}</h2>
		<p class="data-layer-summary__lead">${esc(
			t("dataLayer.summaryLead", "Across every projected field on every tool.")
		)}</p>
		<p class="data-layer-summary__figure"><strong>${esc(`${count(filled)} / ${count(slots)}`)}</strong><span>${esc(`${Number(overall?.percent) || 0}%`)}</span></p>
		${stackedBar(primary, slots, filled)}
		<dl class="data-layer-ledger">
			${["human", "toolinfo", "code", "ai"]
				.map(
					(bucket) =>
						`<div class="data-layer-ledger__cell"><dt><span class="data-layer-swatch data-layer-swatch--${esc(bucket)}" aria-hidden="true"></span>${esc(bucketLabel(bucket))}</dt><dd>${esc(count(primary?.[bucket]))}</dd></div>`
				)
				.join("")}
			<div class="data-layer-ledger__cell"><dt>${esc(t("dataLayer.toolsCounted", "Tools counted"))}</dt><dd>${esc(count(tools))}</dd></div>
			<div class="data-layer-ledger__cell"><dt>${esc(t("dataLayer.toolsPending", "Not yet projected"))}</dt><dd>${esc(count(payload?.pendingTools))}</dd></div>
		</dl>
	</section>`;
}

/** @param {any} payload */
function fieldsHTML(payload) {
	const tools = Number(payload?.tools) || 0;
	/** @type {any[]} */
	const fields = Array.isArray(payload?.fields) ? payload.fields : [];
	const rows = fields
		.map(
			(entry) => `<tr>
				<th scope="row">
					<span class="data-layer-field">${esc(fieldLabel(String(entry?.field || "")))}</span>
					<code>${esc(String(entry?.field || ""))}</code>
					${entry?.kind === "list" ? `<span class="data-layer-tag">${esc(t("dataLayer.listField", "list"))}</span>` : ""}
				</th>
				<td class="data-layer-cell--figure"><strong>${esc(`${Number(entry?.percent) || 0}%`)}</strong><span>${esc(`${count(entry?.filled)} / ${count(tools)}`)}</span></td>
				<td class="data-layer-cell--bar">${stackedBar(entry?.primary || {}, tools, Number(entry?.filled) || 0)}</td>
			</tr>`
		)
		.join("");
	return `<section class="data-layer-fields" aria-labelledby="data-layer-fields-title">
		<h2 id="data-layer-fields-title">${esc(t("dataLayer.fieldsTitle", "Filling by field"))}</h2>
		<p class="data-layer-fields__intro">${esc(
			t(
				"dataLayer.fieldsIntro",
				"Every projected field, most complete first, with the source that supplied each value."
			)
		)}</p>
		<div class="data-layer-table-wrap">
			<table class="data-layer-table">
				<thead><tr>
					<th scope="col">${esc(t("dataLayer.colField", "Field"))}</th>
					<th scope="col">${esc(t("dataLayer.colFilled", "Filled"))}</th>
					<th scope="col">${esc(t("dataLayer.colSources", "By source"))}</th>
				</tr></thead>
				<tbody>${rows}</tbody>
			</table>
		</div>
	</section>`;
}

/** @param {any} payload */
export function dataLayerHTML(payload) {
	const fields = Array.isArray(payload?.fields) ? [...payload.fields] : [];
	// Sorting here rather than in the snapshot: the payload is a stable
	// document other clients read by field name, and the ordering is a
	// presentation choice this page makes.
	fields.sort((a, b) => (Number(b?.percent) || 0) - (Number(a?.percent) || 0));
	const ordered = { ...payload, fields };
	return `<article class="data-layer-report">
		<header class="data-layer-report__head">
			<div>
				<p class="data-layer-eyebrow">${esc(t("dataLayer.eyebrow", "Data layer"))}</p>
				<h1>${esc(t("dataLayer.title", "How the catalog got filled in"))}</h1>
				<p class="data-layer-intro">${esc(
					t(
						"dataLayer.intro",
						"Every value in the local catalog carries the evidence that produced it. This is what is filled, what is missing, and who supplied the rest."
					)
				)}</p>
			</div>
			<p class="data-layer-generated">${esc(t("dataLayer.generated", "Snapshot taken"))} ${esc(dateLabel(payload?.generatedAt))}</p>
		</header>
		${summaryHTML(payload)}
		${fieldsHTML(ordered)}
		${legendHTML(payload)}
	</article>`;
}

const loadingHTML = () =>
	loadingRegion({
		label: t("dataLayer.loading", "Reading catalog provenance"),
		className: "data-layer-loading",
		bodyClass: "data-layer-report",
		body: `<header class="data-layer-report__head">
			<div>
				${skeletonLine("skeleton--w-xs")}
				${skeletonLine("skeleton-page__title skeleton--w-md")}
				${skeletonLine("skeleton-page__intro skeleton--w-xl")}
			</div>
			<p>${skeletonLine("skeleton--w-lg")}</p>
		</header>
		<div class="data-layer-skeleton">${`<p>${skeletonLine("skeleton--w-xl")}</p>`.repeat(SKELETON_ROWS)}</div>`
	});

const errorHTML = () =>
	`<div class="data-layer-error" role="alert"><h1>${esc(t("dataLayer.errorTitle", "The data layer report is temporarily unavailable"))}</h1><p>${esc(t("dataLayer.errorBody", "The last provenance snapshot could not be loaded."))}</p>${button(t("dataLayer.retry", "Try again"), { attrs: "data-data-layer-retry" })}</div>`;

const mountDataLayer = mountJsonReport({
	name: "data-layer",
	endpoint: "/v1/coverage/",
	render: dataLayerHTML,
	renderLoading: loadingHTML,
	renderError: errorHTML
});

export function viewDataLayer() {
	return {
		title: t("dataLayer.docTitle", "Data layer — Toolhub"),
		html: `<div class="container page data-layer-page" data-data-layer-root>${loadingHTML()}</div>`,
		mount: mountDataLayer,
		styles: [STYLESHEET]
	};
}
