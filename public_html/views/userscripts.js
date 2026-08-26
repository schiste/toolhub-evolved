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
 * The roster read as one directory rather than as a thousand.
 *
 * An unqualified visit shows every wiki at once, and the coverage strip above it
 * then has to describe a thousand sweeps with one set of numbers. Only some of
 * those numbers survive being merged. Counts add up: pages seen, scripts filed.
 * Dates do not -- a mean of a thousand timestamps describes no wiki -- so both
 * are taken at their oldest and labelled as the floor they are. `sweptAt` is
 * dropped entirely: "the last wiki finished sweeping at" answers a question
 * nobody asked, and `currentTo` already carries the freshness claim that matters.
 *
 * The two partial-coverage notices become counts for the same reason. One wiki
 * saying "these counts are a floor" is a fact about what you are reading; a
 * thousand wikis saying it is a fact about how much of the roster is provisional.
 * @param {Array<any>} wikis
 */
function aggregateCoverage(wikis) {
	/** @param {string} key */
	const sum = (key) => wikis.reduce((total, entry) => total + Number(entry?.[key] || 0), 0);
	// ISO-8601 in UTC sorts lexicographically, so the first is the oldest. Wikis
	// that have no such date yet are never-swept ones, disclosed by their own count.
	const oldest = (/** @type {string} */ key) =>
		wikis
			.map((entry) => String(entry?.[key] || ""))
			.filter(Boolean)
			.sort()[0] || "";
	return {
		wiki: "",
		wikis: wikis.filter((entry) => Number(entry?.active || 0) + Number(entry?.archive || 0) > 0).length,
		roster: wikis.length,
		pages: sum("pages"),
		active: sum("active"),
		archive: sum("archive"),
		neverSwept: wikis.filter((entry) => !Number(entry?.sweepsCompleted || 0)).length,
		notEnumerated: wikis.filter((entry) => entry?.enumerated === false).length,
		currentTo: oldest("currentTo"),
		computedAt: oldest("computedAt")
	};
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

/**
 * The same disclosure as `coverageStrip`, for a reading that spans every wiki.
 * @param {any} summary
 */
function rosterStrip(summary) {
	if (!summary) return "";
	const notices = [];
	if (summary.neverSwept > 0) {
		notices.push(
			t(
				"userscripts.someNeverSwept",
				"$1 of these wikis have no finished sweep yet, so their scripts are a floor rather than a total.",
				fmt(summary.neverSwept)
			)
		);
	}
	if (summary.notEnumerated > 0) {
		notices.push(
			t(
				"userscripts.someNotEnumerated",
				"$1 hold more user-space script pages than one search pass can list, so only part of their user space has been read.",
				fmt(summary.notEnumerated)
			)
		);
	}
	const notice = notices.map((line) => `<p class="empty" role="status">${esc(line)}</p>`).join("");
	return `${notice}<div class="detail__meta">
		${metaItem(t("userscripts.pagesSeen", "Script pages seen"), fmt(Number(summary.pages || 0)))}
		${metaItem(t("userscripts.wikisCovered", "Wikis holding scripts"), esc(t("userscripts.wikisOf", "$1 of $2", fmt(Number(summary.wikis || 0)), fmt(Number(summary.roster || 0)))))}
		${metaItem(t("userscripts.oldestCurrentTo", "Every wiki current to at least"), timeTag(summary.currentTo))}
		${metaItem(t("userscripts.oldestComputedAt", "Oldest directory rebuild"), timeTag(summary.computedAt))}
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
	const options = [
		`<option value=""${state.wiki ? "" : " selected"}>${esc(t("userscripts.allWikis", "All wikis"))}</option>`,
		...wikis.map(
			(entry) =>
				`<option value="${esc(entry.wiki)}"${entry.wiki === state.wiki ? " selected" : ""}>${esc(entry.wiki)}</option>`
		)
	].join("");
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

/**
 * @param {any} entry @param {ReturnType<typeof userScriptState>} state @param {number} rank
 */
function directoryRow(entry, state, rank) {
	// The script link must name the wiki even when the reading does not, because
	// a script page is only ever a page on one wiki. The owner link deliberately
	// does not: asking for one person across every wiki is the more useful read,
	// and the wiki column is right there to narrow it.
	const detail = userScriptHref(state, { wiki: String(entry.wiki || state.wiki), script: entry.title, page: 1 });
	const owner = userScriptHref(state, { owner: entry.owner, page: 1, script: "" });
	const wikiCell = state.wiki
		? ""
		: `<td><a href="${esc(userScriptHref(state, { wiki: String(entry.wiki || ""), page: 1, script: "" }))}" dir="auto">${esc(entry.wiki)}</a></td>`;
	return `<tr>
		<td>${fmt(rank)}</td>
		${wikiCell}
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
	// `position` ranks a script inside its own wiki, so every wiki has a row at 1.
	// Across wikis the rank has to be counted off the page instead.
	const offset = (state.page - 1) * USER_SCRIPT_PAGE_SIZE;
	const caption = state.wiki
		? t("userscripts.tableCaption", "User scripts, most demanded first")
		: t("userscripts.tableCaptionAll", "User scripts across every wiki, most demanded first");
	return `<p class="userscripts__count">${esc(t("userscripts.showing", "Showing $1 of $2 scripts.", fmt(results.length), fmt(total)))}</p>
	<table class="runs">
		<caption class="skip-label">${esc(caption)}</caption>
		<thead><tr>
			<th scope="col">${esc(t("userscripts.rank", "Rank"))}</th>
			${state.wiki ? "" : `<th scope="col">${esc(t("userscripts.wikiLabel", "Wiki"))}</th>`}
			<th scope="col">${esc(t("userscripts.script", "Script"))}</th>
			<th scope="col">${esc(t("userscripts.owner", "Owner"))}</th>
			<th scope="col">${esc(t("userscripts.demand", "Users loading it"))}</th>
			<th scope="col">${esc(t("userscripts.instances", "Pages filed under it"))}</th>
		</tr></thead>
		<tbody>${results
			.map((/** @type {any} */ entry, /** @type {number} */ index) =>
				directoryRow(entry, state, state.wiki ? Number(entry.position || 0) : offset + index + 1)
			)
			.join("")}</tbody>
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
	// No wiki named means every wiki, not "pick one for me". The census covers
	// close to a thousand projects and no single one of them is the obvious place
	// to open; a reader who wants one narrows to it from the roster above.
	const state = { ...requested };
	/** @type {string} */
	let body;
	let coverage = state.wiki ? wikis.find((entry) => entry.wiki === state.wiki) || null : aggregateCoverage(wikis);
	if (failed) {
		body = requestError();
	} else if (wikis.length === 0) {
		body = `<p class="empty" role="status">${esc(t("userscripts.noWikis", "No wiki has been swept for user scripts yet."))}</p>`;
	} else if (state.script && state.wiki) {
		// A script page belongs to exactly one wiki, so `?script=` without a
		// `?wiki=` cannot be answered; every link this view writes carries both,
		// and a hand-edited URL that drops the wiki falls back to the directory.
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
			const wikiParam = state.wiki ? `wiki=${encodeURIComponent(state.wiki)}&` : "";
			const response = await readJson(
				`/v1/userscripts/directory/?${wikiParam}tier=${encodeURIComponent(state.tier)}&owner=${encodeURIComponent(state.owner)}&limit=${USER_SCRIPT_PAGE_SIZE}&offset=${offset}`
			);
			// A cross-wiki read discloses no coverage of its own -- there is no one
			// sweep to describe -- so the roster summary computed above stands.
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
			<p class="page__intro">${esc(
				state.wiki
					? t(
							"userscripts.intro",
							"Every user-space script this wiki publishes, collapsed so each distinct script appears once, ranked by how many people load it."
						)
					: t(
							"userscripts.introAll",
							"Every user-space script the census has read, across every wiki it covers, collapsed so each distinct script appears once and ranked by how many people load it."
						)
			)}</p>
			${wikis.length > 0 ? controls(state, wikis) : ""}
			${state.wiki ? coverageStrip(coverage) : rosterStrip(coverage)}
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
