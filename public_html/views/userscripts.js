// SPDX-License-Identifier: GPL-3.0-or-later
import { $, esc } from "../lib/core/dom.js";
import { fetchRead } from "../lib/core/api.js";
import { fmt, t, timeTag } from "../lib/core/i18n.js";
import { navigateTo } from "../lib/core/routing.js";
import { metaItem } from "../lib/atoms/labels.js";
import { renderPager } from "../lib/molecules/pager.js";

export const STYLESHEET = "/styles/userscripts.css";
const USER_SCRIPT_PAGE_SIZE = 25;
const TIERS = ["active", "archive"];

/** @param {string | null} value @param {number} max */
function trimmed(value, max) {
	return String(value || "")
		.trim()
		.slice(0, max);
}

/** @param {string | null} value @param {number} fallback */
function positiveInteger(value, fallback) {
	const parsed = Number.parseInt(value || "", 10);
	return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

/** @param {URLSearchParams} [params] */
export function userScriptState(params = new URLSearchParams(globalThis.location?.search || "")) {
	const tier = trimmed(params.get("tier"), 16) || "active";
	return {
		wiki: trimmed(params.get("wiki"), 128),
		tier: TIERS.includes(tier) ? tier : "active",
		owner: trimmed(params.get("owner"), 255),
		page: positiveInteger(params.get("page"), 1),
		script: trimmed(params.get("script"), 512)
	};
}

/** @param {ReturnType<typeof userScriptState>} state @param {Partial<ReturnType<typeof userScriptState>>} [changes] */
export function userScriptHref(state, changes = {}) {
	const next = { ...state, ...changes };
	const params = new URLSearchParams();
	if (next.wiki) params.set("wiki", next.wiki);
	if (next.tier !== "active") params.set("tier", next.tier);
	if (next.owner) params.set("owner", next.owner);
	if (next.page > 1) params.set("page", String(next.page));
	if (next.script) params.set("script", next.script);
	return `/userscripts${params.size > 0 ? `?${params}` : ""}`;
}

/**
 * Read a directory endpoint keeping the failure body.
 *
 * A folded page answers 404 with the entry it was filed under, which is the
 * most useful thing this view can say about it — so a reader that discards
 * non-2xx bodies would throw away the answer along with the status.
 * @param {string} path
 */
async function readJson(path) {
	const response = await fetchRead(path, { headers: { Accept: "application/json" } });
	const data = await response.json().catch(() => null);
	return { ok: response.ok, data };
}

/**
 * Which wiki the directory opens on when the reader has not named one.
 *
 * "The first wiki holding anything" was a fair answer while the census covered
 * three wikis, all of them large. Across every Wikimedia project the listing is
 * alphabetical and opens at aa.wikibooks.org, which holds one archived page and
 * nothing at all in the tier this page shows first -- so an unqualified visit
 * landed on an empty directory that read as a broken one.
 *
 * Pick the busiest wiki in the tier actually being shown. It is what an
 * unqualified visit is asking for, it stays right as the roster grows, and it
 * honours `?tier=archive` rather than choosing for one tier and rendering the
 * other. Ties keep the first listed, so the choice is stable between reads.
 * @param {Array<any>} wikis @param {string} tier
 */
function defaultWiki(wikis, tier) {
	/** @param {(entry: any) => number} score */
	const busiest = (score) =>
		wikis.reduce((chosen, entry) => (score(entry) > score(chosen || {}) ? entry : chosen), null);
	const inTier = busiest((entry) => Number(entry?.[tier] || 0));
	const anywhere = busiest((entry) => Number(entry?.active || 0) + Number(entry?.archive || 0));
	return String(inTier?.wiki || anywhere?.wiki || wikis[0]?.wiki || "");
}

/** @param {string} wiki @param {string} title */
function wikiPageHref(wiki, title) {
	return `https://${wiki}/wiki/${encodeURIComponent(title)}`;
}

/** @param {string} relation */
function relationLabel(relation) {
	return relation === "copy"
		? t("userscripts.relationCopy", "Identical copy")
		: t("userscripts.relationVariant", "Same name, different code");
}

/**
 * What the numbers on this page were computed from, and how current they are.
 *
 * Three dates rather than one, because "the job ran an hour ago" is not the
 * same claim as "this is what the wiki held an hour ago", and only the first is
 * cheap to know. A wiki swept in July and caught up to the first week of August
 * is a perfectly healthy hourly job over month-old data, and a reader shown one
 * timestamp would have no way to tell.
 * @param {any} coverage
 */
function coverageStrip(coverage) {
	if (!coverage) return "";
	// Two separate ways of being partial, and a wiki can be both at once: never
	// swept yet, and too large to enumerate in one pass. Say each one plainly.
	const notices = [];
	if (!Number(coverage.sweepsCompleted || 0)) {
		notices.push(
			t(
				"userscripts.neverSwept",
				"No full sweep of this wiki has finished yet, so these counts are a floor rather than a total."
			)
		);
	}
	if (coverage.enumerated === false) {
		notices.push(
			t(
				"userscripts.notEnumerated",
				"This wiki holds more user-space script pages than one search pass can list, so only part of its user space has been read."
			)
		);
	}
	const notice = notices.map((line) => `<p class="empty" role="status">${esc(line)}</p>`).join("");
	return `${notice}<div class="detail__meta">
		${metaItem(t("userscripts.pagesSeen", "Script pages seen"), fmt(Number(coverage.pages || 0)))}
		${metaItem(t("userscripts.sweptAt", "Last full sweep"), timeTag(coverage.sweptAt))}
		${metaItem(t("userscripts.currentTo", "Changes read up to"), timeTag(coverage.currentTo))}
		${metaItem(t("userscripts.computedAt", "Directory rebuilt"), timeTag(coverage.computedAt))}
	</div>`;
}

/** @param {ReturnType<typeof userScriptState>} state @param {any} coverage */
function tierTabs(state, coverage) {
	const counts = {
		active: Number(coverage?.active || 0),
		archive: Number(coverage?.archive || 0)
	};
	/** @type {Record<string, string>} */
	const labels = {
		active: t("userscripts.tierActive", "In use ($1)", fmt(counts.active)),
		archive: t("userscripts.tierArchive", "Archive ($1)", fmt(counts.archive))
	};
	return `<nav class="userscripts__tiers" aria-label="${esc(t("userscripts.tierNav", "Directory tiers"))}">${TIERS.map(
		(tier) =>
			`<a class="userscripts__tier${tier === state.tier ? " is-current" : ""}" href="${esc(userScriptHref(state, { tier, page: 1, script: "" }))}"${tier === state.tier ? ' aria-current="page"' : ""}>${esc(labels[tier])}</a>`
	).join("")}</nav>`;
}

/** @param {ReturnType<typeof userScriptState>} state @param {Array<any>} wikis */
function controls(state, wikis) {
	const options = wikis
		.map(
			(entry) =>
				`<option value="${esc(entry.wiki)}"${entry.wiki === state.wiki ? " selected" : ""}>${esc(entry.wiki)}</option>`
		)
		.join("");
	return `<form class="userscripts__controls" data-userscript-search>
		<label class="userscripts__field">
			<span class="userscripts__field-label">${esc(t("userscripts.wikiLabel", "Wiki"))}</span>
			<select name="wiki" data-userscript-auto>${options}</select>
		</label>
		<label class="userscripts__field">
			<span class="userscripts__field-label">${esc(t("userscripts.ownerLabel", "Owner"))}</span>
			<input type="search" name="owner" value="${esc(state.owner)}" placeholder="${esc(t("userscripts.ownerPlaceholder", "Any user"))}">
		</label>
		<button class="btn" type="submit">${esc(t("userscripts.apply", "Apply"))}</button>
	</form>`;
}

/** @param {any} entry @param {ReturnType<typeof userScriptState>} state */
function directoryRow(entry, state) {
	const detail = userScriptHref(state, { script: entry.title, page: 1 });
	const owner = userScriptHref(state, { owner: entry.owner, page: 1, script: "" });
	return `<tr>
		<td>${fmt(Number(entry.position || 0))}</td>
		<td><a href="${esc(detail)}" dir="auto">${esc(entry.basename || entry.title)}</a></td>
		<td><a href="${esc(owner)}" dir="auto">${esc(entry.owner)}</a></td>
		<td>${fmt(Number(entry.demand || 0))}</td>
		<td>${fmt(Number(entry.instances || 0))}</td>
	</tr>`;
}

/** @param {any} listing @param {ReturnType<typeof userScriptState>} state */
function directoryTable(listing, state) {
	const results = Array.isArray(listing?.results) ? listing.results : [];
	if (results.length === 0) {
		return `<p class="empty">${esc(
			state.owner
				? t("userscripts.noneForOwner", "No scripts in this tier belong to $1.", state.owner)
				: t("userscripts.noneInTier", "No scripts are filed in this tier yet.")
		)}</p>`;
	}
	const total = Number(listing?.total || results.length);
	const pages = Math.ceil(total / USER_SCRIPT_PAGE_SIZE);
	return `<p class="userscripts__count">${esc(t("userscripts.showing", "Showing $1 of $2 scripts.", fmt(results.length), fmt(total)))}</p>
	<table class="runs">
		<caption class="skip-label">${esc(t("userscripts.tableCaption", "User scripts, most demanded first"))}</caption>
		<thead><tr>
			<th scope="col">${esc(t("userscripts.rank", "Rank"))}</th>
			<th scope="col">${esc(t("userscripts.script", "Script"))}</th>
			<th scope="col">${esc(t("userscripts.owner", "Owner"))}</th>
			<th scope="col">${esc(t("userscripts.demand", "Users loading it"))}</th>
			<th scope="col">${esc(t("userscripts.instances", "Pages filed under it"))}</th>
		</tr></thead>
		<tbody>${results.map((/** @type {any} */ entry) => directoryRow(entry, state)).join("")}</tbody>
	</table>
	<div class="pager" data-userscript-pager>${renderPager(state.page, pages)}</div>`;
}

/** @param {any} script @param {ReturnType<typeof userScriptState>} state */
function memberTable(script, state) {
	const members = Array.isArray(script?.members) ? script.members : [];
	if (members.length === 0) {
		return `<p class="empty">${esc(t("userscripts.noMembers", "No other page was folded into this script."))}</p>`;
	}
	return `<table class="runs">
		<caption class="skip-label">${esc(t("userscripts.membersCaption", "Pages filed under this script"))}</caption>
		<thead><tr>
			<th scope="col">${esc(t("userscripts.memberPage", "Page"))}</th>
			<th scope="col">${esc(t("userscripts.memberRelation", "Why it was filed here"))}</th>
		</tr></thead>
		<tbody>${members
			.map(
				(/** @type {any} */ member) =>
					`<tr><td><a href="${esc(wikiPageHref(state.wiki, member.title))}" target="_blank" rel="noopener nofollow" dir="auto">${esc(member.title)}</a></td><td>${esc(relationLabel(member.relation))}</td></tr>`
			)
			.join("")}</tbody>
	</table>`;
}

/** @param {any} script @param {ReturnType<typeof userScriptState>} state */
function scriptDetail(script, state) {
	const back = userScriptHref(state, { script: "" });
	return `<section class="userscripts__detail">
		<p><a href="${esc(back)}">${esc(t("userscripts.backToDirectory", "← Back to the directory"))}</a></p>
		<h2 dir="auto">${esc(script.title)}</h2>
		<div class="detail__meta">
			${metaItem(t("userscripts.owner", "Owner"), `<a href="${esc(userScriptHref(state, { owner: script.owner, page: 1, script: "" }))}" dir="auto">${esc(script.owner)}</a>`)}
			${metaItem(t("userscripts.demand", "Users loading it"), fmt(Number(script.demand || 0)))}
			${metaItem(t("userscripts.instances", "Pages filed under it"), fmt(Number(script.instances || 0)))}
		</div>
		<p><a href="${esc(wikiPageHref(state.wiki, script.title))}" target="_blank" rel="noopener nofollow">${esc(t("userscripts.readOnWiki", "Read the source on the wiki"))}</a></p>
		${memberTable(script, state)}
	</section>`;
}

/** @param {any} body @param {ReturnType<typeof userScriptState>} state */
function scriptMiss(body, state) {
	const filedUnder = String(body?.filedUnder || "");
	if (!filedUnder) {
		return `<p class="empty" role="status">${esc(t("userscripts.unknownScript", "This wiki's directory has no such script."))}</p>`;
	}
	const href = userScriptHref(state, { script: filedUnder });
	return `<p class="empty" role="status">${esc(t("userscripts.foldedInto", "This page was filed under another script:"))} <a href="${esc(href)}" dir="auto">${esc(filedUnder)}</a></p>`;
}

function requestError() {
	return `<div class="userscripts__error" role="alert">
		<strong>${esc(t("userscripts.errorTitle", "The user-script directory could not be read."))}</strong>
		<span>${esc(t("userscripts.errorBody", "This is not an empty directory — the request failed."))}</span>
		<button class="btn" type="button" data-userscript-retry>${esc(t("userscripts.retry", "Try again"))}</button>
	</div>`;
}

export async function viewUserScripts() {
	const requested = userScriptState();
	/** @type {Array<any>} */
	let wikis = [];
	let failed = false;
	try {
		const listing = await readJson("/v1/userscripts/wikis/");
		wikis = Array.isArray(listing.data?.results) ? listing.data.results : [];
	} catch {
		failed = true;
	}
	const state = { ...requested, wiki: requested.wiki || defaultWiki(wikis, requested.tier) };
	/** @type {string} */
	let body;
	let coverage = wikis.find((entry) => entry.wiki === state.wiki) || null;
	if (failed) {
		body = requestError();
	} else if (!state.wiki) {
		body = `<p class="empty" role="status">${esc(t("userscripts.noWikis", "No wiki has been swept for user scripts yet."))}</p>`;
	} else if (state.script) {
		try {
			const response = await readJson(
				`/v1/userscripts/script/?wiki=${encodeURIComponent(state.wiki)}&title=${encodeURIComponent(state.script)}`
			);
			coverage = response.data?.coverage || coverage;
			body = response.ok ? scriptDetail(response.data, state) : scriptMiss(response.data, state);
		} catch {
			body = requestError();
		}
	} else {
		try {
			const offset = (state.page - 1) * USER_SCRIPT_PAGE_SIZE;
			const response = await readJson(
				`/v1/userscripts/directory/?wiki=${encodeURIComponent(state.wiki)}&tier=${encodeURIComponent(state.tier)}&owner=${encodeURIComponent(state.owner)}&limit=${USER_SCRIPT_PAGE_SIZE}&offset=${offset}`
			);
			coverage = response.data?.coverage || coverage;
			body = response.ok ? `${tierTabs(state, coverage)}${directoryTable(response.data, state)}` : requestError();
		} catch {
			body = requestError();
		}
	}
	return {
		styles: [STYLESHEET],
		title: t("userscripts.docTitle", "User scripts — Toolhub"),
		html: `<div class="container page userscripts-page">
			<h1 class="page__title">${esc(t("userscripts.heading", "User script directory"))}</h1>
			<p class="page__intro">${esc(t("userscripts.intro", "Every user-space script this wiki publishes, collapsed so each distinct script appears once, ranked by how many people load it."))}</p>
			${wikis.length > 0 ? controls(state, wikis) : ""}
			${coverageStrip(coverage)}
			<div data-userscript-results>${body}</div>
		</div>`,
		mount() {
			const form = /** @type {HTMLFormElement | null} */ ($("[data-userscript-search]"));
			const showLoading = () => $("[data-userscript-results]")?.setAttribute("aria-busy", "true");
			const submit = () => {
				if (!form) return;
				const data = new FormData(form);
				navigateTo(
					userScriptHref(state, {
						wiki: trimmed(String(data.get("wiki") || ""), 128),
						owner: trimmed(String(data.get("owner") || ""), 255),
						page: 1,
						script: ""
					}),
					{ beforeNavigate: showLoading }
				);
			};
			form?.addEventListener("submit", (event) => {
				event.preventDefault();
				submit();
			});
			form?.querySelectorAll("[data-userscript-auto]").forEach((control) =>
				control.addEventListener("change", submit)
			);
			$("[data-userscript-pager]")?.addEventListener("click", (event) => {
				const button = /** @type {HTMLElement | null} */ (event.target?.closest?.("[data-page]"));
				if (!button) return;
				navigateTo(
					userScriptHref(state, { page: positiveInteger(button.getAttribute("data-page"), state.page) }),
					{
						beforeNavigate: showLoading
					}
				);
			});
			$("[data-userscript-retry]")?.addEventListener("click", () =>
				window.dispatchEvent(new Event("toolhub:navigate"))
			);
		}
	};
}
