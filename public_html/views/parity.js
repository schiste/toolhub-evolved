// SPDX-License-Identifier: GPL-3.0-or-later
import { $, $input, dirAttrs, esc } from "../lib/core/dom.js";
import { countLabel, fmt, t, timeTag } from "../lib/core/i18n.js";
import { apiGet } from "../lib/core/api.js";
import { listHref, navigateTo, toolHref } from "../lib/core/routing.js";
import { DEMO_KEYS, demoFeed } from "../lib/core/store.js";
import { avatar } from "../lib/atoms/avatar.js";
import { icon } from "../lib/atoms/icon.js";
import { metaItem } from "../lib/atoms/labels.js";

/* ---- Parity pages: data-driven (read-only) ----------------------------- */
const RECENT_FILTERS = [
	{ value: "all", label: t("parity.all", "All") },
	{ value: "tools", label: t("parity.tools", "Tools") },
	{ value: "lists", label: t("parity.lists", "Lists") },
	{ value: "other", label: t("parity.other", "Other") }
];
const RECENT_STATUS_FILTERS = [
	{ value: "all", label: t("parity.anyReviewState", "Any review state") },
	{ value: "unpatrolled", label: t("parity.needsReview", "Needs review") },
	{ value: "patrolled", label: t("parity.patrolled", "Patrolled") },
	{ value: "evolved", label: t("parity.evolvedLocal", "Evolved local") }
];
const RECENT_SORTS = [
	{ value: "newest", label: t("parity.sortNewest", "Newest first") },
	{ value: "oldest", label: t("parity.sortOldest", "Oldest first") },
	{ value: "type", label: t("parity.sortType", "Type") },
	{ value: "title", label: t("parity.sortTitle", "Title") },
	{ value: "actor", label: t("parity.sortActor", "Actor") }
];
/**
 * @param {{ content_type?: string }} r
 * @returns {string}
 */
function recentFilterKey(r) {
	if (r.content_type === "tool") return "tools";
	if (r.content_type === "list") return "lists";
	return "other";
}
/** @param {{ _evolved?: boolean, source?: string, syncStatus?: string, patrolled?: boolean, suppressed?: boolean }} r */
function recentReviewState(r) {
	if (r._evolved || r.source || r.syncStatus) return "evolved";
	if (r.suppressed) return "suppressed";
	if (r.patrolled === true) return "patrolled";
	if (r.patrolled === false) return "unpatrolled";
	return "unknown";
}
/** @param {string} type */
function recentTypeLabel(type) {
	if (type === "tool") return t("parity.typeTool", "Tool");
	if (type === "list") return t("parity.typeList", "List");
	return t("parity.typeOther", "Other");
}
/** @param {string} reviewState */
function recentReviewLabel(reviewState) {
	if (reviewState === "evolved") return t("parity.evolvedData", "Evolved data");
	if (reviewState === "suppressed") return t("parity.suppressed", "Suppressed");
	if (reviewState === "patrolled") return t("parity.patrolled", "Patrolled");
	if (reviewState === "unpatrolled") return t("parity.needsReview", "Needs review");
	return t("parity.reviewUnknown", "Review unknown");
}
/**
 * @param {{ parent_id?: unknown, _evolved?: boolean, comment?: string }} r
 * @returns {string}
 */
function recentActionLabel(r) {
	if (r._evolved || String(r.comment || "").startsWith("Evolved:")) {
		return t("parity.evolvedChange", "Evolved change");
	}
	return r.parent_id ? t("parity.updated", "Updated") : t("parity.created", "Created");
}
/**
 * @param {Array<any>} rows
 * @param {string} sort
 * @returns {Array<any>}
 */
function sortRecentRows(rows, sort) {
	const collator = new Intl.Collator(undefined, { sensitivity: "base", numeric: true });
	const text = (/** @type {any} */ r, /** @type {string} */ key) => String(r[key] || "").trim();
	const ts = (/** @type {any} */ r) => new Date(r.timestamp || 0).getTime() || 0;
	return [...rows].sort((a, b) => {
		if (sort === "oldest") return ts(a) - ts(b);
		if (sort === "type") return collator.compare(text(a, "content_type"), text(b, "content_type")) || ts(b) - ts(a);
		if (sort === "title") {
			return (
				collator.compare(
					text(a, "content_title") || text(a, "content_id"),
					text(b, "content_title") || text(b, "content_id")
				) || ts(b) - ts(a)
			);
		}
		if (sort === "actor") {
			return (
				collator.compare((a.user && a.user.username) || "", (b.user && b.user.username) || "") || ts(b) - ts(a)
			);
		}
		return ts(b) - ts(a);
	});
}
/**
 * @param {{ show: string, status: string, sort: string }} state
 * @param {{ show?: string, status?: string, sort?: string }} next
 */
function recentHref(state, next = {}) {
	const show = next.show || state.show;
	const status = next.status || state.status;
	const sort = next.sort || state.sort;
	const params = new URLSearchParams();
	if (show !== "all") params.set("show", show);
	if (status !== "all") params.set("status", status);
	if (sort !== "newest") params.set("sort", sort);
	const qs = params.toString();
	return `/recent${qs ? `?${qs}` : ""}`;
}
/** @param {string} value @param {{ value: string }[]} allowed @param {string} fallback */
function clampRecentOption(value, allowed, fallback) {
	return allowed.some((o) => o.value === value) ? value : fallback;
}
/** @param {Array<any>} rows @param {string} key */
function countRecentByType(rows, key) {
	return rows.filter((r) => recentFilterKey(r) === key).length;
}

// Recent changes — live from /api/recent/ (deep-links tools via content_id slug).
export async function viewRecent() {
	const params = new URLSearchParams(location.search);
	const requestedShow = params.get("show") || "all";
	const requestedStatus =
		params.get("status") || (["patrolled", "unpatrolled"].includes(requestedShow) ? requestedShow : "all");
	const show = clampRecentOption(requestedShow, RECENT_FILTERS, "all");
	const status = clampRecentOption(requestedStatus, RECENT_STATUS_FILTERS, "all");
	const sort = clampRecentOption(params.get("sort") || "newest", RECENT_SORTS, "newest");
	// Stryker disable next-line ObjectLiteral: the catch shape is unobservable — the only read is `data.results || []`, which coerces a missing `results` to the same [] as the {results:[]} fallback.
	const data = await apiGet("/recent/", { page_size: "30" }).catch(() => ({ results: [] }));
	// Local Evolved edits appear at the top of the live feed.
	const merged = demoFeed(DEMO_KEYS.revisions, data.results || []);
	const byType = show === "all" ? merged : merged.filter((r) => recentFilterKey(r) === show);
	const filtered = status === "all" ? byType : byType.filter((r) => recentReviewState(r) === status);
	const sorted = sortRecentRows(filtered, sort);
	const state = { show, status, sort };
	const filters = RECENT_FILTERS.map((o) => {
		const active = o.value === show;
		return `<a class="rc-filter__link${active ? " is-active" : ""}" href="${recentHref(state, { show: o.value })}"${active ? ' aria-current="page"' : ""}>${esc(o.label)}</a>`;
	}).join("");
	const statusOptions = RECENT_STATUS_FILTERS.map(
		(o) => `<option value="${esc(o.value)}"${o.value === status ? " selected" : ""}>${esc(o.label)}</option>`
	).join("");
	const sortOptions = RECENT_SORTS.map(
		(o) => `<option value="${esc(o.value)}"${o.value === sort ? " selected" : ""}>${esc(o.label)}</option>`
	).join("");
	const newest = sortRecentRows(merged, "newest")[0];
	const visibleLabel = countLabel(
		sorted.length,
		t("parity.visibleChangeOne", "visible change"),
		t("parity.visibleChangeOther", "visible changes")
	);
	const totalLabel = countLabel(
		merged.length,
		t("parity.loadedChangeOne", "loaded change"),
		t("parity.loadedChangeOther", "loaded changes")
	);
	const summary = [
		[t("parity.visible", "Visible"), esc(visibleLabel)],
		[t("parity.feedLoaded", "Feed loaded"), esc(totalLabel)],
		[t("parity.tools", "Tools"), fmt(countRecentByType(merged, "tools"))],
		[
			t("parity.needsReview", "Needs review"),
			fmt(merged.filter((r) => recentReviewState(r) === "unpatrolled").length)
		]
	]
		.map(
			([label, value]) =>
				`<div class="recent-stat"><div class="recent-stat__k">${label}</div><div class="recent-stat__v">${value}</div></div>`
		)
		.join("");
	const rows = sorted
		.map((r) => {
			const title = esc(r.content_title || r.content_id || "—");
			const who = esc((r.user && r.user.username) || t("parity.system", "system"));
			const type = String(r.content_type || t("parity.item", "item"));
			const reviewState = recentReviewState(r);
			const typeKey = recentFilterKey(r);
			const rowIcon = r.content_type === "tool" ? "tools" : r.content_type === "list" ? "list" : "edit";
			const comment = r.comment
				? `<span class="recent-row__comment"${dirAttrs(r.comment)}>${esc(r.comment)}</span>`
				: "";
			const contentId = r.content_id
				? `<span class="recent-row__id"${dirAttrs(r.content_id)}>${esc(r.content_id)}</span>`
				: "";
			const inner = `${icon(rowIcon, "feed__ic recent-row__ic")}
			<span class="feed__main recent-row__main">
				<span class="recent-row__top"><strong class="recent-row__title" dir="auto">${title}</strong><span class="recent-chip recent-chip--${esc(typeKey)}">${esc(recentTypeLabel(type))}</span><span class="recent-chip recent-chip--${esc(reviewState)}">${esc(recentReviewLabel(reviewState))}</span></span>
				<span class="feed__sub"><span dir="auto">${who}</span> · ${esc(recentActionLabel(r))}${contentId ? " · " : ""}${contentId}</span>
				${comment}
			</span>
			${timeTag(r.timestamp, "feed__when")}`;
			const link =
				r.content_type === "tool" && r.content_id
					? toolHref(r.content_id)
					: r.content_type === "list" && r.content_id
						? listHref(r.content_id)
						: null;
			return link
				? `<li><a href="${link}">${inner}</a></li>`
				: `<li><div class="feed__static">${inner}</div></li>`;
		})
		.join("");
	return {
		title: t("parity.recentChangesDocTitle", "Recent changes — Toolhub"),
		html: `
		<div class="container page recent-page">
			<header class="recent-head">
				<div>
					<h1 class="page__title">${t("parity.recentChanges", "Recent changes")}</h1>
					<p class="page__intro">${t("parity.recentIntroHybrid", "Live Toolhub activity, merged with Evolved-local write activity when a change is saved here.")}</p>
				</div>
				<div class="recent-head__fresh">
					<span>${t("parity.latestChange", "Latest change")}</span>
					<strong>${newest ? timeTag(newest.timestamp) : "—"}</strong>
				</div>
			</header>
			<div class="recent-summary" aria-label="${t("parity.recentSummary", "Recent changes summary")}">${summary}</div>
			<div class="recent-controls">
				<nav class="rc-filter" aria-label="${t("parity.filterRecentChanges", "Filter recent changes")}">${filters}</nav>
				<label class="sort recent-control"><span class="recent-control__label">${t("parity.reviewState", "Review state")}</span><select id="recent-status">${statusOptions}</select></label>
				<label class="sort recent-control"><span class="recent-control__label">${t("parity.sortBy", "Sort by")}</span><select id="recent-sort">${sortOptions}</select></label>
			</div>
			<ul class="feed feed--recent">${rows || `<li><div class="feed__static recent-empty">${t("parity.noRecentChanges", "No recent changes.")}</div></li>`}</ul>
		</div>`,
		mount() {
			/** @param {{ status?: string, sort?: string }} next */
			const navigate = (next) => {
				navigateTo(recentHref(state, next));
			};
			/** @type {HTMLInputElement} */ ($input("#recent-status")).addEventListener("change", () =>
				navigate({ status: /** @type {HTMLInputElement} */ ($input("#recent-status")).value })
			);
			/** @type {HTMLInputElement} */ ($input("#recent-sort")).addEventListener("change", () =>
				navigate({ sort: /** @type {HTMLInputElement} */ ($input("#recent-sort")).value })
			);
			const controls = $(".recent-controls");
			if (controls) controls.setAttribute("data-enhanced", "true");
		}
	};
}
// Members — live from /api/users/.
export async function viewMembers() {
	// Stryker disable next-line ObjectLiteral: the catch shape is unobservable — the only reads are `data.results || []` and `data.count || 0`, which coerce missing fields to the same [] / 0 as the explicit fallback object.
	const data = await apiGet("/users/", { page_size: "60" }).catch(() => ({ results: [], count: 0 }));
	const cards = (data.results || [])
		.map((/** @type {{ username: string, groups?: string[], date_joined?: string }} */ u) => {
			const meta = u.groups && u.groups.length > 0 ? esc(u.groups.join(", ")) : t("parity.member", "Member");
			return `<div class="mcard">${avatar(u.username)}<div class="mcard__b">
			<div class="mcard__n"${dirAttrs(u.username)}>${esc(u.username)}</div>
			<div class="mcard__c">${meta} · ${t("parity.joined", "joined")} ${timeTag(u.date_joined)}</div></div></div>`;
		})
		.join("");
	return {
		title: t("parity.membersDocTitle", "Members — Toolhub"),
		html: `
		<div class="container page">
			<h1 class="page__title">${t("parity.members", "Members")}</h1>
			<p class="page__intro">${t("parity.membersCount", "{count} contribute to the catalog.", { count: esc(countLabel(data.count || 0, t("parity.registeredWikimedianOne", "registered Wikimedian"), t("parity.registeredWikimedianOther", "registered Wikimedians"))) })}</p>
			<div class="mgrid">${cards}</div>
		</div>`
	};
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
// Audit logs — live from /api/auditlogs/.
/**
 * @param {{ id?: string, type?: string } | null | undefined} target
 * @returns {string | null}
 */
export function targetHref(target) {
	if (!target || !target.id) return null;
	if (target.type === "tool") return toolHref(target.id);
	if (target.type === "list") return listHref(target.id);
	return null;
}
export async function viewAudit() {
	// Stryker disable next-line ObjectLiteral: the catch shape is unobservable — the only read is `data.results || []`, which coerces a missing `results` to the same [] as the {results:[]} fallback.
	const data = await apiGet("/auditlogs/", { page_size: "25" }).catch(() => ({ results: [] }));
	const merged = demoFeed(DEMO_KEYS.auditlogs, data.results || []);
	const rows = merged
		.map((a) => {
			const who = esc((a.user && a.user.username) || t("parity.systemCap", "System"));
			const tgt = a.target
				? t("parity.auditTarget", "{type} “{label}”", { type: esc(a.target.type), label: esc(a.target.label) })
				: "";
			const inner = `${icon("edit", "feed__ic")}
			<span class="feed__main"><span dir="auto">${who}</span> <em>${esc(a.action || t("parity.changed", "changed"))}</em> <span dir="auto">${tgt}</span></span>
			${timeTag(a.timestamp, "feed__when")}`;
			const href = targetHref(a.target);
			return href
				? `<li><a href="${href}">${inner}</a></li>`
				: `<li><div class="feed__static">${inner}</div></li>`;
		})
		.join("");
	return {
		title: t("parity.auditLogsDocTitle", "Audit logs — Toolhub"),
		html: `
		<div class="container page">
			<h1 class="page__title">${t("parity.auditLogs", "Audit logs")}</h1>
			<p class="page__intro">${t("parity.auditIntro", "A record of changes across the catalog, for patrollers and administrators.")}</p>
			<ul class="feed">${rows || `<li><div class="feed__static">${t("parity.noAuditEntries", "No audit entries.")}</div></li>`}</ul>
		</div>`
	};
}
