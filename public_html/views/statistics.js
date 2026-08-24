// SPDX-License-Identifier: GPL-3.0-or-later
import { esc } from "../lib/core/dom.js";
import { mountJsonReport } from "../lib/organisms/json-report.js";
import { t } from "../lib/core/i18n.js";
import { button } from "../lib/atoms/button.js";
import { loadingRegion, skeletonBlock, skeletonLine } from "../lib/molecules/skeleton.js";

const STYLESHEET = "/styles/statistics.css";

/** @param {unknown} value */
function count(value) {
	return new Intl.NumberFormat().format(Number(value) || 0);
}

/** @param {unknown} value */
function dateLabel(value) {
	const date = new Date(String(value || ""));
	return Number.isNaN(date.getTime())
		? t("statistics.dateUnavailable", "Date unavailable")
		: new Intl.DateTimeFormat(undefined, { dateStyle: "long", timeStyle: "short" }).format(date);
}

/** @param {string} value */
function humanize(value) {
	return value
		.replaceAll(/([a-z])([A-Z])/g, "$1 $2")
		.replaceAll(/[_-]+/g, " ")
		.replace(/^./, (letter) => letter.toUpperCase());
}

/** @param {{ count?: number, missingCount?: number, percent?: number }} metric */
function coverageMetric(metric) {
	const percent = Math.max(0, Math.min(100, Number(metric?.percent) || 0));
	return `<div class="statistics-coverage">
		<div class="statistics-coverage__value"><strong>${esc(`${count(metric?.count)} / ${count((metric?.count || 0) + (metric?.missingCount || 0))}`)}</strong><span>${esc(`${percent}%`)}</span></div>
		<meter min="0" max="100" value="${esc(String(percent))}">${esc(`${percent}%`)}</meter>
	</div>`;
}

/** @param {string} title @param {string} description @param {{ count?: number, missingCount?: number, percent?: number }} metric */
function qualityRow(title, description, metric) {
	return `<div class="statistics-quality__row">
		<div><h3>${esc(title)}</h3><p>${esc(description)}</p></div>
		${coverageMetric(metric)}
	</div>`;
}

/** @param {string} title @param {string} intro @param {Array<{ key?: string, label?: string, count?: number }>} rows */
function histogram(title, intro, rows) {
	const values = Array.isArray(rows) ? rows : [];
	const maximum = Math.max(1, ...values.map((row) => Number(row.count) || 0));
	return `<figure class="statistics-histogram">
		<figcaption><h3>${esc(title)}</h3><p>${esc(intro)}</p></figcaption>
		<ol>${values
			.map(
				(row) => `<li>
					<div><span>${esc(row.label || humanize(row.key || ""))}</span><strong>${esc(count(row.count))}</strong></div>
					<meter min="0" max="${esc(String(maximum))}" value="${esc(String(Number(row.count) || 0))}">${esc(count(row.count))}</meter>
				</li>`
			)
			.join("")}</ol>
	</figure>`;
}

/** @param {Record<string, number> | undefined} values */
function breakdown(values) {
	const rows = Object.entries(values || {}).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
	return rows.length > 0
		? `<dl class="statistics-breakdown">${rows
				.map(([label, value]) => `<div><dt>${esc(humanize(label))}</dt><dd>${esc(count(value))}</dd></div>`)
				.join("")}</dl>`
		: `<p class="empty">${esc(t("statistics.noEvidence", "No evidence has been indexed yet."))}</p>`;
}

/** @param {any} data */
export function statisticsHTML(data) {
	const catalog = data?.catalog || {};
	const identities = data?.identities || {};
	const relationshipMetrics = data?.relationshipMetrics || {};
	const peopleMetrics = relationshipMetrics.people || {};
	const rowMetrics = relationshipMetrics.rows || {};
	const newVerification = relationshipMetrics.newlyVerifiedTools?.last24Hours || {};
	const evidenceFreshness = relationshipMetrics.evidenceFreshness || {};
	const sources = data?.sources || {};
	const distributions = data?.distributions || {};
	const definitions = data?.definitions || {};
	return `<div class="statistics-report">
		<header class="statistics-report__head">
			<div><p class="statistics-report__eyebrow">${esc(t("statistics.eyebrow", "Catalog quality ledger"))}</p>
			<h1>${esc(t("statistics.title", "Statistics"))}</h1>
			<p>${esc(t("statistics.intro", "A transparent view of catalog coverage, identity resolution, and data freshness."))}</p></div>
			<p class="statistics-report__as-of"><span>${esc(t("statistics.generated", "Snapshot generated"))}</span><time datetime="${esc(data?.generatedAt || "")}">${esc(dateLabel(data?.generatedAt))}</time></p>
		</header>

		<dl class="statistics-ledger" aria-label="${esc(t("statistics.catalogOverview", "Catalog overview"))}">
			<div><dt>${esc(t("statistics.totalTools", "Total tools"))}</dt><dd>${esc(count(catalog.totalTools))}</dd></div>
			<div><dt>${esc(t("statistics.verifiedAuthorCoverage", "Verified author coverage"))}</dt><dd>${esc(`${catalog.verifiedAuthors?.percent || 0}%`)}</dd></div>
			<div class="statistics-ledger__attention"><dt>${esc(t("statistics.needAuthorVerification", "Need author verification"))}</dt><dd>${esc(count(catalog.verifiedAuthors?.missingCount))}</dd></div>
			<div><dt>${esc(t("statistics.unresolvedAttributions", "Unresolved author tools"))}</dt><dd>${esc(count(catalog.unresolvedAuthorTools))}</dd></div>
		</dl>

		<section class="statistics-section" aria-labelledby="statistics-trust-title">
			<div class="statistics-section__head"><div><p>${esc(t("statistics.sectionOne", "01 · Relationships"))}</p><h2 id="statistics-trust-title">${esc(t("statistics.trustTitle", "Who is connected to each tool?"))}</h2></div>
			<p>${esc(t("statistics.trustIntro", "Listed names and verified relationships are counted separately so attribution is never presented as proof."))}</p></div>
			<div class="statistics-quality">
				${qualityRow(t("statistics.listedAuthors", "Listed authors"), definitions.listedAuthor || "Canonical records containing author metadata.", catalog.listedAuthors || {})}
				${qualityRow(t("statistics.verifiedAuthors", "Verified authors"), definitions.verifiedAuthor || "Current author relationships backed by stable evidence.", catalog.verifiedAuthors || {})}
				${qualityRow(t("statistics.verifiedMaintainers", "Verified maintainers"), definitions.verifiedMaintainer || "Current maintenance relationships backed by access evidence.", catalog.verifiedMaintainers || {})}
			</div>
			<dl class="statistics-ledger statistics-ledger--compact" aria-label="${esc(t("statistics.relationshipMetricOverview", "Relationship metric overview"))}">
				<div><dt>${esc(t("statistics.verifiedPeople", "People with a verified relationship"))}</dt><dd>${esc(count(peopleMetrics.withAnyVerifiedRelationship))}</dd></div>
				<div><dt>${esc(t("statistics.identityOnlyPeople", "Identity-only people"))}</dt><dd>${esc(count(peopleMetrics.identityOnly))}</dd></div>
				<div><dt>${esc(t("statistics.newlyVerifiedTools24h", "Newly verified tools · 24h"))}</dt><dd>${esc(count(newVerification.all))}</dd></div>
				<div class="statistics-ledger__attention"><dt>${esc(t("statistics.staleRelationships", "Stale relationships"))}</dt><dd>${esc(count(rowMetrics.stale))}</dd></div>
				<div><dt>${esc(t("statistics.relationshipRows", "Relationship rows"))}</dt><dd>${esc(count(rowMetrics.total))}</dd></div>
				<div><dt>${esc(t("statistics.evidenceExpiring", "Evidence expiring within 72h"))}</dt><dd>${esc(count(evidenceFreshness.expiringWithin72Hours))}</dd></div>
			</dl>
			<div class="statistics-columns">
				<div><h3>${esc(t("statistics.authorEvidence", "Author relationship evidence"))}</h3>${breakdown(data?.relationships?.authors)}</div>
				<div><h3>${esc(t("statistics.maintainerEvidence", "Maintainer relationship evidence"))}</h3>${breakdown(data?.relationships?.maintainers)}</div>
			</div>
		</section>

		<section class="statistics-section" aria-labelledby="statistics-metadata-title">
			<div class="statistics-section__head"><div><p>${esc(t("statistics.sectionTwo", "02 · Documentation"))}</p><h2 id="statistics-metadata-title">${esc(t("statistics.metadataTitle", "Is the catalog useful at a glance?"))}</h2></div>
			<p>${esc(t("statistics.metadataIntro", "Coverage is measured field by field. A core-complete record has a title, description, tool URL, and listed author."))}</p></div>
			<div class="statistics-metadata">
				<div class="statistics-metadata__lead"><span>${esc(t("statistics.coreComplete", "Core-complete tools"))}</span>${coverageMetric(catalog.coreMetadataComplete || {})}</div>
				${(data?.metadata || [])
					.map(
						(
							/** @type {{ key?: string, label?: string, count?: number, missingCount?: number, percent?: number }} */ metric
						) =>
							`<div><span>${esc(metric.label || humanize(metric.key || ""))}</span>${coverageMetric(metric)}</div>`
					)
					.join("")}
			</div>
		</section>

		<section class="statistics-section" aria-labelledby="statistics-time-title">
			<div class="statistics-section__head"><div><p>${esc(t("statistics.sectionThree", "03 · Time"))}</p><h2 id="statistics-time-title">${esc(t("statistics.timeTitle", "When did the catalog change?"))}</h2></div>
			<p>${esc(definitions.dateBasis || t("statistics.timeIntro", "Unavailable canonical dates remain visible instead of disappearing from the chart."))}</p></div>
			<div class="statistics-chart-grid">
				${histogram(t("statistics.createdByYear", "Catalog records created by year"), t("statistics.createdByYearIntro", "Based on Toolhub creation dates."), distributions.createdByYear)}
				${histogram(t("statistics.updateRecency", "Time since last update"), t("statistics.updateRecencyIntro", "How recently each canonical record was modified."), distributions.modifiedRecency)}
			</div>
			${histogram(t("statistics.modifiedByYear", "Catalog records last updated by year"), t("statistics.modifiedByYearIntro", "A historical distribution of each record's latest modification."), distributions.modifiedByYear)}
		</section>

		<section class="statistics-section" aria-labelledby="statistics-pipeline-title">
			<div class="statistics-section__head"><div><p>${esc(t("statistics.sectionFour", "04 · Resolution pipeline"))}</p><h2 id="statistics-pipeline-title">${esc(t("statistics.pipelineTitle", "How much evidence can be resolved?"))}</h2></div>
			<p>${esc(t("statistics.pipelineIntro", "Public identities require stable IDs or trusted handles. Display-only labels stay unresolved."))}</p></div>
			<dl class="statistics-ledger statistics-ledger--compact">
				<div><dt>${esc(t("statistics.publishablePeople", "Publishable people"))}</dt><dd>${esc(count(identities.publishablePeople))}</dd></div>
				<div><dt>${esc(t("statistics.stablePeople", "Stable-ID identities"))}</dt><dd>${esc(count(identities.stablePeople))}</dd></div>
				<div><dt>${esc(t("statistics.handlePeople", "Trusted-handle identities"))}</dt><dd>${esc(count(identities.handlePeople))}</dd></div>
				<div class="statistics-ledger__attention"><dt>${esc(t("statistics.unresolvedLabels", "Unresolved labels"))}</dt><dd>${esc(count(identities.unresolvedLabels))}</dd></div>
			</dl>
			<div class="statistics-columns statistics-columns--three">
				<div><h3>${esc(t("statistics.sourceOverview", "Toolinfo sources"))}</h3><p class="statistics-big-number">${esc(count(sources.total))}</p><p>${esc(t("statistics.validFeedCount", "$1 valid feeds · $2 indexed items", count(sources.validFeeds), count(sources.items)))}</p></div>
				<div><h3>${esc(t("statistics.controllerStatus", "Controller verification"))}</h3>${breakdown(sources.statuses)}</div>
				<div><h3>${esc(t("statistics.sourceClassification", "Source classification"))}</h3>${breakdown(sources.classifications)}</div>
			</div>
		</section>

		<section class="statistics-section" aria-labelledby="statistics-types-title">
			<div class="statistics-section__head"><div><p>${esc(t("statistics.sectionFive", "05 · Shape"))}</p><h2 id="statistics-types-title">${esc(t("statistics.typesTitle", "What kinds of tools are cataloged?"))}</h2></div></div>
			${histogram(t("statistics.toolTypes", "Tools by type"), t("statistics.toolTypesIntro", "Canonical Toolhub tool-type metadata, including unspecified records."), distributions.toolTypes)}
		</section>

		<details class="statistics-method">
			<summary>${esc(t("statistics.methodTitle", "How these statistics are calculated"))}</summary>
			<dl>${Object.entries(definitions)
				.map(([key, value]) => `<div><dt>${esc(humanize(key))}</dt><dd>${esc(value)}</dd></div>`)
				.join("")}</dl>
		</details>
	</div>`;
}

// The report opens with a ledger of four figures, then runs as a sequence of
// charted sections. Two stand-in sections are enough to show that shape without
// reserving a whole screen of space the answer may not need.
const SKELETON_LEDGER_CELLS = 4;
const SKELETON_SECTIONS = 2;

function sectionSkeleton() {
	return `<section class="statistics-section">
		<div class="statistics-section__head">
			<div>${skeletonLine("skeleton--w-xs")}${skeletonLine("skeleton-page__title skeleton--w-md")}</div>
			<p>${skeletonLine("skeleton-page__intro skeleton--w-xl")}</p>
		</div>
		${skeletonBlock("statistics-skeleton__chart")}
	</section>`;
}

const loadingHTML = () =>
	loadingRegion({
		label: t("statistics.loading", "Calculating catalog quality"),
		className: "statistics-loading",
		bodyClass: "statistics-report",
		body: `<header class="statistics-report__head">
			<div>
				${skeletonLine("skeleton--w-xs")}
				${skeletonLine("skeleton-page__title skeleton--w-md")}
				${skeletonLine("skeleton-page__intro skeleton--w-xl")}
			</div>
			<p>${skeletonLine("skeleton--w-lg")}</p>
		</header>
		<dl class="statistics-ledger">${`<div><dt>${skeletonLine("skeleton--w-lg")}</dt><dd>${skeletonLine("skeleton--w-sm")}</dd></div>`.repeat(SKELETON_LEDGER_CELLS)}</dl>
		${sectionSkeleton().repeat(SKELETON_SECTIONS)}`
	});

const errorHTML = () =>
	`<div class="statistics-error" role="alert"><h1>${esc(t("statistics.errorTitle", "Statistics are temporarily unavailable"))}</h1><p>${esc(t("statistics.errorBody", "The last quality snapshot could not be loaded."))}</p>${button(t("statistics.retry", "Try again"), { attrs: "data-statistics-retry" })}</div>`;

export function viewStatistics() {
	return {
		title: t("statistics.docTitle", "Statistics — Toolhub"),
		html: `<div class="container page statistics-page" data-statistics-root>${loadingHTML()}</div>`,
		mount: mountJsonReport({
			name: "statistics",
			endpoint: "/v1/statistics/",
			render: statisticsHTML,
			renderLoading: loadingHTML,
			renderError: errorHTML
		}),
		styles: [STYLESHEET]
	};
}
