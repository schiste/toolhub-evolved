// SPDX-License-Identifier: GPL-3.0-or-later
import { $, $$, $input, dirAttrs, esc } from "../lib/core/dom.js";
import { countLabel, fmt, t, timeTag } from "../lib/core/i18n.js";
import { apiGet } from "../lib/core/api.js";
import { listHref, navigateTo, toolHref } from "../lib/core/routing.js";
import { DEMO_KEYS, demoFeed, recentOwnerCacheGet, recentOwnerCacheSet } from "../lib/core/store.js";
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
	{ value: "unknown", label: t("parity.reviewUnknown", "Review unknown") },
	{ value: "unpatrolled", label: t("parity.needsReview", "Needs review") },
	{ value: "patrolled", label: t("parity.patrolled", "Patrolled") },
	{ value: "evolved", label: t("parity.evolvedLocal", "Evolved local") },
	{ value: "suppressed", label: t("parity.suppressed", "Suppressed") }
];
const RECENT_SORTS = [
	{ value: "updated", label: t("parity.sortUpdated", "Updated") },
	{ value: "title", label: t("parity.sortTitle", "Title") },
	{ value: "type", label: t("parity.sortType", "Type") },
	{ value: "owner", label: t("parity.toolOwner", "Tool owner") },
	{ value: "updated_by", label: t("parity.lastUpdatedBy", "Last updated by") },
	{ value: "action", label: t("parity.action", "Action") },
	{ value: "review", label: t("parity.reviewState", "Review state") }
];
const RECENT_DIRECTIONS = [
	{ value: "desc", label: t("parity.descending", "Descending") },
	{ value: "asc", label: t("parity.ascending", "Ascending") }
];
const RECENT_OWNER_FETCH_CONCURRENCY = 4;
const recentOwnerInflight = new Map();
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
/** @param {{ user?: { username?: string } }} r */
function recentUpdatedBy(r) {
	return (r.user && r.user.username) || t("parity.system", "system");
}
/** @param {{ content_title?: string, content_id?: string }} r */
function recentTitle(r) {
	return String(r.content_title || r.content_id || "—");
}
/** @param {any} raw */
function ownerFromToolRecord(raw) {
	const author = raw && raw.author;
	if (Array.isArray(author)) {
		const first = author.find((a) => (a && typeof a === "object" ? a.name : a));
		if (first && typeof first === "object" && first.name) return String(first.name);
		if (first) return String(first);
	}
	if (typeof author === "string" && author) return author;
	if (raw && raw.created_by && raw.created_by.username) return String(raw.created_by.username);
	return "";
}
/** @param {any} r */
function ownerFromRecentRow(r) {
	if (r._recentOwner) return String(r._recentOwner);
	if (r.maintainer) return String(r.maintainer);
	if (r.owner && typeof r.owner === "object" && r.owner.username) return String(r.owner.username);
	if (r.owner) return String(r.owner);
	if (r.created_by && r.created_by.username) return String(r.created_by.username);
	return "";
}
/** @param {any} r */
function recentToolName(r) {
	return r.content_type === "tool" && r.content_id ? String(r.content_id) : "";
}
/** @param {any[]} rows */
function applyCachedRecentOwners(rows) {
	return rows.map((r) => ({
		...r,
		_recentOwner:
			ownerFromRecentRow(r) || (recentToolName(r) ? recentOwnerCacheGet(recentToolName(r)) : undefined) || ""
	}));
}
/** @param {any[]} rows */
function missingOwnerNames(rows) {
	return [
		...new Set(
			rows
				.filter(
					(r) =>
						recentToolName(r) &&
						!ownerFromRecentRow(r) &&
						recentOwnerCacheGet(recentToolName(r)) === undefined
				)
				.map((r) => recentToolName(r))
		)
	];
}
/** @param {string} name */
function fetchRecentOwner(name) {
	const cached = recentOwnerCacheGet(name);
	if (cached !== undefined) return Promise.resolve(cached);
	if (recentOwnerInflight.has(name)) return recentOwnerInflight.get(name);
	const promise = apiGet(`/tools/${encodeURIComponent(name)}/`)
		.then((tool) => ownerFromToolRecord(tool))
		.catch(() => "")
		.then((owner) => {
			recentOwnerCacheSet(name, owner);
			return owner;
		})
		.finally(() => {
			recentOwnerInflight.delete(name);
		});
	recentOwnerInflight.set(name, promise);
	return promise;
}
/**
 * @param {string[]} names
 * @param {(name: string, owner: string) => void} onOwner
 */
async function enrichRecentOwnersProgressively(names, onOwner) {
	const queue = [...names];
	const workerCount = Math.min(RECENT_OWNER_FETCH_CONCURRENCY, queue.length);
	await Promise.all(
		Array.from({ length: workerCount }, async () => {
			while (queue.length > 0) {
				const name = queue.shift();
				if (!name) continue;
				onOwner(name, await fetchRecentOwner(name));
			}
		})
	);
}
/**
 * @param {Array<any>} rows
 * @param {string} sort
 * @param {string} dir
 * @returns {Array<any>}
 */
function sortRecentRows(rows, sort, dir) {
	const collator = new Intl.Collator(undefined, { sensitivity: "base", numeric: true });
	const text = (/** @type {any} */ r, /** @type {string} */ key) => String(r[key] || "").trim();
	const ts = (/** @type {any} */ r) => new Date(r.timestamp || 0).getTime() || 0;
	const direction = dir === "asc" ? 1 : -1;
	/** @param {any} r */
	const value = (r) => {
		if (sort === "updated") return ts(r);
		if (sort === "type") return recentTypeLabel(String(r.content_type || ""));
		if (sort === "owner") return ownerFromRecentRow(r);
		if (sort === "updated_by") return recentUpdatedBy(r);
		if (sort === "action") return recentActionLabel(r);
		if (sort === "review") return recentReviewLabel(recentReviewState(r));
		return text(r, "content_title") || text(r, "content_id");
	};
	return [...rows].sort((a, b) => {
		if (sort === "updated") {
			return direction * (ts(a) - ts(b)) || collator.compare(recentTitle(a), recentTitle(b));
		}
		return direction * collator.compare(String(value(a)), String(value(b))) || ts(b) - ts(a);
	});
}
/**
 * @param {{ show: string, status: string, sort: string, dir: string, q: string, owner: string, user: string }} state
 * @param {{ show?: string, status?: string, sort?: string, dir?: string, q?: string, owner?: string, user?: string }} next
 */
function recentHref(state, next = {}) {
	const show = Object.hasOwn(next, "show") ? next.show || "all" : state.show;
	const status = Object.hasOwn(next, "status") ? next.status || "all" : state.status;
	const sort = Object.hasOwn(next, "sort") ? next.sort || "updated" : state.sort;
	const dir = Object.hasOwn(next, "dir") ? next.dir || "desc" : state.dir;
	const q = Object.hasOwn(next, "q") ? next.q || "" : state.q;
	const owner = Object.hasOwn(next, "owner") ? next.owner || "" : state.owner;
	const user = Object.hasOwn(next, "user") ? next.user || "" : state.user;
	const params = new URLSearchParams();
	if (show !== "all") params.set("show", show);
	if (status !== "all") params.set("status", status);
	if (sort !== "updated") params.set("sort", sort);
	if (dir !== (sort === "updated" ? "desc" : "asc")) params.set("dir", dir);
	if (q) params.set("q", q);
	if (owner) params.set("owner", owner);
	if (user) params.set("user", user);
	const qs = params.toString();
	return `/recent${qs ? `?${qs}` : ""}`;
}
/** @param {string} value @param {{ value: string }[]} allowed @param {string} fallback */
function clampRecentOption(value, allowed, fallback) {
	return allowed.some((o) => o.value === value) ? value : fallback;
}
/** @param {URLSearchParams} params */
function recentState(params) {
	const requestedShow = params.get("show") || "all";
	const legacyStatus = ["patrolled", "unpatrolled"].includes(requestedShow) ? requestedShow : "";
	const requestedSort = params.get("sort") || "updated";
	const alias =
		requestedSort === "newest"
			? { sort: "updated", dir: "desc" }
			: requestedSort === "oldest"
				? { sort: "updated", dir: "asc" }
				: requestedSort === "actor"
					? { sort: "updated_by", dir: "asc" }
					: { sort: requestedSort, dir: params.get("dir") || "" };
	const sort = clampRecentOption(alias.sort, RECENT_SORTS, "updated");
	const defaultDir = sort === "updated" ? "desc" : "asc";
	return {
		show: clampRecentOption(requestedShow, RECENT_FILTERS, "all"),
		status: clampRecentOption(params.get("status") || legacyStatus || "all", RECENT_STATUS_FILTERS, "all"),
		sort,
		dir: clampRecentOption(alias.dir || defaultDir, RECENT_DIRECTIONS, defaultDir),
		q: (params.get("q") || "").trim(),
		owner: (params.get("owner") || "").trim(),
		user: (params.get("user") || "").trim()
	};
}
/** @param {{ value: string, label: string }[]} options @param {string} active */
function recentSelectOptions(options, active) {
	return options
		.map((o) => `<option value="${esc(o.value)}"${o.value === active ? " selected" : ""}>${esc(o.label)}</option>`)
		.join("");
}
/** @param {string} value @param {string} needle */
function recentIncludes(value, needle) {
	return value.toLocaleLowerCase().includes(needle.toLocaleLowerCase());
}
/** @param {any} r @param {{ q: string, owner: string, user: string }} state */
function recentTextFiltersMatch(r, state) {
	const owner = ownerFromRecentRow(r);
	const updatedBy = recentUpdatedBy(r);
	if (state.owner && !recentIncludes(owner, state.owner)) return false;
	if (state.user && !recentIncludes(updatedBy, state.user)) return false;
	if (!state.q) return true;
	return recentIncludes(
		[
			recentTitle(r),
			r.content_id || "",
			recentTypeLabel(String(r.content_type || "")),
			owner,
			updatedBy,
			recentActionLabel(r),
			recentReviewLabel(recentReviewState(r)),
			r.comment || ""
		].join(" "),
		state.q
	);
}
/**
 * @param {{ show: string, status: string, sort: string, dir: string, q: string, owner: string, user: string }} state
 * @param {string} sort
 * @param {string} label
 */
function recentSortHeader(state, sort, label) {
	const active = state.sort === sort;
	const firstDir = sort === "updated" ? "desc" : "asc";
	const nextDir = active ? (state.dir === "asc" ? "desc" : "asc") : firstDir;
	const aria = active ? ` aria-sort="${state.dir === "asc" ? "ascending" : "descending"}"` : "";
	const marker = active
		? `<span class="recent-table__sort recent-table__sort--${esc(state.dir)}" aria-hidden="true"></span>`
		: "";
	return `<th scope="col"${aria}><a href="${recentHref(state, { sort, dir: nextDir })}">${esc(label)}${marker}</a></th>`;
}
/** @param {string} value */
function recentDash(value) {
	return value ? `<span${dirAttrs(value)}>${esc(value)}</span>` : `<span class="recent-table__muted">—</span>`;
}
/** @param {string | undefined | null} comment */
function recentComment(comment) {
	return comment
		? `<button class="recent-comment" type="button" aria-expanded="false"><span class="recent-comment__text"${dirAttrs(comment)}>${esc(comment)}</span></button>`
		: `<span class="recent-table__muted">—</span>`;
}
/** @param {any[]} rows @param {{ show: string, status: string, sort: string, dir: string, q: string, owner: string, user: string }} state */
function visibleRecentRows(rows, state) {
	const byType = state.show === "all" ? rows : rows.filter((r) => recentFilterKey(r) === state.show);
	const byStatus = state.status === "all" ? byType : byType.filter((r) => recentReviewState(r) === state.status);
	return sortRecentRows(
		byStatus.filter((r) => recentTextFiltersMatch(r, state)),
		state.sort,
		state.dir
	);
}
/** @param {any} r */
function recentRowHTML(r) {
	const title = esc(recentTitle(r));
	const who = recentUpdatedBy(r);
	const type = String(r.content_type || t("parity.item", "item"));
	const reviewState = recentReviewState(r);
	const typeKey = recentFilterKey(r);
	const toolName = recentToolName(r);
	const contentId = r.content_id
		? `<span class="recent-table__id"${dirAttrs(r.content_id)}>${esc(r.content_id)}</span>`
		: "";
	const link =
		r.content_type === "tool" && r.content_id
			? toolHref(r.content_id)
			: r.content_type === "list" && r.content_id
				? listHref(r.content_id)
				: null;
	const item = link
		? `<a class="recent-table__item" href="${link}"><strong dir="auto">${title}</strong>${contentId}</a>`
		: `<span class="recent-table__item"><strong dir="auto">${title}</strong>${contentId}</span>`;
	const ownerCellAttr = toolName ? ` data-recent-owner-tool="${esc(toolName)}"` : "";
	return `<tr>
		<td data-label="${t("parity.itemTitle", "Item")}">${item}</td>
		<td data-label="${t("parity.type", "Type")}"><span class="recent-chip recent-chip--${esc(typeKey)}">${esc(recentTypeLabel(type))}</span></td>
		<td data-label="${t("parity.toolOwner", "Tool owner")}"${ownerCellAttr}>${recentDash(ownerFromRecentRow(r))}</td>
		<td data-label="${t("parity.lastUpdatedBy", "Last updated by")}"><span${dirAttrs(who)}>${esc(who)}</span></td>
		<td data-label="${t("parity.action", "Action")}">${esc(recentActionLabel(r))}</td>
		<td data-label="${t("parity.reviewState", "Review state")}"><span class="recent-chip recent-chip--${esc(reviewState)}">${esc(recentReviewLabel(reviewState))}</span></td>
		<td data-label="${t("parity.updatedAt", "Updated")}">${timeTag(r.timestamp)}</td>
		<td data-label="${t("parity.comment", "Comment")}" class="recent-table__comment">${recentComment(r.comment)}</td>
	</tr>`;
}
/** @param {any[]} rows @param {{ show: string, status: string, sort: string, dir: string, q: string, owner: string, user: string }} state */
function recentRowsHTML(rows, state) {
	return (
		visibleRecentRows(rows, state)
			.map((r) => recentRowHTML(r))
			.join("") ||
		`<tr><td class="recent-empty" colspan="8">${t("parity.noRecentChanges", "No recent changes.")}</td></tr>`
	);
}
/** @param {HTMLElement} root @param {string} toolName @param {string} owner */
function updateRecentOwnerCells(root, toolName, owner) {
	for (const cell of $$("[data-recent-owner-tool]", root)) {
		if (cell.getAttribute("data-recent-owner-tool") === toolName) cell.innerHTML = recentDash(owner);
	}
}
/** @param {{ sort: string, q: string, owner: string }} state */
function ownerSensitiveRecentState(state) {
	return Boolean(state.owner || state.q || state.sort === "owner");
}

// Recent changes — live from /api/recent/ (deep-links tools via content_id slug).
export async function viewRecent() {
	const state = recentState(new URLSearchParams(location.search));
	// Stryker disable next-line ObjectLiteral: the catch shape is unobservable — the only read is `data.results || []`, which coerces a missing `results` to the same [] as the {results:[]} fallback.
	const data = await apiGet("/recent/", { page_size: "30" }).catch(() => ({ results: [] }));
	// Local Evolved edits appear at the top of the live feed.
	const merged = applyCachedRecentOwners(demoFeed(DEMO_KEYS.revisions, data.results || []));
	const showOptions = recentSelectOptions(RECENT_FILTERS, state.show);
	const statusOptions = recentSelectOptions(RECENT_STATUS_FILTERS, state.status);
	const sortOptions = recentSelectOptions(RECENT_SORTS, state.sort);
	const dirOptions = recentSelectOptions(RECENT_DIRECTIONS, state.dir);
	const headers = [
		recentSortHeader(state, "title", t("parity.itemTitle", "Item")),
		recentSortHeader(state, "type", t("parity.type", "Type")),
		recentSortHeader(state, "owner", t("parity.toolOwner", "Tool owner")),
		recentSortHeader(state, "updated_by", t("parity.lastUpdatedBy", "Last updated by")),
		recentSortHeader(state, "action", t("parity.action", "Action")),
		recentSortHeader(state, "review", t("parity.reviewState", "Review state")),
		recentSortHeader(state, "updated", t("parity.updatedAt", "Updated")),
		`<th scope="col">${t("parity.comment", "Comment")}</th>`
	].join("");
	return {
		title: t("parity.recentChangesDocTitle", "Recent changes — Toolhub"),
		html: `
		<div class="container page recent-page">
			<header class="recent-head">
				<h1 class="page__title">${t("parity.recentChanges", "Recent changes")}</h1>
				<p class="page__intro">${t("parity.recentIntroHybrid", "Live Toolhub activity, merged with Evolved-local write activity when a change is saved here.")}</p>
			</header>
			<form class="recent-controls" id="recent-filter-form">
				<div class="recent-controls__filters">
					<label class="recent-control recent-control--wide"><span class="recent-control__label">${t("parity.searchRecent", "Search")}</span><input class="le__input" id="recent-q" type="search" value="${esc(state.q)}" placeholder="${t("parity.searchRecentPlaceholder", "Title, id, comment, owner...")}"></label>
					<label class="recent-control"><span class="recent-control__label">${t("parity.type", "Type")}</span><select id="recent-show">${showOptions}</select></label>
					<label class="recent-control"><span class="recent-control__label">${t("parity.reviewState", "Review state")}</span><select id="recent-status">${statusOptions}</select></label>
					<label class="recent-control"><span class="recent-control__label">${t("parity.toolOwner", "Tool owner")}</span><input class="le__input" id="recent-owner" type="search" value="${esc(state.owner)}"></label>
					<label class="recent-control"><span class="recent-control__label">${t("parity.lastUpdatedBy", "Last updated by")}</span><input class="le__input" id="recent-user" type="search" value="${esc(state.user)}"></label>
				</div>
				<div class="recent-controls__sortbar">
					<label class="recent-control recent-control--sort"><span class="recent-control__label">${t("parity.sortBy", "Sort by")}</span><select id="recent-sort">${sortOptions}</select></label>
					<label class="recent-control recent-control--dir"><span class="recent-control__label">${t("parity.direction", "Direction")}</span><select id="recent-dir">${dirOptions}</select></label>
					<div class="recent-actions">
						<button class="btn btn--primary" type="submit">${t("parity.applyFilters", "Apply")}</button>
						<a class="btn btn--subtle" href="/recent">${t("parity.clearFilters", "Clear")}</a>
					</div>
				</div>
			</form>
			<div class="recent-table-wrap">
				<table class="recent-table">
					<caption class="skip-label">${t("parity.recentChangesTable", "Recent changes table")}</caption>
					<colgroup>
						<col class="recent-table__col recent-table__col--item">
						<col class="recent-table__col recent-table__col--type">
						<col class="recent-table__col recent-table__col--owner">
						<col class="recent-table__col recent-table__col--updated-by">
						<col class="recent-table__col recent-table__col--action">
						<col class="recent-table__col recent-table__col--review">
						<col class="recent-table__col recent-table__col--updated">
						<col class="recent-table__col recent-table__col--comment">
					</colgroup>
					<thead><tr>${headers}</tr></thead>
					<tbody data-recent-body>${recentRowsHTML(merged, state)}</tbody>
				</table>
			</div>
		</div>`,
		mount() {
			/** @param {{ show?: string, status?: string, sort?: string, dir?: string, q?: string, owner?: string, user?: string }} next */
			const navigate = (next = {}) => {
				navigateTo(recentHref(state, next));
			};
			const readForm = () => ({
				show: /** @type {HTMLInputElement} */ ($input("#recent-show")).value,
				status: /** @type {HTMLInputElement} */ ($input("#recent-status")).value,
				sort: /** @type {HTMLInputElement} */ ($input("#recent-sort")).value,
				dir: /** @type {HTMLInputElement} */ ($input("#recent-dir")).value,
				q: /** @type {HTMLInputElement} */ ($input("#recent-q")).value.trim(),
				owner: /** @type {HTMLInputElement} */ ($input("#recent-owner")).value.trim(),
				user: /** @type {HTMLInputElement} */ ($input("#recent-user")).value.trim()
			});
			/** @type {HTMLFormElement | null} */ ($("#recent-filter-form"))?.addEventListener("submit", (event) => {
				event.preventDefault();
				navigate(readForm());
			});
			for (const selector of ["#recent-show", "#recent-status", "#recent-sort", "#recent-dir"]) {
				/** @type {HTMLInputElement} */ ($input(selector)).addEventListener("change", () =>
					navigate(readForm())
				);
			}
			const controls = $(".recent-controls");
			if (controls) controls.setAttribute("data-enhanced", "true");
			const table = $(".recent-table");
			const tbody = $("[data-recent-body]");
			const needsOwnerRerender = ownerSensitiveRecentState(state);
			const rerenderOwnerSensitiveRows = () => {
				if (tbody && tbody.isConnected) tbody.innerHTML = recentRowsHTML(merged, state);
			};
			const ownerNames = missingOwnerNames(merged);
			if (table && ownerNames.length > 0) {
				enrichRecentOwnersProgressively(ownerNames, (name, owner) => {
					for (const row of merged) {
						if (recentToolName(row) === name) row._recentOwner = owner;
					}
					if (!needsOwnerRerender) updateRecentOwnerCells(table, name, owner);
				}).then(() => {
					if (needsOwnerRerender) rerenderOwnerSensitiveRows();
				});
			}
			table?.addEventListener("click", (event) => {
				const toggle =
					event.target instanceof Element
						? /** @type {HTMLButtonElement | null} */ (event.target.closest(".recent-comment"))
						: null;
				if (!toggle) return;
				toggle.setAttribute(
					"aria-expanded",
					toggle.getAttribute("aria-expanded") === "true" ? "false" : "true"
				);
			});
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
