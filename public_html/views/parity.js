// SPDX-License-Identifier: GPL-3.0-or-later
import { avatar, dirAttrs, esc } from "../lib/dom.js";
import { countLabel, fmt, timeTag } from "../lib/i18n.js";
import { apiGet } from "../lib/api.js";
import { DEMO_KEYS, demoFeed } from "../lib/store.js";
import { metaItem } from "../lib/badges.js";
import { listHref, toolHref } from "../lib/nav.js";

/* ---- Parity pages: data-driven (read-only) ----------------------------- */
// Recent changes — live from /api/recent/ (deep-links tools via content_id slug).
export async function viewRecent() {
	const data = await apiGet("/recent/", { page_size: "30" }).catch(() => ({ results: [] }));
	// Lane B: your demo edits appear at the top of the live feed.
	const merged = demoFeed(DEMO_KEYS.revisions, data.results || []);
	const rows = merged.map((r) => {
		const title = esc(r.content_title || r.content_id || "—");
		const who = esc((r.user && r.user.username) || "system");
		const inner = `<span class="feed__ic" aria-hidden="true">✎</span>
			<span class="feed__main"><strong dir="auto">${title}</strong> <span class="feed__sub">${esc(r.content_type || "item")} · <span dir="auto">${who}</span></span></span>
			${timeTag(r.timestamp, "feed__when")}`;
		const link = r.content_type === "tool" && r.content_id
			? toolHref(r.content_id)
			: r.content_type === "list" && r.content_id ? listHref(r.content_id) : null;
		return link ? `<li><a href="${link}">${inner}</a></li>` : `<li><div class="feed__static">${inner}</div></li>`;
	}).join("");
	return { title: "Recent changes — Toolhub", html: `
		<div class="container page">
			<h1 class="page__title">Recent changes</h1>
			<p class="page__intro">The latest edits across the catalog.</p>
			<ul class="feed">${rows || '<li><div class="feed__static">No recent changes.</div></li>'}</ul>
		</div>` };
}
// Members — live from /api/users/.
export async function viewMembers() {
	const data = await apiGet("/users/", { page_size: "60" }).catch(() => ({ results: [], count: 0 }));
	const cards = (data.results || []).map((u) => {
		const meta = u.groups && u.groups.length ? esc(u.groups.join(", ")) : "Member";
		return `<div class="mcard">${avatar(u.username)}<div class="mcard__b">
			<div class="mcard__n"${dirAttrs(u.username)}>${esc(u.username)}</div>
			<div class="mcard__c">${meta} · joined ${timeTag(u.date_joined)}</div></div></div>`;
	}).join("");
	return { title: "Members — Toolhub", html: `
		<div class="container page">
			<h1 class="page__title">Members</h1>
			<p class="page__intro">${esc(countLabel(data.count || 0, "registered Wikimedian", "registered Wikimedians"))} contribute to the catalog.</p>
			<div class="mgrid">${cards}</div>
		</div>` };
}
// Crawler history — live from /api/crawler/runs/.
export async function viewCrawler() {
	const data = await apiGet("/crawler/runs/", { page_size: "12" }).catch(() => ({ results: [] }));
	const runs = data.results || [];
	const last = runs[0] || {};
	const rows = runs.map((r) => `
		<tr><td>${timeTag(r.start_date)}</td><td>${fmt(r.crawled_urls || 0)}</td>
		<td>${fmt(r.new_tools || 0)}</td><td>${fmt(r.updated_tools || 0)}</td><td>${fmt(r.total_tools || 0)}</td></tr>`).join("");
	return { title: "Crawler history — Toolhub", html: `
		<div class="container page">
			<h1 class="page__title">Crawler history</h1>
			<p class="page__intro">Toolhub re-reads every registered <code>toolinfo.json</code> URL roughly hourly and updates the catalog with any changes.</p>
			<div class="detail__meta">
				${metaItem("Last crawl", timeTag(last.start_date))}
				${metaItem("URLs crawled", fmt(last.crawled_urls || 0))}
				${metaItem("Updated in last run", fmt(last.updated_tools || 0))}
			</div>
			<table class="runs">
				<caption class="skip-label">Recent crawler runs, newest first</caption>
				<thead><tr><th scope="col">Run</th><th scope="col">URLs</th><th scope="col">New</th><th scope="col">Updated</th><th scope="col">Total</th></tr></thead>
				<tbody>${rows}</tbody>
			</table>
		</div>` };
}
// Audit logs — live from /api/auditlogs/.
export function targetHref(target) {
	if (!target || !target.id) return null;
	if (target.type === "tool") return toolHref(target.id);
	if (target.type === "list") return listHref(target.id);
	return null;
}
export async function viewAudit() {
	const data = await apiGet("/auditlogs/", { page_size: "25" }).catch(() => ({ results: [] }));
	const merged = demoFeed(DEMO_KEYS.auditlogs, data.results || []);
	const rows = merged.map((a) => {
		const who = esc((a.user && a.user.username) || "System");
		const tgt = a.target ? `${esc(a.target.type)} “${esc(a.target.label)}”` : "";
		const inner = `<span class="feed__ic" aria-hidden="true">📝</span>
			<span class="feed__main"><span dir="auto">${who}</span> <em>${esc(a.action || "changed")}</em> <span dir="auto">${tgt}</span></span>
			${timeTag(a.timestamp, "feed__when")}`;
		const href = targetHref(a.target);
		return href ? `<li><a href="${href}">${inner}</a></li>` : `<li><div class="feed__static">${inner}</div></li>`;
	}).join("");
	return { title: "Audit logs — Toolhub", html: `
		<div class="container page">
			<h1 class="page__title">Audit logs</h1>
			<p class="page__intro">A record of changes across the catalog, for patrollers and administrators.</p>
			<ul class="feed">${rows || '<li><div class="feed__static">No audit entries.</div></li>'}</ul>
		</div>` };
}
