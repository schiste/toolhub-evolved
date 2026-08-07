// SPDX-License-Identifier: GPL-3.0-or-later
import { $, dirAttrs, esc } from "../lib/core/dom.js";
import { accountById, searchAccounts } from "../lib/core/accounts.js";
import { t, timeTag } from "../lib/core/i18n.js";
import { navigateTo, personHref } from "../lib/core/routing.js";
import { avatar } from "../lib/atoms/avatar.js";
import { icon } from "../lib/atoms/icon.js";
import { renderPager } from "../lib/molecules/pager.js";
import { communityHeader } from "./community.js";

const ACCOUNT_PAGE_SIZES = [12, 24, 48, 96];
const DEFAULT_ACCOUNT_PAGE_SIZE = 24;
const ACCOUNT_ORDERINGS = new Set(["name", "recent"]);

/** @param {string | null} value @param {number} fallback */
function positiveInteger(value, fallback) {
	const parsed = Number.parseInt(value || "", 10);
	return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

/** @param {URLSearchParams} [params] */
export function accountDirectoryState(params = new URLSearchParams(globalThis.location?.search || "")) {
	const requestedSize = positiveInteger(params.get("page_size"), DEFAULT_ACCOUNT_PAGE_SIZE);
	const ordering = String(params.get("ordering") || "name");
	return {
		q: String(params.get("q") || "")
			.trim()
			.slice(0, 255),
		page: positiveInteger(params.get("page"), 1),
		pageSize: ACCOUNT_PAGE_SIZES.includes(requestedSize) ? requestedSize : DEFAULT_ACCOUNT_PAGE_SIZE,
		group: String(params.get("group") || "")
			.trim()
			.slice(0, 255),
		ordering: ACCOUNT_ORDERINGS.has(ordering) ? ordering : "name",
		accountId: String(params.get("account") || "")
			.trim()
			.slice(0, 64)
	};
}

/** @param {ReturnType<typeof accountDirectoryState>} state @param {Partial<ReturnType<typeof accountDirectoryState>>} [changes] */
export function accountDirectoryHref(state, changes = {}) {
	const next = { ...state, ...changes };
	const params = new URLSearchParams();
	if (next.q) params.set("q", next.q);
	if (next.group) params.set("group", next.group);
	if (next.ordering !== "name") params.set("ordering", next.ordering);
	if (next.pageSize !== DEFAULT_ACCOUNT_PAGE_SIZE) params.set("page_size", String(next.pageSize));
	if (next.page > 1) params.set("page", String(next.page));
	if (next.accountId) params.set("account", next.accountId);
	return `/people${params.size > 0 ? `?${params}` : ""}`;
}

/** @param {string} value @param {string} current @param {string} label */
function option(value, current, label) {
	return `<option value="${esc(value)}"${value === current ? " selected" : ""}>${esc(label)}</option>`;
}

/** @param {any} sync */
function syncNotice(sync) {
	const status = String(sync?.status || "unavailable");
	if (status === "ready") return "";
	if (status === "stale") {
		const completed = sync?.lastCompletedAt
			? ` ${t("accounts.lastComplete", "Last complete refresh: {date}.", { date: timeTag(sync.lastCompletedAt) })}`
			: "";
		return `<div class="account-directory__notice account-directory__notice--warning" role="status"><strong>${t("accounts.staleTitle", "Showing a stale account cache.")}</strong><span>${t("accounts.staleBody", "The latest official refresh failed; previously completed records remain available.")}${completed}</span></div>`;
	}
	if (status === "refreshing") {
		return `<div class="account-directory__notice" role="status">${t("accounts.refreshing", "A new official account refresh is in progress. The last complete directory remains available.")}</div>`;
	}
	if (status === "building") {
		return `<div class="account-directory__notice" role="status">${t("accounts.building", "The first complete official account refresh is still in progress. Partial results are not published as a complete directory.")}</div>`;
	}
	return `<div class="account-directory__notice account-directory__notice--error" role="alert"><strong>${t("accounts.unavailableTitle", "The account directory is not available yet.")}</strong><span>${t("accounts.unavailableBody", "No complete official Toolhub account refresh has finished.")}</span></div>`;
}

/** @param {any} account @param {ReturnType<typeof accountDirectoryState>} state */
function accountCard(account, state) {
	const name = String(account?.username || t("accounts.unknown", "Unknown account"));
	const groups =
		Array.isArray(account?.groups) && account.groups.length > 0
			? account.groups.join(", ")
			: t("accounts.registered", "Registered account");
	const joined = timeTag(account?.dateJoined);
	return `<a class="account-card" href="${esc(accountDirectoryHref(state, { accountId: String(account?.id || "") }))}">
		${avatar(name, "account-card__avatar")}
		<span class="account-card__body"><strong class="account-card__name"${dirAttrs(name)}>${esc(name)}</strong><small>${esc(groups)}${joined ? ` · ${t("accounts.joined", "joined")} ${joined}` : ""}</small>${account?.personId ? `<small>${t("accounts.linkedPerson", "Linked to a public person through a stable identifier")}</small>` : ""}</span>
	</a>`;
}

/** @param {any} directory @param {ReturnType<typeof accountDirectoryState>} state */
function accountResults(directory, state) {
	if (!directory.sync?.complete && ["unavailable", "building"].includes(directory.sync?.status)) return "";
	const accounts = directory.accounts || [];
	if (accounts.length === 0) {
		return `<p class="empty">${state.q || state.group ? t("accounts.noMatches", "No official accounts match these filters.") : t("accounts.noAccounts", "No official accounts are present in the completed projection.")}</p>`;
	}
	const first = (directory.page - 1) * directory.pageSize + 1;
	const last = first + accounts.length - 1;
	return `<section aria-labelledby="account-results-title">
		<div class="section-head people-page__results-head"><div><h2 id="account-results-title" class="people-page__section-title">${t("accounts.officialAccounts", "Official Toolhub accounts")}</h2><p class="muted" aria-live="polite">${t("accounts.range", "Showing {first}–{last} of {count} accounts", { first, last, count: directory.count })}</p></div></div>
		<div class="account-grid">${accounts.map((/** @type {any} */ account) => accountCard(account, state)).join("")}</div>
		<nav class="pager" data-account-pager aria-label="${esc(t("accounts.pagination", "Account pagination"))}">${renderPager(directory.page, directory.pageCount)}</nav>
	</section>`;
}

/** @param {ReturnType<typeof accountDirectoryState>} state */
function accountForm(state) {
	const ordering = [
		["name", t("accounts.orderName", "Name (A–Z)")],
		["recent", t("accounts.orderRecent", "Newest registrations")]
	]
		.map(([value, label]) => option(value, state.ordering, label))
		.join("");
	const sizes = ACCOUNT_PAGE_SIZES.map((size) =>
		option(String(size), String(state.pageSize), t("accounts.perPage", "{size} per page", { size }))
	).join("");
	return `<form class="people-directory account-directory__form" data-account-search role="search">
		<div class="searchbar people-page__search"><input class="searchbar__input" name="q" type="search" value="${esc(state.q)}" placeholder="${esc(t("accounts.search", "Search official accounts"))}" aria-label="${esc(t("accounts.search", "Search official accounts"))}" /><button class="btn btn--primary" type="submit">${icon("search")} ${t("accounts.searchButton", "Search")}</button></div>
		<fieldset class="people-directory__filters account-directory__filters"><legend class="skip-label">${t("accounts.filters", "Account filters")}</legend>
			<label><span>${t("accounts.group", "Official group")}</span><input name="group" value="${esc(state.group)}" placeholder="user" /></label>
			<label><span>${t("accounts.ordering", "Sort by")}</span><select name="ordering" data-account-auto>${ordering}</select></label>
			<label><span>${t("accounts.resultsPerPage", "Results per page")}</span><select name="page_size" data-account-auto>${sizes}</select></label>
		</fieldset>
	</form>`;
}

function accountRequestError() {
	return `<div class="empty people-directory__error" role="alert"><p>${t("accounts.loadFailed", "The official account directory could not be loaded. This is not a zero-account result.")}</p><button class="btn btn--primary" type="button" data-account-retry>${t("accounts.retry", "Retry")}</button></div>`;
}

/** @param {any} account @param {ReturnType<typeof accountDirectoryState>} state */
function accountDetail(account, state) {
	const name = String(account?.username || t("accounts.unknown", "Unknown account"));
	const groups =
		Array.isArray(account?.groups) && account.groups.length > 0
			? account.groups.join(", ")
			: t("accounts.noGroups", "No special groups");
	const personLink = account?.personId
		? `<a href="${personHref(account.personId)}">${t("accounts.openPerson", "Open linked public person")}</a>`
		: account?.identityLinkStatus === "conflict"
			? `<span>${t("accounts.identityConflict", "Stable identifiers point to different people; no automatic link is shown.")}</span>`
			: `<span>${t("accounts.noPersonLink", "No public person is linked by a stable identifier.")}</span>`;
	return `<section class="account-detail" aria-labelledby="account-detail-title">
		<a class="back" href="${esc(accountDirectoryHref(state, { accountId: "" }))}">${t("accounts.backToDirectory", "← Back to community directory")}</a>
		<div class="account-detail__head">${avatar(name, "account-card__avatar")}<div><h2 id="account-detail-title"${dirAttrs(name)}>${esc(name)}</h2><p class="muted">${t("accounts.officialProfile", "Official Toolhub account projection")}</p></div></div>
		<dl class="account-detail__facts">
			<div><dt>${t("accounts.toolhubId", "Toolhub user ID")}</dt><dd>${esc(account?.id || "")}</dd></div>
			<div><dt>${t("accounts.registration", "Toolhub registration")}</dt><dd>${timeTag(account?.dateJoined) || t("accounts.notProvided", "Not provided")}</dd></div>
			<div><dt>${t("accounts.groups", "Official groups")}</dt><dd>${esc(groups)}</dd></div>
			<div><dt>${t("accounts.wikimediaId", "Wikimedia global user ID")}</dt><dd>${esc(account?.wikimediaGlobalUserId || t("accounts.notProvided", "Not provided"))}</dd></div>
			<div><dt>${t("accounts.wikimediaRegistration", "Wikimedia registration")}</dt><dd>${esc(account?.wikimediaRegisteredAt || t("accounts.notProvided", "Not provided"))}</dd></div>
			<div><dt>${t("accounts.publicPerson", "Public person")}</dt><dd>${personLink}</dd></div>
		</dl>
		${syncNotice(account?.sync)}
	</section>`;
}

/** @param {{canonicalize?: boolean}} [options] */
export async function viewAccounts(options = {}) {
	const state = accountDirectoryState();
	let detail = null;
	let detailError = false;
	let directory = null;
	let directoryError = false;
	if (state.accountId) {
		try {
			detail = await accountById(state.accountId);
		} catch {
			detailError = true;
		}
	} else {
		try {
			directory = await searchAccounts(state);
		} catch {
			directoryError = true;
		}
	}
	const body = state.accountId
		? detailError || !detail
			? accountRequestError()
			: accountDetail(detail, state)
		: `${accountForm(state)}<div data-account-results>${directoryError ? accountRequestError() : `${syncNotice(directory?.sync)}${accountResults(directory, state)}`}</div>`;
	return {
		title:
			state.accountId && detail?.username
				? t("accounts.detailDocTitle", "{name} — Accounts — Toolhub", { name: detail.username })
				: t("accounts.docTitle", "Accounts — Toolhub"),
		html: `<div class="container page people-page community-directory account-directory">${communityHeader()}${body}</div>`,
		mount() {
			if (options.canonicalize && location.pathname === "/members") {
				history.replaceState({}, "", accountDirectoryHref(state));
			}
			const form = /** @type {HTMLFormElement | null} */ ($("[data-account-search]"));
			const showLoading = () => {
				const target = $("[data-account-results]") || $("[data-account-search]")?.parentElement;
				if (target) target.setAttribute("aria-busy", "true");
			};
			const navigateFromForm = () => {
				if (!form) return;
				const data = new FormData(form);
				showLoading();
				navigateTo(
					accountDirectoryHref(state, {
						q: String(data.get("q") || "")
							.trim()
							.slice(0, 255),
						group: String(data.get("group") || "")
							.trim()
							.slice(0, 255),
						ordering: ACCOUNT_ORDERINGS.has(String(data.get("ordering") || ""))
							? String(data.get("ordering"))
							: "name",
						pageSize: ACCOUNT_PAGE_SIZES.includes(
							positiveInteger(String(data.get("page_size") || ""), DEFAULT_ACCOUNT_PAGE_SIZE)
						)
							? positiveInteger(String(data.get("page_size") || ""), DEFAULT_ACCOUNT_PAGE_SIZE)
							: DEFAULT_ACCOUNT_PAGE_SIZE,
						page: 1,
						accountId: ""
					})
				);
			};
			form?.addEventListener("submit", (event) => {
				event.preventDefault();
				navigateFromForm();
			});
			form?.querySelectorAll("[data-account-auto]").forEach((control) =>
				control.addEventListener("change", navigateFromForm)
			);
			$("[data-account-pager]")?.addEventListener("click", (event) => {
				const button = /** @type {HTMLElement | null} */ (event.target?.closest?.("[data-page]"));
				if (!button) return;
				navigateTo(
					accountDirectoryHref(state, {
						page: positiveInteger(button.getAttribute("data-page"), state.page),
						accountId: ""
					})
				);
			});
			$("[data-account-retry]")?.addEventListener("click", () =>
				window.dispatchEvent(new Event("toolhub:navigate"))
			);
		}
	};
}
