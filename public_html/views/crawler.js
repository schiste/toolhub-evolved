// SPDX-License-Identifier: GPL-3.0-or-later
import { fmt, t, tWithElements, timeTag } from "../lib/core/i18n.js";
import { apiGet } from "../lib/core/api.js";
import { esc } from "../lib/core/dom.js";
import { metaItem } from "../lib/atoms/labels.js";

const GRAPH_WIDTH = 820;
const GRAPH_HEIGHT = 260;
const GRAPH_PAD_X = 46;
const GRAPH_PAD_TOP = 24;
const GRAPH_PAD_BOTTOM = 46;
const GRAPH_PLOT_BOTTOM = GRAPH_HEIGHT - GRAPH_PAD_BOTTOM;

/** @param {unknown} value */
function crawlerMetric(value) {
	const number = Number(value || 0);
	return Number.isFinite(number) && number > 0 ? number : 0;
}
/**
 * @param {number} value
 * @param {number} max
 */
function crawlerGraphY(value, max) {
	const range = GRAPH_PLOT_BOTTOM - GRAPH_PAD_TOP;
	return GRAPH_PLOT_BOTTOM - (max ? (value / max) * range : 0);
}
/**
 * @param {number} index
 * @param {number} count
 */
function crawlerGraphX(index, count) {
	if (count <= 1) return GRAPH_PAD_X;
	return GRAPH_PAD_X + (index / (count - 1)) * (GRAPH_WIDTH - GRAPH_PAD_X * 2);
}
/** @param {string | undefined} value */
function crawlerDateLabel(value) {
	if (!value) return t("parity.unknownDate", "Unknown date");
	const date = new Date(value);
	if (Number.isNaN(date.getTime())) return value;
	return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(date);
}
/** @param {Array<{ start_date?: string, crawled_urls?: number, new_tools?: number, updated_tools?: number, total_tools?: number }>} runs */
function crawlerGraph(runs) {
	const points = runs
		.filter((run) => run && (run.start_date || run.total_tools || run.new_tools || run.updated_tools))
		.reverse();
	if (points.length === 0) {
		return `<section class="crawler-graph crawler-graph--empty" aria-label="${esc(t("parity.crawlerRunGraph", "Crawler run graph"))}"><p class="empty">${esc(t("parity.crawlerGraphEmpty", "No crawler run data to graph yet."))}</p></section>`;
	}
	const maxTotal = Math.max(1, ...points.map((run) => crawlerMetric(run.total_tools)));
	const maxDelta = Math.max(
		1,
		...points.map((run) => crawlerMetric(run.new_tools) + crawlerMetric(run.updated_tools))
	);
	const line = points
		.map(
			(run, index) =>
				`${crawlerGraphX(index, points.length).toFixed(1)},${crawlerGraphY(crawlerMetric(run.total_tools), maxTotal).toFixed(1)}`
		)
		.join(" ");
	const bars = points
		.map((run, index) => {
			const x = crawlerGraphX(index, points.length);
			const newTools = crawlerMetric(run.new_tools);
			const updatedTools = crawlerMetric(run.updated_tools);
			const totalDelta = newTools + updatedTools;
			const barHeight = totalDelta ? GRAPH_PLOT_BOTTOM - crawlerGraphY(totalDelta, maxDelta) : 1;
			const updatedHeight = totalDelta ? barHeight * (updatedTools / totalDelta) : 0;
			const newHeight = Math.max(0, barHeight - updatedHeight);
			const yUpdated = GRAPH_PLOT_BOTTOM - updatedHeight;
			const yNew = yUpdated - newHeight;
			const title = `${crawlerDateLabel(run.start_date)}: ${fmt(newTools)} ${t("parity.new", "New")}, ${fmt(updatedTools)} ${t("parity.updated", "Updated")}`;
			const updatedBar = updatedTools
				? `<rect class="crawler-graph__bar-updated" x="${(x - 5).toFixed(1)}" y="${yUpdated.toFixed(1)}" width="10" height="${Math.max(1, updatedHeight).toFixed(1)}"></rect>`
				: "";
			const newBar = newTools
				? `<rect class="crawler-graph__bar-new" x="${(x - 5).toFixed(1)}" y="${yNew.toFixed(1)}" width="10" height="${Math.max(1, newHeight).toFixed(1)}"></rect>`
				: "";
			return `<g class="crawler-graph__bar"><title>${esc(title)}</title>${updatedBar}${newBar}</g>`;
		})
		.join("");
	const markers = points
		.map((run, index) => {
			const x = crawlerGraphX(index, points.length);
			const y = crawlerGraphY(crawlerMetric(run.total_tools), maxTotal);
			const title = `${crawlerDateLabel(run.start_date)}: ${fmt(crawlerMetric(run.total_tools))} ${t("parity.total", "Total")}`;
			return `<circle class="crawler-graph__point" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3"><title>${esc(title)}</title></circle>`;
		})
		.join("");
	const first = points[0];
	const last = points[points.length - 1];
	return `<section class="crawler-graph" aria-labelledby="crawler-graph-title">
		<div class="crawler-graph__head">
			<h2 class="crawler-graph__title" id="crawler-graph-title">${esc(t("parity.runHistory", "Run history"))}</h2>
			<div class="crawler-graph__legend" aria-hidden="true">
				<span><i class="crawler-graph__key crawler-graph__key--total"></i>${esc(t("parity.total", "Total"))}</span>
				<span><i class="crawler-graph__key crawler-graph__key--updated"></i>${esc(t("parity.updated", "Updated"))}</span>
				<span><i class="crawler-graph__key crawler-graph__key--new"></i>${esc(t("parity.new", "New"))}</span>
			</div>
		</div>
		<svg class="crawler-graph__svg" viewBox="0 0 ${GRAPH_WIDTH} ${GRAPH_HEIGHT}" role="img" aria-label="${esc(t("parity.crawlerGraphLabel", "Crawler runs over time"))}">
			<line class="crawler-graph__axis" x1="${GRAPH_PAD_X}" y1="${GRAPH_PLOT_BOTTOM}" x2="${GRAPH_WIDTH - GRAPH_PAD_X}" y2="${GRAPH_PLOT_BOTTOM}"></line>
			<line class="crawler-graph__axis" x1="${GRAPH_PAD_X}" y1="${GRAPH_PAD_TOP}" x2="${GRAPH_PAD_X}" y2="${GRAPH_PLOT_BOTTOM}"></line>
			${bars}
			<polyline class="crawler-graph__line" points="${line}"></polyline>
			${markers}
			<text class="crawler-graph__label" x="${GRAPH_PAD_X}" y="${GRAPH_HEIGHT - 18}" text-anchor="start">${esc(crawlerDateLabel(first.start_date))}</text>
			<text class="crawler-graph__label" x="${GRAPH_WIDTH - GRAPH_PAD_X}" y="${GRAPH_HEIGHT - 18}" text-anchor="end">${esc(crawlerDateLabel(last.start_date))}</text>
			<text class="crawler-graph__label crawler-graph__label--total" x="${GRAPH_PAD_X + 4}" y="${GRAPH_PAD_TOP + 12}" text-anchor="start">${esc(fmt(maxTotal))}</text>
		</svg>
	</section>`;
}

// Crawler history — live from /api/crawler/runs/.
export async function viewCrawler() {
	// Stryker disable next-line ObjectLiteral: the catch shape is unobservable — the only read is `data.results || []`, which coerces a missing `results` to the same [] as the {results:[]} fallback.
	const data = await apiGet("/crawler/runs/", { page_size: "12" }).catch(() => ({ results: [] }));
	const runs = data.results || [];
	const last = runs[0] || {};
	const rows = runs
		.map(
			(
				/** @type {{ start_date?: string, crawled_urls?: number, new_tools?: number, updated_tools?: number, total_tools?: number }} */ r
			) => `
		<tr><td>${timeTag(r.start_date)}</td><td>${fmt(r.crawled_urls || 0)}</td>
		<td>${fmt(r.new_tools || 0)}</td><td>${fmt(r.updated_tools || 0)}</td><td>${fmt(r.total_tools || 0)}</td></tr>`
		)
		.join("");
	return {
		title: t("parity.crawlerHistoryDocTitle", "Crawler history — Toolhub"),
		html: `
		<div class="container page">
			<h1 class="page__title">${t("parity.crawlerHistory", "Crawler history")}</h1>
			<p class="page__intro">${tWithElements("parity.crawlerIntro", "Toolhub re-reads every registered {toolinfo} URL roughly hourly and updates the catalog with any changes.", { toolinfo: "<code>toolinfo.json</code>" })}</p>
			<div class="detail__meta">
				${metaItem(t("parity.lastCrawl", "Last crawl"), timeTag(last.start_date))}
				${metaItem(t("parity.urlsCrawled", "URLs crawled"), fmt(last.crawled_urls || 0))}
				${metaItem(t("parity.updatedInLastRun", "Updated in last run"), fmt(last.updated_tools || 0))}
			</div>
			${crawlerGraph(runs)}
			<table class="runs">
				<caption class="skip-label">${t("parity.recentCrawlerRuns", "Recent crawler runs, newest first")}</caption>
				<thead><tr><th scope="col">${t("parity.run", "Run")}</th><th scope="col">${t("parity.urls", "URLs")}</th><th scope="col">${t("parity.new", "New")}</th><th scope="col">${t("parity.updated", "Updated")}</th><th scope="col">${t("parity.total", "Total")}</th></tr></thead>
				<tbody>${rows}</tbody>
			</table>
		</div>`
	};
}
