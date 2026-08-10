// SPDX-License-Identifier: GPL-3.0-or-later
import { $, dirAttrs, esc, safeUrl } from "../lib/core/dom.js";
import { authorProfileUrl, toolsByAuthor } from "../lib/core/author-index.js";
import { fmt, t } from "../lib/core/i18n.js";
import { identityQualityLabel, relationshipLabel } from "../lib/core/claims.js";
import { personById, resolvePersonHandle, searchCommunity, toolsForPerson } from "../lib/core/people.js";
import { navigateTo, personHref } from "../lib/core/routing.js";
import { attachEvolvedSummaries, EVOLVED_SUMMARY_GRACE_MS } from "../lib/core/signals.js";
import { icon } from "../lib/atoms/icon.js";
import { avatar } from "../lib/atoms/avatar.js";
import { button } from "../lib/atoms/button.js";
import { entityCard } from "../lib/organisms/entity-card.js";
import { grid } from "../lib/organisms/grid.js";
import { toolCard } from "../lib/organisms/tool-card.js";
import { relationshipTrustMarkup } from "../lib/molecules/relationship-trust.js";
import { renderPager } from "../lib/molecules/pager.js";
import { communityHeader } from "./community.js";

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
	return personCard({ kind: "person", person, identityEvidence: {}, matchBasis: ["identity"] });
}

/** @param {string} name @param {any} resolution */
function renderDisambiguation(name, resolution) {
	const candidates = Array.isArray(resolution?.candidates) ? resolution.candidates : [];
	const unresolved = Array.isArray(resolution?.unresolvedAttributions) ? resolution.unresolvedAttributions : [];
	const choices =
		candidates.length > 0
			? `<section aria-labelledby="author-candidates-title"><h2 id="author-candidates-title" class="people-page__section-title">${t("authors.possiblePeople", "Possible people")}</h2><ul class="card-grid grid-tools" role="list">${candidates.map((/** @type {any} */ person) => `<li>${disambiguationCard(person)}</li>`).join("")}</ul></section>`
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

/** @param {string} role @param {boolean} verified */
function relationshipSummaryLabel(role, verified) {
	const label = relationshipLabel(role);
	return verified
		? t("authors.verifiedRelationship", "Verified $1 relationship", label)
		: t("authors.listedRelationship", "Listed $1", label);
}

/** @param {string} role @param {any} summary */
function relationshipCardSignal(role, summary) {
	const verifiedTypes = Array.isArray(summary?.verifiedTypes) ? summary.verifiedTypes : [];
	const total = Number(summary?.toolCountsByType?.[role]) || 0;
	if (!["maintainer", "record_owner"].includes(role) || total === 0) {
		return relationshipSummaryLabel(role, verifiedTypes.includes(role));
	}
	const verified = Math.min(total, Number(summary?.verifiedToolCountsByType?.[role]) || 0);
	const label = relationshipLabel(role);
	if (verified === total) {
		return t(
			"authors.verifiedRelationshipToolCount",
			"Verified $1 relationship · $2 {{PLURAL:$3|tool|tools}}",
			label,
			fmt(total),
			total
		);
	}
	if (verified > 0) {
		return t(
			"authors.partlyVerifiedRelationshipToolCount",
			"$1 · $2 of $3 {{PLURAL:$4|tool|tools}} verified",
			label,
			fmt(verified),
			fmt(total),
			total
		);
	}
	return t(
		"authors.listedRelationshipToolCount",
		"Listed $1 · $2 {{PLURAL:$3|tool|tools}}",
		label,
		fmt(total),
		total
	);
}

/** @param {any} summary */
function relationshipCardMetrics(summary) {
	const counts = summary?.toolCountsByType || {};
	const verifiedCounts = summary?.verifiedToolCountsByType || {};
	return [
		["maintainer", t("authors.maintainerToolsMetric", "Tools maintained")],
		["record_owner", t("authors.recordOwnerToolsMetric", "Toolhub records owned")]
	].map(([role, label]) => {
		const total = Number(counts[role]) || 0;
		const verified = Math.min(total, Number(verifiedCounts[role]) || 0);
		return {
			label,
			value: fmt(total),
			detail: total > 0 ? t("authors.verifiedToolCountMetric", "$1 verified", fmt(verified)) : ""
		};
	});
}

/** @param {any} item */
function personCard(item) {
	const person = item?.person || item;
	const name = person?.displayName || t("authors.unknownPerson", "Unknown person");
	const avatarUrl = safeUrl(person?.profile?.avatarUrl);
	const picture = avatarUrl
		? `<img class="avatar avatar--img entity-card__avatar" src="${esc(avatarUrl)}" alt="" width="48" height="48" loading="lazy" />`
		: avatar(name, "entity-card__avatar");
	const count = Number(person?.activity?.relatedToolCount) || 0;
	const summary = person?.relationshipSummary || {};
	const verifiedTypes = Array.isArray(summary.verifiedTypes) ? summary.verifiedTypes : [];
	const types = Array.isArray(summary.types) ? summary.types : [];
	const identityEvidence = item?.identityEvidence || {};
	const account = Array.isArray(item?.officialAccountMatches) ? item.officialAccountMatches[0] : null;
	const identityLabels = [
		identityEvidence.officialToolhubAccount || account
			? t("authors.officialToolhubAccount", "Official Toolhub account")
			: "",
		identityEvidence.wikimediaIdentity
			? t("authors.wikimediaIdentity", "Wikimedia identity matched by stable ID")
			: "",
		identityEvidence.toolforgeHandle ? t("authors.toolforgeHandle", "Toolforge username") : "",
		identityEvidence.wikiHandle ? t("authors.wikiHandle", "Wiki username") : ""
	].filter(Boolean);
	if (identityLabels.length === 0) {
		identityLabels.push(
			...(Array.isArray(person?.identifiers) ? person.identifiers : [])
				.filter((/** @type {any} */ identifier) => identifier?.value)
				.map((/** @type {any} */ identifier) => identifierLabel(identifier))
		);
	}
	if (identityLabels.length === 0) identityLabels.push(identityQualityLabel(person?.identityQuality || ""));
	const matchBasis = Array.isArray(item?.matchBasis) ? item.matchBasis : [];
	const matchDetail = matchBasis.includes("tool")
		? t("authors.matchedByTool", "Matched through a related tool")
		: account?.username
			? t("authors.accountUsername", "Toolhub username: $1", account.username)
			: "";
	const contributorBases = /** @type {string[]} */ (
		Array.isArray(person?.contributor?.bases) ? person.contributor.bases : []
	);
	const contributorDetail =
		contributorBases.length > 0
			? contributorBases
					.map((/** @type {string} */ basis) =>
						basis === "canonical_catalog_actor"
							? t("authors.canonicalCatalogActor", "Observed canonical Toolhub catalog activity")
							: t("authors.approvedContribution", "Approved public contribution activity")
					)
					.join(" · ")
			: "";
	return entityCard({
		kind: t("authors.personResult", "Person"),
		kindDetail: identityQualityLabel(person?.identityQuality || ""),
		title: name,
		href: personHref(person.id),
		visual: picture,
		subtitle: t("authors.toolCount", "$1 {{PLURAL:$2|tool|tools}}", fmt(count), count),
		description: [matchDetail, contributorDetail].filter(Boolean).join(" · "),
		metrics: relationshipCardMetrics(summary),
		tags: identityLabels.map((label) => ({ label, className: "entity-card__tag--identity" })),
		signals: types.map((/** @type {string} */ role) => {
			const verified = verifiedTypes.includes(role);
			return {
				label: relationshipCardSignal(role, summary),
				className: verified ? "status status--green" : "signal signal--compact"
			};
		}),
		className: verifiedTypes.length > 0 ? "entity-card--verified" : "entity-card--stable",
		dataName: name.toLocaleLowerCase()
	});
}

/** @param {any} item @param {ReturnType<typeof peopleDirectoryState>} state */
function accountResultCard(item, state) {
	const account = item?.account || {};
	const relationshipSummary = item?.relationshipSummary;
	const name = String(account.username || t("accounts.unknown", "Unknown account"));
	const href = peopleDirectoryHref({ ...state, accountId: String(account.id || "") });
	const linked = Boolean(account.personId);
	return entityCard({
		kind: t("authors.accountResult", "Official account"),
		kindDetail: linked
			? t("accounts.linkedPersonShort", "Linked identity")
			: t("authors.accountOnly", "Account only"),
		title: name,
		href,
		visual: avatar(name, "entity-card__avatar"),
		subtitle: account.id ? t("authors.toolhubAccountId", "Toolhub ID $1", account.id) : "",
		description: linked
			? t("accounts.linkedPerson", "Linked to a public person through a stable identifier")
			: t("authors.noPublicRelationship", "No stable public person or tool relationship is linked yet."),
		metrics: linked && relationshipSummary ? relationshipCardMetrics(relationshipSummary) : [],
		tags: [
			{
				label: t("authors.officialToolhubAccount", "Official Toolhub account"),
				className: "entity-card__tag--identity"
			},
			...(account.wikimediaGlobalUserId
				? [
						{
							label: t("authors.wikimediaStableId", "Wikimedia stable ID"),
							className: "entity-card__tag--identity"
						}
					]
				: [])
		],
		className: linked ? "entity-card--stable" : "entity-card--account",
		dataName: name.toLocaleLowerCase()
	});
}

/** @param {any} attribution */
function unresolvedAttribution(attribution, asCard = false) {
	const label = attribution?.label || t("authors.unknownAttribution", "Unknown attribution");
	const tools = Number(attribution?.toolCount) || 0;
	const observations = Number(attribution?.evidenceCount) || Number(attribution?.attributionCount) || 0;
	if (asCard) {
		return entityCard({
			kind: t("authors.unresolvedResult", "Unresolved attribution"),
			kindDetail: t("authors.needsIdentityEvidence", "Needs identity evidence"),
			title: label,
			visual: `<span class="avatar entity-card__avatar entity-card__unknown" aria-hidden="true">?</span>`,
			subtitle: `${t("authors.toolCount", "$1 {{PLURAL:$2|tool|tools}}", fmt(tools), tools)} · ${t("authors.observationCount", "$1 {{PLURAL:$2|observation|observations}}", fmt(observations), observations)}`,
			description: t("authors.unverifiedAttribution", "Unverified attribution — name-only evidence"),
			tags: [{ label: t("authors.nameOnlyEvidence", "Name-only evidence") }],
			className: "entity-card--unresolved",
			dataName: label.toLocaleLowerCase(),
			static: true
		});
	}
	const content = `
		<span class="people-attribution__mark" aria-hidden="true">?</span>
		<span class="people-attribution__content"><strong${dirAttrs(label)}>${esc(label)}</strong><small>${esc(t("authors.toolCount", "$1 {{PLURAL:$2|tool|tools}}", fmt(tools), tools))} · ${esc(t("authors.observationCount", "$1 {{PLURAL:$2|observation|observations}}", fmt(observations), observations))}</small></span>
		<span class="people-attribution__status">${t("authors.unverifiedAttribution", "Unverified attribution — name-only evidence")}</span>`;
	return `<li class="people-attribution">${content}</li>`;
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
	const legacyView = String(params.get("view") || "");
	return {
		q: String(params.get("q") || "")
			.trim()
			.slice(0, 255),
		page: positiveInteger(params.get("page"), 1),
		pageSize: PEOPLE_PAGE_SIZES.includes(requestedSize) ? requestedSize : DEFAULT_PEOPLE_PAGE_SIZE,
		role: choice(params.get("role"), PEOPLE_ROLES),
		verification: choice(params.get("verification"), PEOPLE_VERIFICATIONS),
		activity: choice(params.get("activity"), PEOPLE_ACTIVITIES),
		project: String(params.get("project") || "")
			.trim()
			.slice(0, 255),
		ordering: choice(params.get("ordering"), PEOPLE_ORDERINGS, "relevance"),
		contributor: params.get("contributor") === "observed" || legacyView === "contributors",
		accountId: String(params.get("account") || "")
			.trim()
			.slice(0, 64)
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
	if (state.contributor) params.set("contributor", "observed");
	if (state.pageSize !== DEFAULT_PEOPLE_PAGE_SIZE) params.set("page_size", String(state.pageSize));
	if (state.page > 1) params.set("page", String(state.page));
	if (state.accountId) params.set("account", state.accountId);
	return `/people${params.size > 0 ? `?${params}` : ""}`;
}

/** @param {string} value @param {string} current @param {string} label */
function option(value, current, label) {
	return `<option value="${esc(value)}"${value === current ? " selected" : ""}>${esc(label)}</option>`;
}

/** @param {any} directory @param {ReturnType<typeof peopleDirectoryState>} state */
function communityResultSummary(directory, state) {
	const results = Array.isArray(directory?.results) ? directory.results : [];
	const count = Number(directory?.count) || 0;
	const first = results.length > 0 ? (directory.page - 1) * directory.pageSize + 1 : 0;
	const last = first + results.length - 1;
	const counts = directory?.counts || {};
	const breakdown = [
		Number(counts.people) > 0
			? t("authors.personCount", "$1 {{PLURAL:$2|person|people}}", fmt(counts.people), counts.people)
			: "",
		Number(counts.accounts) > 0
			? t(
					"authors.accountCount",
					"$1 {{PLURAL:$2|account-only result|account-only results}}",
					fmt(counts.accounts),
					counts.accounts
				)
			: "",
		Number(counts.unresolvedAttributions) > 0
			? t(
					"authors.unresolvedCount",
					"$1 {{PLURAL:$2|unresolved attribution|unresolved attributions}}",
					fmt(counts.unresolvedAttributions),
					counts.unresolvedAttributions
				)
			: ""
	].filter(Boolean);
	const range =
		results.length > 0
			? t("authors.showingCommunityRange", "Showing $1–$2 of $3 results", first, last, count)
			: t("authors.communityCount", "$1 results", count);
	return `${esc(range)}${state.q ? ` ${t("authors.forQuery", "for")} “<span${dirAttrs(state.q)}>${esc(state.q)}</span>”` : ""}${breakdown.length > 0 ? ` <span class="browse__count-note">${esc(breakdown.join(" · "))}</span>` : ""}`;
}

/** @param {any} directory @param {ReturnType<typeof peopleDirectoryState>} state */
function communityDirectoryResults(directory, state) {
	const results = Array.isArray(directory?.results) ? directory.results : [];
	const cards = results
		.map((/** @type {any} */ item) => {
			if (item?.kind === "person") return personCard(item);
			if (item?.kind === "account") return accountResultCard(item, state);
			if (item?.kind === "unresolved_attribution") return unresolvedAttribution(item.attribution, true);
			return "";
		})
		.filter(Boolean)
		.map((/** @type {string} */ card) => `<li>${card}</li>`)
		.join("");
	const truncated = directory?.truncated
		? `<p class="account-directory__notice account-directory__notice--warning" role="status">${t("authors.refineResults", "Many records matched. Refine the search to see the most relevant identities and evidence.")}</p>`
		: "";
	return `<section aria-labelledby="community-results-title">
		<h2 id="community-results-title" class="skip-label">${t("authors.directoryResults", "Directory results")}</h2>
		${truncated}
		${results.length > 0 ? `<ul class="card-grid grid-tools community-results" role="list">${cards}</ul>` : `<p class="empty">${t("authors.noCommunityMatches", "No people, official accounts, tools, or unresolved attributions match this search.")}</p>`}
		<nav class="pager" data-people-pager aria-label="${esc(t("authors.peoplePagination", "Directory pagination"))}">${renderPager(directory.page, directory.pageCount)}</nav>
	</section>`;
}

function peopleSearchError() {
	return `<div class="empty people-directory__error" role="alert"><p>${t("authors.peopleSearchFailed", "Community search could not be loaded. Try again.")}</p><button class="btn btn--primary" type="button" data-people-retry>${t("authors.retrySearch", "Retry search")}</button></div>`;
}

/** @param {any} sync */
function accountEvidenceNotice(sync) {
	const status = String(sync?.status || "unavailable");
	if (status === "ready") return "";
	if (status === "stale") {
		return `<p class="account-directory__notice account-directory__notice--warning" role="status">${t("authors.staleAccountEvidence", "Official Toolhub account evidence is temporarily stale; the last complete snapshot is being used.")}</p>`;
	}
	if (status === "refreshing" || status === "building") {
		return `<p class="account-directory__notice" role="status">${t("authors.refreshingAccountEvidence", "Official Toolhub account evidence is currently refreshing.")}</p>`;
	}
	return `<p class="account-directory__notice account-directory__notice--warning" role="status">${t("authors.unavailableAccountEvidence", "Official Toolhub account corroboration is currently unavailable. Public identity and relationship results are still shown.")}</p>`;
}

/** @param {ReturnType<typeof peopleDirectoryState>} state */
function directorySidebar(state) {
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
	const contributorOptions = [
		["", t("authors.anyContribution", "Any contribution evidence")],
		["observed", t("authors.observedContributors", "Observed contributors only")]
	]
		.map(([value, label]) => option(value, state.contributor ? "observed" : "", label))
		.join("");
	const clearFilters = button(t("authors.clearFilters", "Clear filters"), {
		variant: "outline",
		href: "/people",
		cls: "facets__reset"
	});
	return `<aside class="facets community-facets" aria-label="${esc(t("authors.directoryFilters", "Directory filters"))}">
		<form data-people-search role="search">
			<label for="people-q" class="skip-label">${t("authors.searchCommunity", "Search a person, username, or tool")}</label>
			<input id="people-q" class="facets__search" name="q" type="search" value="${esc(state.q)}" placeholder="${esc(t("authors.searchCommunity", "Search a person, username, or tool"))}" autocomplete="off" />
			<div class="facet-group"><label class="facet-group__title" for="people-role">${t("authors.roleFilter", "Role")}</label><select id="people-role" class="le__input community-facets__control" name="role" data-people-auto>${roleOptions}</select></div>
			<div class="facet-group"><label class="facet-group__title" for="people-verification">${t("authors.verificationFilter", "Verification")}</label><select id="people-verification" class="le__input community-facets__control" name="verification" data-people-auto>${verificationOptions}</select></div>
			<div class="facet-group"><label class="facet-group__title" for="people-activity">${t("authors.activityFilter", "Activity")}</label><select id="people-activity" class="le__input community-facets__control" name="activity" data-people-auto>${activityOptions}</select></div>
			<div class="facet-group"><label class="facet-group__title" for="people-contributor">${t("authors.contributionFilter", "Contribution evidence")}</label><select id="people-contributor" class="le__input community-facets__control" name="contributor" data-people-auto>${contributorOptions}</select></div>
			<div class="facet-group"><label class="facet-group__title" for="people-project">${t("authors.projectFilter", "Project or wiki")}</label><input id="people-project" class="le__input community-facets__control" name="project" value="${esc(state.project)}" placeholder="wikidata.org" /></div>
			${clearFilters}
		</form>
	</aside>`;
}

/** @param {ReturnType<typeof peopleDirectoryState>} state */
function directoryResultControls(state) {
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
	return `<span class="browse__controls">
		<label class="sort"><span class="skip-label">${t("authors.resultsPerPage", "Results per page")}</span><select id="people-page-size">${pageSizeOptions}</select></label>
		<label class="sort"><span class="skip-label">${t("authors.ordering", "Sort by")}</span><select id="people-sort">${orderingOptions}</select></label>
	</span>`;
}

export async function viewPeople() {
	const state = peopleDirectoryState();
	let directory = null;
	let directoryFailed = false;
	try {
		directory = await searchCommunity({
			...state,
			contributor: state.contributor ? "observed" : ""
		});
	} catch {
		directoryFailed = true;
	}
	return {
		title: state.q
			? t("authors.communitySearchDocTitle", "$1 — Community — Toolhub", state.q)
			: t("authors.communityDocTitle", "Community directory — Toolhub"),
		html: `<div class="container page people-page community-directory">
			${communityHeader()}
			<div class="browse">
				${directorySidebar(state)}
				<div class="browse__main">
					<div class="browse__bar">
						<span class="browse__count" aria-live="polite">${directoryFailed ? t("authors.directoryResults", "Directory results") : communityResultSummary(directory, state)}</span>
						${directoryResultControls(state)}
					</div>
					${directoryFailed ? "" : accountEvidenceNotice(directory?.accountSync)}
					<div data-people-results>${directoryFailed ? peopleSearchError() : communityDirectoryResults(directory, state)}</div>
				</div>
			</div>
		</div>`,
		mount() {
			const legacyView = new URLSearchParams(location.search).get("view");
			if (legacyView) history.replaceState({}, "", peopleDirectoryHref(state));
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
				const pageSize = /** @type {HTMLSelectElement | null} */ ($("#people-page-size"));
				const ordering = /** @type {HTMLSelectElement | null} */ ($("#people-sort"));
				showLoading();
				navigateTo(
					peopleDirectoryHref({
						q: String(data.get("q") || "").trim(),
						page: 1,
						pageSize: positiveInteger(pageSize?.value || "", DEFAULT_PEOPLE_PAGE_SIZE),
						role: choice(String(data.get("role") || ""), PEOPLE_ROLES),
						verification: choice(String(data.get("verification") || ""), PEOPLE_VERIFICATIONS),
						activity: choice(String(data.get("activity") || ""), PEOPLE_ACTIVITIES),
						contributor: String(data.get("contributor") || "") === "observed",
						project: String(data.get("project") || "")
							.trim()
							.slice(0, 255),
						ordering: choice(ordering?.value || "", PEOPLE_ORDERINGS, "relevance"),
						accountId: ""
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
			$("#people-sort")?.addEventListener("change", navigateFromForm);
			$("#people-page-size")?.addEventListener("change", navigateFromForm);
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
			$("[data-people-retry]")?.addEventListener("click", () => {
				showLoading();
				window.dispatchEvent(new Event("toolhub:navigate"));
			});
		}
	};
}
