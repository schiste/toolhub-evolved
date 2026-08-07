// SPDX-License-Identifier: GPL-3.0-or-later
import { $, dirAttrs, esc, safeUrl } from "../lib/core/dom.js";
import { authorProfileUrl, toolsByAuthor } from "../lib/core/author-index.js";
import { fmt, t } from "../lib/core/i18n.js";
import { identityQualityLabel, relationshipLabel } from "../lib/core/claims.js";
import {
	personById,
	resolvePersonHandle,
	searchPeopleDirectory,
	searchUnresolvedAttributions,
	toolsForPerson
} from "../lib/core/people.js";
import { navigateTo, personHref } from "../lib/core/routing.js";
import { attachEvolvedSummaries, EVOLVED_SUMMARY_GRACE_MS } from "../lib/core/signals.js";
import { icon } from "../lib/atoms/icon.js";
import { avatar } from "../lib/atoms/avatar.js";
import { grid } from "../lib/organisms/grid.js";
import { toolCard } from "../lib/organisms/tool-card.js";
import { relationshipTrustMarkup } from "../lib/molecules/relationship-trust.js";
import { renderPager } from "../lib/molecules/pager.js";

const PEOPLE_PAGE_SIZES = [12, 24, 48];
const DEFAULT_PEOPLE_PAGE_SIZE = 24;
const PEOPLE_ROLES = new Set(["author", "maintainer", "record_owner", "catalog_actor"]);
const PEOPLE_VERIFICATIONS = new Set(["verified", "unverified", "renewal_needed"]);
const PEOPLE_ACTIVITIES = new Set(["active", "quiet", "unknown"]);
const PEOPLE_ORDERINGS = new Set(["relevance", "relationship", "recent", "name"]);

/** @param {any} person */
function profileLinks(person) {
	const links = [];
	const website = safeUrl(person?.profile?.websiteUrl);
	if (website) links.push(website);
	for (const link of person?.profile?.links || []) {
		const url = safeUrl(link);
		if (url && !links.includes(url)) links.push(url);
	}
	const wiki = person?.identifiers?.find(
		(/** @type {any} */ identifier) => identifier.namespace === "wiki_username"
	)?.value;
	const wikiUrl = wiki ? authorProfileUrl({ wikiUsername: wiki }) : null;
	if (wikiUrl && !links.includes(wikiUrl)) links.push(wikiUrl);
	return links
		.map((url) => {
			let label = t("authors.authorProfile", "Author profile");
			try {
				label = new URL(url).hostname.replace(/^www\./, "");
			} catch {
				// safeUrl has already accepted the URL; retain the localized fallback label.
			}
			return `<a class="author-page__profile" href="${esc(url)}" target="_blank" rel="noopener nofollow">${esc(label)} ${icon("external")}</a>`;
		})
		.join("");
}

/** @param {Tool} tool */
function relationshipsForTool(tool) {
	const relationships = Array.isArray(/** @type {any} */ (tool).personRelationships)
		? /** @type {any[]} */ (/** @type {any} */ (tool).personRelationships)
		: [];
	if (relationships.length > 0) return relationships;
	return [
		{
			type: "author",
			status: "unverified",
			confidence: 0,
			evidenceCount: 1,
			toolhubCanonical: true,
			evidence: [{ source: "toolhub_author_metadata", method: "toolhub_author_metadata", status: "unverified" }]
		}
	];
}

/**
 * Render one tool once while preserving every relationship carried by that tool.
 * @param {Tool[]} tools
 * @param {{count?: number, page?: number, pageSize?: number, pageCount?: number}} toolPage
 */
function relatedTools(tools, toolPage) {
	const count = Number(toolPage?.count) || tools.length;
	const page = Number(toolPage?.page) || 1;
	const pageSize = Number(toolPage?.pageSize) || Math.max(1, tools.length);
	const first = tools.length > 0 ? (page - 1) * pageSize + 1 : 0;
	const last = first + tools.length - 1;
	const range =
		tools.length > 0
			? t("authors.showingRelatedTools", "Showing $1–$2 of $3", first, last, count)
			: t("authors.noToolsOnPage", "No related tools on this page.");
	return `<section class="author-page__tools" aria-labelledby="author-related-tools">
		<div class="section-head"><div><h2 id="author-related-tools">${t("authors.relatedTools", "Related tools")}</h2><p class="muted" aria-live="polite">${esc(range)}</p></div><span class="muted">${count}</span></div>
		${
			tools.length > 0
				? grid(
						"grid-tools author-page__tool-grid",
						tools,
						(/** @type {Tool} */ tool) =>
							`<div class="author-tool-card">${toolCard(tool)}${/** @type {any} */ (tool).profileSummaryStatus === "missing" ? `<p class="author-tool-card__summary-note">${t("authors.toolMetadataUnavailable", "Tool metadata is unavailable; relationships are shown from local evidence.")}</p>` : ""}<div class="author-tool-card__relationships" aria-label="${esc(t("authors.relationshipsForTool", "Relationships for $1", tool.title || tool.name))}">${relationshipsForTool(
								tool
							)
								.map((relationship) => relationshipTrustMarkup(relationship))
								.join("")}</div></div>`
					)
				: `<p class="empty">${t("authors.noToolsOnPage", "No related tools on this page.")}</p>`
		}
		<nav class="pager" data-person-tools-pager aria-label="${esc(t("authors.relatedToolsPagination", "Related tools pagination"))}">${renderPager(page, Number(toolPage?.pageCount) || 1)}</nav>
	</section>`;
}

/** @param {any} activity @param {number} toolCount */
function activityStats(activity, toolCount) {
	const stats = [
		[t("authors.relatedToolsStat", "Related tools"), activity?.relatedToolCount ?? toolCount],
		[t("authors.verifiedToolsStat", "Tools with a verified relationship"), activity?.verifiedToolCount ?? 0],
		[t("authors.contributionsStat", "Public contributions"), activity?.contributionCount ?? 0],
		[t("authors.recentContributionsStat", "Recent contributions"), activity?.recentContributionCount ?? 0]
	];
	return `<dl class="author-page__stats">${stats
		.map(([label, value]) => `<div><dt>${esc(label)}</dt><dd>${Number(value) || 0}</dd></div>`)
		.join("")}</dl>`;
}

/** @param {any} person @param {Tool[]} tools */
function renderPerson(person, tools) {
	const name = person?.displayName || t("authors.unknownPerson", "Unknown person");
	const profile = person?.profile || {};
	const externalLinks = profileLinks(person);
	const toolPage = Array.isArray(person?.tools)
		? { count: tools.length, page: 1, pageSize: Math.max(1, tools.length), pageCount: 1 }
		: person?.tools || { count: person?.toolCount ?? tools.length, page: 1, pageSize: 24, pageCount: 1 };
	const toolCount = Number(person?.toolCount ?? toolPage.count ?? tools.length) || 0;
	const body =
		toolCount > 0
			? relatedTools(tools, toolPage)
			: `<p class="empty">${t("authors.noToolsFound", "No tools found for this person.")}</p>`;
	const bio = profile.bio ? `<div class="prose author-page__bio">${esc(profile.bio)}</div>` : "";
	const meta = [
		profile.location,
		person?.activity?.status && person.activity.status !== "unknown" ? person.activity.status : "",
		person?.identityQuality ? identityQualityLabel(person.identityQuality) : ""
	]
		.filter(Boolean)
		.join(" · ");
	const avatarUrl = safeUrl(profile.avatarUrl);
	const profileAvatar = avatarUrl
		? `<img class="author-page__avatar" src="${esc(avatarUrl)}" alt="" width="96" height="96" />`
		: avatar(name, "avatar--lg author-page__avatar");
	return {
		title: t("authors.docTitle", "$1 — Toolhub", name),
		html: `<div class="container page author-page">
			<a class="back" href="/search">${t("authors.backToTools", "← Back to tools")}</a>
			<div class="section-head author-page__head">
				<div class="author-page__identity">
					${profileAvatar}
					<div>
					<h1 class="page__title"${dirAttrs(name)}>${esc(name)}</h1>
					<p class="page__intro">${esc(t("authors.toolCount", "$1 {{PLURAL:$2|tool|tools}}", fmt(toolCount), toolCount))}</p>
					${meta ? `<p class="muted">${esc(meta)}</p>` : ""}
					</div>
				</div>
				${externalLinks ? `<div class="author-page__links">${externalLinks}</div>` : ""}
			</div>
			${bio}
			${activityStats(person?.activity, toolCount)}
			${body}
		</div>`,
		mount() {
			$("[data-person-tools-pager]")?.addEventListener("click", (event) => {
				const button = /** @type {HTMLElement | null} */ (event.target?.closest?.("[data-page]"));
				if (!button || !person?.id) return;
				const page = positiveInteger(button.getAttribute("data-page"), 1);
				navigateTo(`${personHref(person.id)}${page > 1 ? `?page=${page}` : ""}`);
			});
		}
	};
}

/** @param {any} person */
async function resolvedView(person) {
	const tools = await toolsForPerson(person);
	await attachEvolvedSummaries(tools, { graceMs: EVOLVED_SUMMARY_GRACE_MS });
	return renderPerson(person, tools);
}

function profileToolPage() {
	return positiveInteger(new URLSearchParams(globalThis.location?.search || "").get("page"), 1);
}

/** @param {any} identifier */
function identifierLabel(identifier) {
	const labels = /** @type {Record<string, string>} */ ({
		toolhub_user_id: t("authors.toolhubId", "Toolhub ID"),
		toolhub_username: t("authors.toolhubUsername", "Toolhub"),
		toolforge_username: t("authors.toolforgeUsername", "Toolforge"),
		wikimedia_global_user_id: t("authors.wikimediaId", "Wikimedia ID"),
		wiki_username: t("authors.wikiUsername", "Wiki")
	});
	return `${labels[identifier?.namespace] || identifier?.namespace || t("authors.identifier", "Identifier")}: ${identifier?.value || ""}`;
}

/** @param {any} person */
function disambiguationCard(person) {
	const name = person?.displayName || t("authors.unknownPerson", "Unknown person");
	const identifiers = (Array.isArray(person?.identifiers) ? person.identifiers : [])
		.filter((/** @type {any} */ identifier) => identifier?.value)
		.map((/** @type {any} */ identifier) => identifierLabel(identifier));
	const detail = identifiers.join(" · ") || t("authors.verifiedIdentity", "Verified identity");
	return `<a class="people-card" href="${personHref(person.id)}">
		${avatar(name, "people-card__avatar")}<span><strong${dirAttrs(name)}>${esc(name)}</strong><small>${esc(detail)}</small></span>
	</a>`;
}

/** @param {string} name @param {any} resolution */
function renderDisambiguation(name, resolution) {
	const candidates = Array.isArray(resolution?.candidates) ? resolution.candidates : [];
	const unresolved = Array.isArray(resolution?.unresolvedAttributions) ? resolution.unresolvedAttributions : [];
	const choices =
		candidates.length > 0
			? `<section aria-labelledby="author-candidates-title"><h2 id="author-candidates-title" class="people-page__section-title">${t("authors.possiblePeople", "Possible people")}</h2><div class="people-grid">${candidates.map((/** @type {any} */ person) => disambiguationCard(person)).join("")}</div></section>`
			: "";
	const attributions =
		unresolved.length > 0
			? `<section class="people-attributions" aria-labelledby="author-attributions-title"><div class="section-head"><div><h2 id="author-attributions-title">${t("authors.unresolvedAttributions", "Attributions awaiting identity evidence")}</h2><p class="muted people-attributions__intro">${t("authors.disambiguationUnresolved", "These tool attributions use this label but do not contain enough stable evidence to select a person.")}</p></div></div><ul class="people-attributions__list">${unresolved.map((/** @type {any} */ attribution) => unresolvedAttribution(attribution)).join("")}</ul></section>`
			: "";
	return {
		title: t("authors.disambiguationDocTitle", "$1 — Choose a person", name),
		html: `<div class="container page people-page author-disambiguation">
			<a class="back" href="/people">${t("authors.backToPeople", "← Back to people")}</a>
			<header><h1 class="page__title"${dirAttrs(name)}>${esc(name)}</h1><p class="page__intro">${t("authors.disambiguationIntro", "This name does not identify one unique person. Choose a verified identity below.")}</p></header>
			${choices}${attributions}
		</div>`
	};
}

/** Legacy name route; the name is resolved through current identifiers first. @param {string} name */
export async function viewAuthor(name) {
	const resolution = await resolvePersonHandle(name).catch(() => null);
	if (resolution?.status === "resolved" && resolution?.person?.id) {
		const person = await personById(resolution.person.id, { toolPage: profileToolPage() });
		return resolvedView(person);
	}
	if (resolution?.status === "ambiguous") return renderDisambiguation(name, resolution);
	// Toolhub remains canonical and is the final fallback while a newly changed
	// catalog record is waiting for the local people projection to refresh.
	const entry = await toolsByAuthor(name);
	await attachEvolvedSummaries(entry.tools || [], { graceMs: EVOLVED_SUMMARY_GRACE_MS });
	return renderPerson(
		{
			displayName: entry.name || name,
			identifiers: [],
			profile: { websiteUrl: authorProfileUrl(entry.profile) },
			activity: { status: "unknown" }
		},
		entry.tools || []
	);
}

/** Immutable public-id route. @param {string} publicId */
export async function viewPerson(publicId) {
	const person = await personById(publicId, { toolPage: profileToolPage() });
	return resolvedView(person);
}

/** @param {any} person */
function personCard(person) {
	const name = person?.displayName || t("authors.unknownPerson", "Unknown person");
	const avatarUrl = safeUrl(person?.profile?.avatarUrl);
	const picture = avatarUrl
		? `<img class="people-card__avatar" src="${esc(avatarUrl)}" alt="" width="56" height="56" loading="lazy" />`
		: avatar(name, "people-card__avatar");
	const count = Number(person?.activity?.relatedToolCount) || 0;
	const summary = person?.relationshipSummary || {};
	const verifiedTypes = Array.isArray(summary.verifiedTypes) ? summary.verifiedTypes : [];
	const types = Array.isArray(summary.types) ? summary.types : [];
	const relationshipDetail =
		verifiedTypes.length > 0
			? t(
					"authors.verifiedRelationshipRoles",
					"Verified: $1",
					verifiedTypes.map((role) => relationshipLabel(role)).join(", ")
				)
			: types.length > 0
				? t(
						"authors.relationshipRoles",
						"Relationships: $1",
						types.map((role) => relationshipLabel(role)).join(", ")
					)
				: t("authors.noRelationshipSummary", "No relationship summary");
	const identityDetail = identityQualityLabel(person?.identityQuality || "");
	return `<a class="people-card" href="${personHref(person.id)}" data-person-name="${esc(name.toLocaleLowerCase())}">
		${picture}<span><strong${dirAttrs(name)}>${esc(name)}</strong><small>${esc(t("authors.toolCount", "$1 {{PLURAL:$2|tool|tools}}", fmt(count), count))} · ${esc(identityDetail)}</small><small>${esc(relationshipDetail)}</small></span>
	</a>`;
}

/** @param {any[]} people */
function peopleResults(people) {
	return people.length > 0
		? `<div class="people-grid">${people.map((/** @type {any} */ person) => personCard(person)).join("")}</div>`
		: `<p class="empty">${t("authors.noPeopleFound", "No people found.")}</p>`;
}

/** @param {any} attribution */
function unresolvedAttribution(attribution) {
	const label = attribution?.label || t("authors.unknownAttribution", "Unknown attribution");
	const tools = Number(attribution?.toolCount) || 0;
	const observations = Number(attribution?.evidenceCount) || Number(attribution?.attributionCount) || 0;
	return `<li class="people-attribution">
		<span class="people-attribution__mark" aria-hidden="true">?</span>
		<span class="people-attribution__content"><strong${dirAttrs(label)}>${esc(label)}</strong><small>${esc(t("authors.toolCount", "$1 {{PLURAL:$2|tool|tools}}", fmt(tools), tools))} · ${esc(t("authors.observationCount", "$1 {{PLURAL:$2|observation|observations}}", fmt(observations), observations))}</small></span>
		<span class="people-attribution__status">${t("authors.identityUnresolved", "Identity unresolved")}</span>
	</li>`;
}

/** @param {string | null} value @param {Set<string>} allowed @param {string} fallback */
function choice(value, allowed, fallback = "") {
	return value && allowed.has(value) ? value : fallback;
}

/** @param {string | null} value @param {number} fallback */
function positiveInteger(value, fallback) {
	const parsed = Number.parseInt(value || "", 10);
	return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

/** @param {URLSearchParams} [params] */
export function peopleDirectoryState(params = new URLSearchParams(globalThis.location?.search || "")) {
	const requestedSize = positiveInteger(params.get("page_size"), DEFAULT_PEOPLE_PAGE_SIZE);
	return {
		q: String(params.get("q") || "").trim(),
		page: positiveInteger(params.get("page"), 1),
		pageSize: PEOPLE_PAGE_SIZES.includes(requestedSize) ? requestedSize : DEFAULT_PEOPLE_PAGE_SIZE,
		role: choice(params.get("role"), PEOPLE_ROLES),
		verification: choice(params.get("verification"), PEOPLE_VERIFICATIONS),
		activity: choice(params.get("activity"), PEOPLE_ACTIVITIES),
		project: String(params.get("project") || "")
			.trim()
			.slice(0, 255),
		ordering: choice(params.get("ordering"), PEOPLE_ORDERINGS, "relevance"),
		attributionPage: positiveInteger(params.get("attribution_page"), 1)
	};
}

/** @param {ReturnType<typeof peopleDirectoryState>} state */
function peopleDirectoryHref(state) {
	const params = new URLSearchParams();
	if (state.q) params.set("q", state.q);
	if (state.role) params.set("role", state.role);
	if (state.verification) params.set("verification", state.verification);
	if (state.activity) params.set("activity", state.activity);
	if (state.project) params.set("project", state.project);
	if (state.ordering !== "relevance") params.set("ordering", state.ordering);
	if (state.pageSize !== DEFAULT_PEOPLE_PAGE_SIZE) params.set("page_size", String(state.pageSize));
	if (state.page > 1) params.set("page", String(state.page));
	if (state.attributionPage > 1) params.set("attribution_page", String(state.attributionPage));
	return `/people${params.size > 0 ? `?${params}` : ""}`;
}

/** @param {string} value @param {string} current @param {string} label */
function option(value, current, label) {
	return `<option value="${esc(value)}"${value === current ? " selected" : ""}>${esc(label)}</option>`;
}

/** @param {ReturnType<typeof peopleDirectoryState>} state */
function activeFilterSummary(state) {
	const values = [
		state.role ? relationshipLabel(state.role) : "",
		state.verification
			? {
					verified: t("authors.filterVerified", "Currently verified"),
					unverified: t("authors.filterUnverified", "Unverified"),
					renewal_needed: t("authors.filterRenewal", "Renewal needed")
				}[state.verification]
			: "",
		state.activity ? t("authors.activityFilterValue", "Activity: $1", state.activity) : "",
		state.project ? t("authors.projectFilterValue", "Project: $1", state.project) : ""
	].filter(Boolean);
	return values.length > 0
		? `<div class="people-directory__active"><span>${t("authors.activeFilters", "Active filters:")} ${values.map((value) => `<strong>${esc(value)}</strong>`).join(" · ")}</span><a href="/people">${t("authors.clearFilters", "Clear filters")}</a></div>`
		: "";
}

/** @param {any} directory @param {ReturnType<typeof peopleDirectoryState>} state */
function resolvedDirectoryResults(directory, state) {
	const people = directory.people || [];
	const count = Number(directory.count) || 0;
	const first = people.length > 0 ? (directory.page - 1) * directory.pageSize + 1 : 0;
	const last = first + people.length - 1;
	const summary =
		people.length > 0
			? t("authors.showingPeopleRange", "Showing $1–$2 of $3 people", first, last, count)
			: t("authors.peopleCount", "$1 people", count);
	return `<section aria-labelledby="people-profiles-title">
		<div class="section-head people-page__results-head"><div><h2 id="people-profiles-title" class="people-page__section-title">${t("authors.resolvedProfiles", "Resolved profiles")}</h2><p class="muted" aria-live="polite">${esc(summary)}${state.q ? ` ${t("authors.forQuery", "for")} “<span${dirAttrs(state.q)}>${esc(state.q)}</span>”` : ""}</p></div></div>
		${peopleResults(people)}
		<nav class="pager" data-people-pager aria-label="${esc(t("authors.peoplePagination", "People pagination"))}">${renderPager(directory.page, directory.pageCount)}</nav>
	</section>`;
}

/** @param {any} directory */
function unresolvedDirectoryResults(directory) {
	const attributions = directory.attributions || [];
	if (attributions.length === 0 && !directory.error) return "";
	return `<section class="people-attributions" aria-labelledby="people-attributions-title">
		<div class="section-head"><div><h2 id="people-attributions-title">${t("authors.unresolvedAttributions", "Attributions awaiting identity evidence")}</h2><p class="muted people-attributions__intro">${t("authors.unresolvedAttributionsIntro", "These labels appear in tool records, but there is not enough stable evidence to publish them as people.")}</p></div><span class="muted">${esc(t("authors.labelCount", "$1 {{PLURAL:$2|label|labels}}", fmt(directory.count || 0), directory.count || 0))}</span></div>
		${
			directory.error
				? `<p class="empty" role="alert">${t("authors.attributionSearchFailed", "Unresolved attributions could not be loaded.")}</p>`
				: `<ul class="people-attributions__list">${attributions.map((attribution) => unresolvedAttribution(attribution)).join("")}</ul><nav class="pager" data-attribution-pager aria-label="${esc(t("authors.attributionPagination", "Unresolved attribution pagination"))}">${renderPager(directory.page, directory.pageCount)}</nav>`
		}
	</section>`;
}

function peopleSearchError() {
	return `<div class="empty people-directory__error" role="alert"><p>${t("authors.peopleSearchFailed", "People search could not be loaded. Try again.")}</p><button class="btn btn--primary" type="button" data-people-retry>${t("authors.retrySearch", "Retry search")}</button></div>`;
}

/** @param {ReturnType<typeof peopleDirectoryState>} state */
function directoryForm(state) {
	const roleOptions = [
		["", t("authors.anyRole", "Any role")],
		...Array.from(PEOPLE_ROLES, (role) => [role, relationshipLabel(role)])
	]
		.map(([value, label]) => option(value, state.role, label))
		.join("");
	const verificationOptions = [
		["", t("authors.anyVerification", "Any verification")],
		["verified", t("authors.filterVerified", "Currently verified")],
		["unverified", t("authors.filterUnverified", "Unverified")],
		["renewal_needed", t("authors.filterRenewal", "Renewal needed")]
	]
		.map(([value, label]) => option(value, state.verification, label))
		.join("");
	const activityOptions = [
		["", t("authors.anyActivity", "Any activity")],
		["active", t("authors.activityActive", "Active")],
		["quiet", t("authors.activityQuiet", "Quiet")],
		["unknown", t("authors.activityUnknown", "Unknown")]
	]
		.map(([value, label]) => option(value, state.activity, label))
		.join("");
	const orderingOptions = [
		["relevance", t("authors.orderRelevance", "Most relevant")],
		["relationship", t("authors.orderRelationship", "Strongest relationships")],
		["recent", t("authors.orderRecent", "Recent activity")],
		["name", t("authors.orderName", "Name (A–Z)")]
	]
		.map(([value, label]) => option(value, state.ordering, label))
		.join("");
	const pageSizeOptions = PEOPLE_PAGE_SIZES.map((size) =>
		option(String(size), String(state.pageSize), t("authors.peoplePerPage", "$1 per page", size))
	).join("");
	return `<form class="people-directory" data-people-search role="search">
		<div class="searchbar people-page__search"><input class="searchbar__input" name="q" type="search" value="${esc(state.q)}" placeholder="${esc(t("authors.searchPeople", "Search people"))}" aria-label="${esc(t("authors.searchPeople", "Search people"))}" /><button class="btn btn--primary" type="submit">${icon("search")} ${t("authors.search", "Search")}</button></div>
		<fieldset class="people-directory__filters"><legend class="skip-label">${t("authors.directoryFilters", "Directory filters")}</legend>
			<label><span>${t("authors.roleFilter", "Role")}</span><select name="role" data-people-auto>${roleOptions}</select></label>
			<label><span>${t("authors.verificationFilter", "Verification")}</span><select name="verification" data-people-auto>${verificationOptions}</select></label>
			<label><span>${t("authors.activityFilter", "Activity")}</span><select name="activity" data-people-auto>${activityOptions}</select></label>
			<label><span>${t("authors.projectFilter", "Project or wiki")}</span><input name="project" value="${esc(state.project)}" placeholder="wikidata.org" /></label>
			<label><span>${t("authors.ordering", "Sort by")}</span><select name="ordering" data-people-auto>${orderingOptions}</select></label>
			<label><span>${t("authors.resultsPerPage", "Results per page")}</span><select name="page_size" data-people-auto>${pageSizeOptions}</select></label>
		</fieldset>
	</form>`;
}

export async function viewPeople() {
	const state = peopleDirectoryState();
	const attributionsApplicable = !state.verification && !state.activity;
	const [directoryResult, attributionResult] = await Promise.allSettled([
		searchPeopleDirectory(state),
		attributionsApplicable
			? searchUnresolvedAttributions({
					q: state.q,
					page: state.attributionPage,
					pageSize: 10,
					role: state.role,
					project: state.project
				})
			: Promise.resolve({ attributions: [], count: 0, page: 1, pageSize: 10, pageCount: 1 })
	]);
	const directory =
		directoryResult.status === "fulfilled"
			? directoryResult.value
			: { people: [], count: 0, page: state.page, pageSize: state.pageSize, pageCount: 1, error: true };
	const attributions =
		attributionResult.status === "fulfilled"
			? attributionResult.value
			: { attributions: [], count: 0, page: state.attributionPage, pageSize: 10, pageCount: 1, error: true };
	return {
		title: state.q
			? t("authors.peopleSearchDocTitle", "$1 — People — Toolhub", state.q)
			: t("authors.peopleDocTitle", "People — Toolhub"),
		html: `<div class="container page people-page">
			<header><h1 class="page__title">${t("authors.peopleTitle", "People")}</h1><p class="page__intro">${t("authors.peopleIntro", "Discover authors, maintainers, record owners, and catalog contributors resolved from Toolhub and Evolved evidence.")}</p></header>
			${directoryForm(state)}
			${activeFilterSummary(state)}
			<div data-people-results>${directory.error ? peopleSearchError() : resolvedDirectoryResults(directory, state)}</div>
			<div data-attribution-results>${attributionsApplicable ? unresolvedDirectoryResults(attributions) : ""}</div>
		</div>`,
		mount() {
			const form = /** @type {HTMLFormElement | null} */ ($("[data-people-search]"));
			const showLoading = () => {
				const target = $("[data-people-results]");
				if (target) {
					target.innerHTML = `<p class="signin-note" role="status" aria-live="polite">${t("authors.searching", "Searching…")}</p>`;
				}
			};
			const navigateFromForm = () => {
				if (!form) return;
				const data = new FormData(form);
				showLoading();
				navigateTo(
					peopleDirectoryHref({
						q: String(data.get("q") || "").trim(),
						page: 1,
						pageSize: positiveInteger(String(data.get("page_size") || ""), DEFAULT_PEOPLE_PAGE_SIZE),
						role: choice(String(data.get("role") || ""), PEOPLE_ROLES),
						verification: choice(String(data.get("verification") || ""), PEOPLE_VERIFICATIONS),
						activity: choice(String(data.get("activity") || ""), PEOPLE_ACTIVITIES),
						project: String(data.get("project") || "")
							.trim()
							.slice(0, 255),
						ordering: choice(String(data.get("ordering") || ""), PEOPLE_ORDERINGS, "relevance"),
						attributionPage: 1
					})
				);
			};
			form?.addEventListener("submit", (event) => {
				event.preventDefault();
				navigateFromForm();
			});
			form?.querySelectorAll("[data-people-auto]").forEach((control) =>
				control.addEventListener("change", navigateFromForm)
			);
			$("[data-people-pager]")?.addEventListener("click", (event) => {
				const button = /** @type {HTMLElement | null} */ (event.target?.closest?.("[data-page]"));
				if (!button) return;
				showLoading();
				navigateTo(
					peopleDirectoryHref({
						...state,
						page: positiveInteger(button.getAttribute("data-page"), state.page)
					})
				);
			});
			$("[data-attribution-pager]")?.addEventListener("click", (event) => {
				const button = /** @type {HTMLElement | null} */ (event.target?.closest?.("[data-page]"));
				if (!button) return;
				navigateTo(
					peopleDirectoryHref({
						...state,
						attributionPage: positiveInteger(button.getAttribute("data-page"), state.attributionPage)
					})
				);
			});
			$("[data-people-retry]")?.addEventListener("click", () => {
				showLoading();
				window.dispatchEvent(new Event("toolhub:navigate"));
			});
		}
	};
}
