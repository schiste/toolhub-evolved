// SPDX-License-Identifier: GPL-3.0-or-later
import { esc } from "../core/dom.js";
import { t } from "../core/i18n.js";

const CARD_COUNT_TOOL = 6;
const CARD_COUNT_LIST = 4;
const TABLE_ROWS = 6;
const RECENT_TABLE_COLUMNS = 8;
const ACCOUNT_TABLE_COLUMNS = 7;
const CRAWLER_TABLE_COLUMNS = 5;
const AUDIT_TABLE_COLUMNS = 4;

/** @param {number} count @param {(index: number) => string} render */
function repeat(count, render) {
	return Array.from({ length: count }, (_value, index) => render(index)).join("");
}

/** @param {...string} parts */
function classes(...parts) {
	return parts.filter(Boolean).join(" ");
}

/**
 * Decorative placeholder line. Keep visible loading text outside skeleton
 * bodies so assistive tech gets one concise status instead of fake content.
 * @param {string} [className]
 * @returns {string}
 */
export function skeletonLine(className = "") {
	return `<span class="${classes("skeleton", "skeleton--line", className)}"></span>`;
}

/**
 * @param {string} [className]
 * @returns {string}
 */
export function skeletonBlock(className = "") {
	return `<span class="${classes("skeleton", "skeleton--block", className)}"></span>`;
}

/**
 * @returns {string}
 */
export function toolCardSkeleton() {
	return `<article class="tcard skeleton-card skeleton-card--tool">
		<div class="tcard__head">
			${skeletonBlock("skeleton--avatar")}
			<div class="tcard__heading skeleton-card__heading">
				${skeletonLine("skeleton--w-lg")}
				${skeletonLine("skeleton--w-sm")}
			</div>
		</div>
		${skeletonLine("skeleton-card__desc skeleton--w-xl")}
		${skeletonLine("skeleton-card__desc skeleton--w-md")}
		<div class="tcard__tags skeleton-card__tags">
			${repeat(3, () => skeletonLine("skeleton--chip"))}
		</div>
		<div class="tcard__signals skeleton-card__signals">
			${repeat(2, () => skeletonLine("skeleton--badge"))}
		</div>
		<div class="tcard__foot">
			${skeletonLine("skeleton--w-md")}
			${skeletonBlock("skeleton--icon")}
		</div>
	</article>`;
}

/**
 * @returns {string}
 */
export function listCardSkeleton() {
	return `<div class="lcard skeleton-card skeleton-card--list">
		${skeletonBlock("skeleton--avatar")}
		<div class="lcard__body skeleton-card__heading">
			${skeletonLine("skeleton--w-lg")}
			${skeletonLine("skeleton--w-xl")}
			${skeletonLine("skeleton--w-md")}
		</div>
	</div>`;
}

/**
 * @param {"tool" | "list"} kind
 * @param {number} [count]
 * @returns {string}
 */
export function cardGridSkeleton(kind, count = kind === "list" ? CARD_COUNT_LIST : CARD_COUNT_TOOL) {
	const gridClass = kind === "list" ? "grid-lists" : "grid-tools";
	const renderCard = kind === "list" ? listCardSkeleton : toolCardSkeleton;
	return `<ul class="card-grid ${gridClass} skeleton-grid skeleton-grid--${kind}" role="list">
		${repeat(count, () => `<li>${renderCard()}</li>`)}
	</ul>`;
}

/**
 * @param {{ columns?: number; rows?: number; wrapClass?: string; tableClass?: string }} [options]
 * @returns {string}
 */
export function tableSkeleton(options = {}) {
	const columns = Math.max(1, options.columns || CRAWLER_TABLE_COLUMNS);
	const rows = Math.max(1, options.rows || TABLE_ROWS);
	const wrapClass = options.wrapClass || "skeleton-table-wrap";
	const tableClass = options.tableClass || "skeleton-table";
	const widthClasses = ["skeleton--w-md", "skeleton--w-xl", "skeleton--w-sm", "skeleton--w-lg", "skeleton--w-xs"];
	const cells = () =>
		repeat(
			columns,
			(index) =>
				`<td><span class="${classes("skeleton", "skeleton--line", widthClasses[index % widthClasses.length])}"></span></td>`
		);
	return `<div class="${classes(wrapClass, "skeleton-table-wrap")}">
		<table class="${classes(tableClass, "skeleton-table")}">
			<tbody>${repeat(rows, () => `<tr>${cells()}</tr>`)}</tbody>
		</table>
	</div>`;
}

function pageHeadSkeleton() {
	return `<div class="skeleton-page__head">
		${skeletonLine("skeleton-page__title skeleton--w-lg")}
		${skeletonLine("skeleton-page__intro skeleton--w-xl")}
	</div>`;
}

function searchSkeleton() {
	return `${pageHeadSkeleton()}
	<div class="browse skeleton-browse">
		<aside class="facets skeleton-facets">
			${skeletonBlock("skeleton-facets__search")}
			${repeat(
				3,
				() => `<div class="facet-group skeleton-facet-group">
					${skeletonLine("skeleton-facet-group__title skeleton--w-sm")}
					${repeat(4, () => skeletonLine("skeleton-facet-group__row skeleton--w-lg"))}
				</div>`
			)}
		</aside>
		<div class="browse__main">
			<div class="browse__bar">
				${skeletonLine("skeleton--w-lg")}
				<span class="browse__controls skeleton-browse__controls">
					${skeletonBlock("skeleton--control")}
					${skeletonBlock("skeleton--control")}
				</span>
			</div>
			${cardGridSkeleton("tool")}
		</div>
	</div>`;
}

function listOverviewSkeleton() {
	return `<div class="section-head skeleton-section-head">
		${skeletonLine("skeleton-page__title skeleton--w-md")}
		${skeletonBlock("skeleton--button")}
	</div>
	${skeletonLine("skeleton-page__intro skeleton--w-xl")}
	${cardGridSkeleton("list")}`;
}

function listDetailSkeleton() {
	return `${pageHeadSkeleton()}
	${cardGridSkeleton("tool", 4)}`;
}

function styleguideSkeleton() {
	return `${pageHeadSkeleton()}
	<div class="skeleton-styleguide">
		<div class="sg-token-grid skeleton-grid" aria-hidden="true">
			${repeat(12, () => `<div class="sg-token skeleton-card">${skeletonBlock("skeleton--avatar")}${skeletonLine("skeleton--w-md")}</div>`)}
		</div>
		<div class="sg-examples skeleton-styleguide__examples">
			${repeat(9, () => `<div class="sg-example skeleton-card">${skeletonLine("skeleton--w-lg")}${skeletonLine("skeleton--w-md")}${skeletonBlock("skeleton--control")}</div>`)}
		</div>
	</div>`;
}

function toolDetailSkeleton() {
	return `<div class="toolpage__head skeleton-toolpage__head">
		${skeletonBlock("skeleton--avatar skeleton--avatar-lg")}
		<div class="toolpage__id skeleton-toolpage__id">
			${skeletonLine("skeleton-page__title skeleton--w-lg")}
			${skeletonLine("skeleton--w-md")}
			${skeletonLine("skeleton-page__intro skeleton--w-xl")}
			<div class="toolpage__glance skeleton-toolpage__glance">
				${repeat(3, () => skeletonLine("skeleton--badge"))}
			</div>
		</div>
		<div class="toolpage__cta skeleton-toolpage__cta">
			${repeat(3, () => skeletonBlock("skeleton--button"))}
		</div>
	</div>
	<div class="toolpage__grid">
		<div class="skeleton-toolpage__main">
			${skeletonLine("skeleton-toolpage__heading skeleton--w-sm")}
			${skeletonLine("skeleton-toolpage__paragraph skeleton--w-xl")}
			${skeletonLine("skeleton-toolpage__paragraph skeleton--w-lg")}
			${skeletonLine("skeleton-toolpage__heading skeleton--w-md")}
			<div class="toolpage__tags skeleton-card__tags">
				${repeat(4, () => skeletonLine("skeleton--chip"))}
			</div>
			${cardGridSkeleton("tool", 3)}
		</div>
		<aside class="skeleton-toolpage__side">
			${skeletonLine("skeleton-toolpage__heading skeleton--w-sm")}
			${repeat(5, () => skeletonLine("skeleton-toolpage__meta skeleton--w-lg"))}
		</aside>
	</div>`;
}

/**
 * @param {string | undefined} path
 * @returns {{ modifier: string; label: string; body: string } | null}
 */
function routeSkeleton(path = "") {
	const seg = path.split("/").filter(Boolean);
	if (seg[0] === "search") {
		return {
			modifier: "search",
			label: t("router.loadingSearchResults", "Loading search results"),
			body: searchSkeleton()
		};
	}
	if (seg[0] === "tools" && seg[1] && !seg[2]) {
		return {
			modifier: "tool",
			label: t("router.loadingToolPage", "Loading tool page"),
			body: toolDetailSkeleton()
		};
	}
	if (seg[0] === "by" && seg[1]) {
		return {
			modifier: "cards",
			label: t("router.loadingToolCards", "Loading tool cards"),
			body: listDetailSkeleton()
		};
	}
	if (seg[0] === "lists" && seg[1] && !seg[2]) {
		return {
			modifier: "cards",
			label: t("router.loadingListTools", "Loading list tools"),
			body: listDetailSkeleton()
		};
	}
	if (["lists", "published-lists", "my-lists", "favorites"].includes(seg[0])) {
		return {
			modifier: "lists",
			label: t("router.loadingLists", "Loading lists"),
			body: listOverviewSkeleton()
		};
	}
	if (["my-tools", "preferences"].includes(seg[0])) {
		const label =
			seg[0] === "preferences"
				? t("router.loadingPreferences", "Loading preferences")
				: t("router.loadingMyTools", "Loading your tools");
		return {
			modifier: "table",
			label,
			body: `${pageHeadSkeleton()}${tableSkeleton({
				columns: ACCOUNT_TABLE_COLUMNS,
				wrapClass: "account-records__table-wrap",
				tableClass: "account-records__table"
			})}`
		};
	}
	if (seg[0] === "recent") {
		return {
			modifier: "table",
			label: t("router.loadingRecentChanges", "Loading recent changes"),
			body: `${pageHeadSkeleton()}${tableSkeleton({
				columns: RECENT_TABLE_COLUMNS,
				wrapClass: "recent-table-wrap",
				tableClass: "recent-table"
			})}`
		};
	}
	if (seg[0] === "crawler-history") {
		return {
			modifier: "table",
			label: t("router.loadingCrawlerHistory", "Loading crawler history"),
			body: `${pageHeadSkeleton()}${tableSkeleton({
				columns: CRAWLER_TABLE_COLUMNS,
				wrapClass: "skeleton-runs-wrap",
				tableClass: "runs"
			})}`
		};
	}
	if (seg[0] === "audit-logs") {
		return {
			modifier: "table",
			label: t("router.loadingAuditLogs", "Loading audit logs"),
			body: `${pageHeadSkeleton()}${tableSkeleton({ columns: AUDIT_TABLE_COLUMNS })}`
		};
	}
	if (seg[0] === "styleguide") {
		return {
			modifier: "styleguide",
			label: t("router.loadingStyleguide", "Loading design system"),
			body: styleguideSkeleton()
		};
	}
	return null;
}

/**
 * @param {string | undefined} path
 * @returns {string}
 */
export function routeSkeletonHTML(path) {
	const skeleton = routeSkeleton(path);
	if (!skeleton) return "";
	return `<div class="container page route-loading route-loading--skeleton route-loading--${esc(skeleton.modifier)}" role="status" aria-live="polite" aria-atomic="true">
		<span class="route-loading__label">${esc(skeleton.label)}</span>
		<div class="route-loading__body" aria-hidden="true">
			${skeleton.body}
		</div>
	</div>`;
}
