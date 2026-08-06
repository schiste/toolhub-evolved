// SPDX-License-Identifier: GPL-3.0-or-later
import { dirAttrs, esc, safeUrl } from "../lib/core/dom.js";
import { authorProfileUrl, toolsByAuthor } from "../lib/core/author-index.js";
import { countLabel, t } from "../lib/core/i18n.js";
import { personByHandle, personById, searchPeopleDirectory, toolsForPerson } from "../lib/core/people.js";
import { personHref } from "../lib/core/routing.js";
import { attachEvolvedSummaries, EVOLVED_SUMMARY_GRACE_MS } from "../lib/core/signals.js";
import { icon } from "../lib/atoms/icon.js";
import { avatar } from "../lib/atoms/avatar.js";
import { grid } from "../lib/organisms/grid.js";
import { toolCard } from "../lib/organisms/tool-card.js";

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

const ROLE_ORDER = ["record_owner", "maintainer", "author", "catalog_actor"];

/** @param {string} role */
function roleLabel(role) {
	const labels = /** @type {Record<string, string>} */ ({
		record_owner: t("authors.recordOwnerTools", "Toolhub records managed"),
		maintainer: t("authors.maintainerTools", "Tools maintained"),
		author: t("authors.authorTools", "Tools authored"),
		catalog_actor: t("authors.catalogActorTools", "Catalog contributions")
	});
	return labels[role] || t("authors.relatedTools", "Related tools");
}

/** Each tool is rendered once, under the strongest relationship it carries. @param {Tool[]} tools */
function groupedTools(tools) {
	const groups = /** @type {Map<string, Tool[]>} */ (new Map(ROLE_ORDER.map((role) => [role, []])));
	for (const tool of tools) {
		const roles = new Set(
			(Array.isArray(/** @type {any} */ (tool).personRelationships)
				? /** @type {any} */ (tool).personRelationships
				: []
			).map((/** @type {any} */ relationship) => relationship?.type)
		);
		const primary = ROLE_ORDER.find((role) => roles.has(role)) || "author";
		groups.get(primary)?.push(tool);
	}
	return ROLE_ORDER.map((role) => {
		const rows = groups.get(role) || [];
		return rows.length > 0
			? `<section class="author-page__tools" aria-labelledby="author-role-${role}"><div class="section-head"><h2 id="author-role-${role}">${esc(roleLabel(role))}</h2><span class="muted">${rows.length}</span></div>${grid("grid-tools", rows, (/** @type {Tool} */ tool) => toolCard(tool))}</section>`
			: "";
	}).join("");
}

/** @param {any} activity @param {number} toolCount */
function activityStats(activity, toolCount) {
	const stats = [
		[t("authors.relatedToolsStat", "Related tools"), activity?.relatedToolCount ?? toolCount],
		[t("authors.verifiedToolsStat", "Verified tools"), activity?.verifiedToolCount ?? 0],
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
	const body =
		tools.length > 0
			? groupedTools(tools)
			: `<p class="empty">${t("authors.noToolsFound", "No tools found for this person.")}</p>`;
	const bio = profile.bio ? `<div class="prose author-page__bio">${esc(profile.bio)}</div>` : "";
	const meta = [
		profile.location,
		person?.activity?.status && person.activity.status !== "unknown" ? person.activity.status : ""
	]
		.filter(Boolean)
		.join(" · ");
	const avatarUrl = safeUrl(profile.avatarUrl);
	const profileAvatar = avatarUrl
		? `<img class="author-page__avatar" src="${esc(avatarUrl)}" alt="" width="96" height="96" />`
		: avatar(name, "avatar--lg author-page__avatar");
	return {
		title: t("authors.docTitle", "{name} — Toolhub", { name }),
		html: `<div class="container page author-page">
			<a class="back" href="/search">${t("authors.backToTools", "← Back to tools")}</a>
			<div class="section-head author-page__head">
				<div class="author-page__identity">
					${profileAvatar}
					<div>
					<h1 class="page__title"${dirAttrs(name)}>${esc(name)}</h1>
					<p class="page__intro">${esc(countLabel(tools.length, t("authors.toolOne", "tool"), t("authors.toolOther", "tools")))}</p>
					${meta ? `<p class="muted">${esc(meta)}</p>` : ""}
					</div>
				</div>
				${externalLinks ? `<div class="author-page__links">${externalLinks}</div>` : ""}
			</div>
			${bio}
			${activityStats(person?.activity, tools.length)}
			${body}
		</div>`
	};
}

/** @param {any} person */
async function resolvedView(person) {
	const tools = await toolsForPerson(person);
	await attachEvolvedSummaries(tools, { graceMs: EVOLVED_SUMMARY_GRACE_MS });
	return renderPerson(person, tools);
}

/** Legacy name route; the name is resolved through current identifiers first. @param {string} name */
export async function viewAuthor(name) {
	const person = await personByHandle(name).catch(() => null);
	if (person) return resolvedView(person);
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
	const person = await personById(publicId);
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
	return `<a class="people-card" href="${personHref(person.id)}" data-person-name="${esc(name.toLocaleLowerCase())}">
		${picture}<span><strong${dirAttrs(name)}>${esc(name)}</strong><small>${esc(countLabel(count, t("authors.toolOne", "tool"), t("authors.toolOther", "tools")))}</small></span>
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
		<span class="people-attribution__content"><strong${dirAttrs(label)}>${esc(label)}</strong><small>${esc(countLabel(tools, t("authors.toolOne", "tool"), t("authors.toolOther", "tools")))} · ${esc(countLabel(observations, t("authors.observationOne", "observation"), t("authors.observationOther", "observations")))}</small></span>
		<span class="people-attribution__status">${t("authors.identityUnresolved", "Identity unresolved")}</span>
	</li>`;
}

/** @param {{people: any[], unresolvedAttributions: any[]}} directory */
function directoryResults(directory) {
	const unresolved = directory.unresolvedAttributions || [];
	return `<section aria-labelledby="people-profiles-title">
		<h2 id="people-profiles-title" class="people-page__section-title">${t("authors.resolvedProfiles", "Resolved profiles")}</h2>
		${peopleResults(directory.people || [])}
	</section>
	${
		unresolved.length > 0
			? `<section class="people-attributions" aria-labelledby="people-attributions-title">
			<div class="section-head"><div><h2 id="people-attributions-title">${t("authors.unresolvedAttributions", "Attributions awaiting identity evidence")}</h2><p class="muted people-attributions__intro">${t("authors.unresolvedAttributionsIntro", "These labels appear in tool records, but there is not enough stable evidence to publish them as people.")}</p></div></div>
			<ul class="people-attributions__list">${unresolved.map((attribution) => unresolvedAttribution(attribution)).join("")}</ul>
		</section>`
			: ""
	}`;
}

export async function viewPeople() {
	const directory = await searchPeopleDirectory("");
	return {
		title: t("authors.peopleDocTitle", "People — Toolhub"),
		html: `<div class="container page people-page">
			<header><h1 class="page__title">${t("authors.peopleTitle", "People")}</h1><p class="page__intro">${t("authors.peopleIntro", "Discover authors, maintainers, record owners, and catalog contributors resolved from Toolhub and Evolved evidence.")}</p></header>
			<form class="searchbar people-page__search" data-people-search role="search"><input class="searchbar__input" name="q" type="search" placeholder="${esc(t("authors.searchPeople", "Search people"))}" aria-label="${esc(t("authors.searchPeople", "Search people"))}" /><button class="btn btn--primary" type="submit">${icon("search")} ${t("authors.search", "Search")}</button></form>
			<div data-people-results>${directoryResults(directory)}</div>
		</div>`,
		mount() {
			document.querySelector("[data-people-search]")?.addEventListener("submit", async (event) => {
				event.preventDefault();
				const form = /** @type {HTMLFormElement} */ (event.currentTarget);
				const target = document.querySelector("[data-people-results]");
				const query = String(new FormData(form).get("q") || "").trim();
				if (target) target.innerHTML = `<p class="signin-note">${t("authors.searching", "Searching…")}</p>`;
				try {
					const results = await searchPeopleDirectory(query);
					if (target) target.innerHTML = directoryResults(results);
				} catch {
					if (target) {
						target.innerHTML = `<p class="empty">${t("authors.peopleSearchFailed", "People search could not be loaded. Try again.")}</p>`;
					}
				}
			});
		}
	};
}
