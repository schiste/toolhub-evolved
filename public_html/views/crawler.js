// SPDX-License-Identifier: GPL-3.0-or-later
import { fmt, t, timeTag } from "../lib/core/i18n.js";
import { apiGet } from "../lib/core/api.js";
import { metaItem } from "../lib/atoms/labels.js";

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
			<p class="page__intro">${t("parity.crawlerIntroBefore", "Toolhub re-reads every registered")} <code>toolinfo.json</code> ${t("parity.crawlerIntroAfter", "URL roughly hourly and updates the catalog with any changes.")}</p>
			<div class="detail__meta">
				${metaItem(t("parity.lastCrawl", "Last crawl"), timeTag(last.start_date))}
				${metaItem(t("parity.urlsCrawled", "URLs crawled"), fmt(last.crawled_urls || 0))}
				${metaItem(t("parity.updatedInLastRun", "Updated in last run"), fmt(last.updated_tools || 0))}
			</div>
			<table class="runs">
				<caption class="skip-label">${t("parity.recentCrawlerRuns", "Recent crawler runs, newest first")}</caption>
				<thead><tr><th scope="col">${t("parity.run", "Run")}</th><th scope="col">${t("parity.urls", "URLs")}</th><th scope="col">${t("parity.new", "New")}</th><th scope="col">${t("parity.updated", "Updated")}</th><th scope="col">${t("parity.total", "Total")}</th></tr></thead>
				<tbody>${rows}</tbody>
			</table>
		</div>`
	};
}
