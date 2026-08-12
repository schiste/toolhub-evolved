// SPDX-License-Identifier: GPL-3.0-or-later
import { dirAttrs, esc, safeHttpUrl, safeUrl, textAttrs } from "../lib/core/dom.js";
import { relativeTime, t, timeTag } from "../lib/core/i18n.js";
import {
	INDEX,
	apiGet,
	backendErrorExplanation,
	backendGetJson,
	clearApiCache,
	getTool,
	isNewTool
} from "../lib/core/api.js";
import { renderMarkdown } from "../lib/core/markdown.js";
import { peopleForTool } from "../lib/core/people.js";
import { officialWrite, officialWriteAvailable, serverWrite } from "../lib/core/serversync.js";
import {
	attachEvolvedSummaries,
	completeness,
	endorsementOf,
	EVOLVED_SUMMARY_GRACE_MS,
	listMemberships,
	SUMMARY_VIEW_FULL
} from "../lib/core/signals.js";
import { signedIn } from "../lib/core/session.js";
import { SYNC_STATUS, clearLocalToolDraft, demoRevisionsFor } from "../lib/core/store.js";
import { authorProfileUrl } from "../lib/core/author-index.js";
import { authorHref, navigateTo, personHref, toolHref } from "../lib/core/routing.js";
import { avatar, toolIcon } from "../lib/atoms/avatar.js";
import { completenessList, completenessMeter, endorsementChip, fitChip, statusBadge } from "../lib/atoms/badges.js";
import { button } from "../lib/atoms/button.js";
import { icon } from "../lib/atoms/icon.js";
import { glanceChips, keywordTags, langLabel, linkOut, metaItem, wikiLabel } from "../lib/atoms/labels.js";
import { favBtn } from "../lib/molecules/favbtn.js";
import { saveToListControl } from "../lib/molecules/savemenu.js";
import { fieldProvenance, syncStatusPanel } from "../lib/molecules/sync-status.js";
import { healthScoreChip, maintainerDisclosure } from "../lib/molecules/tool-health-summary.js";
import { relationshipTrustMarkup } from "../lib/molecules/relationship-trust.js";
import { openClaimDrawer } from "../lib/organisms/claim-drawer.js";
import { setIssueContext } from "../lib/organisms/issue-drawer.js";
import { prosePage, viewNotFound } from "./static.js";

const QUICK_VIEW_BUTTON_STYLE =
	"appearance: none; border: 0; background: none; padding: 0; color: inherit; font-family: inherit; text-align: start; cursor: pointer;";

/** @typedef {{ name: string, publicId?: string, profile: { url?: string | null, wikiUsername?: string | null } }} AuthorEntry */
/** @typedef {{ id?: string, displayName?: string, identifiers?: Array<{ namespace?: string, value?: string }>, relationships?: Array<any> }} PublicPerson */
/** @typedef {{ people?: PublicPerson[], unresolvedAttributions?: Array<any> }} PeopleSummary */

/** @param {{ tool: Tool, shared?: string[] }} item */
function relatedToolRow(item) {
	const tool = item.tool;
	// Stryker disable next-line ArrayDeclaration: nearestNeighbors() always provides a `shared` array; the `|| []` fallback is never taken — equivalent.
	const chips = (item.shared || []).map((label) => `<span class="tag">${esc(label)}</span>`).join("");
	const deprecated = tool.deprecated
		? `<span class="related__status status status--red"><span class="dot dot--red"></span>${t("tool.deprecated", "Deprecated")}</span>`
		: "";
	return `
		<article class="related__item" data-tool="${esc(tool.name)}">
			${avatar(tool.title)}
			<div class="related__body">
				<div class="related__titleline">
					<button class="related__title" type="button" data-tool="${esc(tool.name)}" aria-label="${t("tool.quickLookAria", "Quick look: $1", esc(tool.title))}" style="${QUICK_VIEW_BUTTON_STYLE}"${textAttrs(tool.title, tool.titleLanguage)}>${esc(tool.title)}</button>
					${deprecated}
				</div>
				<div class="related__maint">${t("tool.by", "by")} <span${dirAttrs(tool.maintainer)}>${esc(tool.maintainer)}</span></div>
				${chips ? `<div class="related__chips">${chips}</div>` : ""}
			</div>
	</article>`;
}

/**
 * @param {Array<{ tool: Tool, shared?: string[] }>} related
 */
function relatedToolsSection(related) {
	return related.length > 0
		? `<section class="related" aria-labelledby="related-title">
			<div class="section-head"><h2 id="related-title">${t("tool.relatedTitle", "Related tools")}</h2></div>
			<p class="related__subtitle">${t("tool.relatedSubtitle", "Overlapping function and scope, by shared metadata.")}</p>
			<div class="related__list">${related.map((item) => relatedToolRow(item)).join("")}</div>
		</section>`
		: "";
}

/** @param {any | null} ego */
function neighborhoodSection(ego) {
	return ego
		? `<section class="neighborhood" aria-labelledby="neighborhood-title">
			<div class="section-head"><h2 id="neighborhood-title">${t("tool.neighborhoodTitle", "Neighborhood")}</h2></div>
			<div class="graph graph--ego"><div id="ego-canvas"></div></div>
			<p class="graph__caption">${t("tool.neighborhoodCaption", "This tool and its nearest neighbors by metadata. Click a node to peek.")}</p>
		</section>`
		: "";
}

/**
 * @param {() => void} task
 * @param {number} [delayMs]
 */
function afterDetailPrimaryPaint(task, delayMs = 0) {
	const runTask = () => {
		if (delayMs > 0) setTimeout(task, delayMs);
		else task();
	};
	const scheduleIdle = () => {
		if ("requestIdleCallback" in window) {
			/** @type {any} */ (window).requestIdleCallback(runTask, { timeout: 1500 + delayMs });
		} else {
			setTimeout(runTask, 600);
		}
	};
	if (typeof window.requestAnimationFrame === "function") {
		window.requestAnimationFrame(() => setTimeout(scheduleIdle, 0));
	} else {
		scheduleIdle();
	}
}

/**
 * @param {string | null | undefined} iso
 * @param {string} label
 * @param {string} title
 * @param {string} iconName
 */
function freshnessSignal(iso, label, title, iconName) {
	if (!iso) return "";
	const date = new Date(iso);
	const rel = relativeTime(iso);
	if (Number.isNaN(date.getTime()) || !rel) return "";
	return `<span class="signal toolpage__freshness">${icon(iconName)}
		<time class="toolpage__when" datetime="${esc(date.toISOString())}" title="${esc(title)}" aria-label="${esc(title)}">${esc(label)}</time>
	</span>`;
}

/** @param {Tool} tool */
function catalogUpdatedSignal(tool) {
	const rel = relativeTime(tool.modified);
	if (!rel) return "";
	const date = new Date(tool.modified || "");
	const iso = Number.isNaN(date.getTime()) ? "" : date.toISOString();
	return freshnessSignal(
		tool.modified,
		t("tool.toolhubListingUpdated", "Toolhub listing updated $1", rel),
		t(
			"tool.toolhubListingUpdatedTooltip",
			"Toolhub catalog listing last modified: $1",
			iso || String(tool.modified || "")
		),
		"history"
	);
}

/** @param {any} evolvedSummary */
function repositoryUpdatedSignal(evolvedSummary) {
	const repository = evolvedSummary?.health?.sourceHealth?.repository;
	if (!repository || typeof repository !== "object") return "";
	const lastCommitAt = String(repository.lastCommitAt || "").trim();
	const commitSha = String(repository.commitSha || "").trim();
	const rel = relativeTime(lastCommitAt);
	const date = new Date(lastCommitAt);
	if (!rel || Number.isNaN(date.getTime())) return "";
	const tooltipLines = [
		commitSha
			? t("tool.repositoryLastCommit", "Last known repository commit: $1", commitSha)
			: t("tool.repositoryLastCommitUnknown", "Last known repository commit id unavailable."),
		repository.branch ? t("tool.repositoryBranch", "Branch: $1", String(repository.branch)) : "",
		t("tool.repositoryUpdatedAt", "Repository updated at: $1", date.toISOString())
	].filter(Boolean);
	return freshnessSignal(
		lastCommitAt,
		t("tool.repositoryUpdated", "Repository updated $1", rel),
		tooltipLines.join("\n"),
		"code"
	);
}

/** @param {string} name */
function viewToolNotFound(name) {
	const rawName = String(name ?? "");
	const searchHref = `/search?q=${encodeURIComponent(rawName)}`;
	return {
		title: t("tool.notFoundDocTitle", "Tool not found — Toolhub"),
		html: `
		<div class="container page">
			<a class="back" href="/search">${t("tool.backToTools", "← Back to tools")}</a>
			<h1 class="page__title">${t("tool.notFoundTitle", "Tool not found")}</h1>
			<p class="page__intro">${t("tool.notFoundIntroLead", "The record for")} <code${dirAttrs(rawName)}>${esc(rawName)}</code> ${t("tool.notFoundIntroMid", "may have been")} <strong>${t("tool.notFoundIntroFates", "deleted, renamed, or never registered")}</strong>.</p>
			<p><a href="${searchHref}">${t("tool.searchForName", 'Search for "$1"', esc(rawName))}</a> · <a href="/search">${t("tool.browseAllTools", "Browse all tools")}</a></p>
		</div>`
	};
}

/**
 * @param {Tool} t
 * @returns {AuthorEntry[]}
 */
function authorEntries(t) {
	const names = (t.authors && t.authors.length > 0 ? t.authors : [t.maintainer]).filter(Boolean);
	/** @type {Array<{ name?: string, url?: string | null, wikiUsername?: string | null }>} */
	// Stryker disable next-line ArrayDeclaration: normalizeTool always provides an `authorObjs` array; the `|| []` fallback is never taken — equivalent.
	const records = t.authorObjs || [];
	return names.map((name, i) => {
		const byIndex = records[i];
		const found = byIndex && byIndex.name === name ? byIndex : records.find((a) => a && a.name === name);
		// Stryker disable next-line ObjectLiteral: only `record.url`/`record.wikiUsername` are read below (both undefined here), so `{ name }` and `{}` are indistinguishable — equivalent.
		const record = found || /** @type {{ name: string, url?: string | null, wikiUsername?: string }} */ ({ name });
		return { name, profile: { url: record.url, wikiUsername: record.wikiUsername } };
	});
}

/** @param {AuthorEntry} entry */
function authorExternalLink(entry) {
	const url = safeUrl(authorProfileUrl(entry.profile));
	if (!url) return "";
	return `<a class="author-ref__external" href="${url}" target="_blank" rel="noopener nofollow" aria-label="${t("tool.externalProfileAria", "External profile for $1", esc(entry.name))}">${icon("external")}</a>`;
}

/** @param {AuthorEntry} entry */
function authorLink(entry) {
	const href = entry.publicId ? personHref(entry.publicId) : authorHref(entry.name);
	return `<span class="author-ref"><a href="${esc(href)}"${dirAttrs(entry.name)}>${esc(entry.name)}</a>${authorExternalLink(entry)}</span>`;
}

/** @param {Tool} t @param {PeopleSummary | null} peopleSummary */
function authorInlineList(t, peopleSummary) {
	const authors = Array.isArray(peopleSummary?.people)
		? peopleSummary.people.filter((person) =>
				person.relationships?.some((relationship) => relationship.type === "author")
			)
		: [];
	const entries = authorEntries(t).map((entry) => {
		const key = entry.name.toLocaleLowerCase();
		const person = authors.find(
			(candidate) =>
				candidate.displayName?.toLocaleLowerCase() === key ||
				candidate.identifiers?.some((identifier) => identifier.value?.toLocaleLowerCase() === key) ||
				candidate.relationships?.some((relationship) =>
					relationship.evidence?.some(
						(/** @type {any} */ evidence) => evidence.observedName?.toLocaleLowerCase() === key
					)
				)
		);
		return person ? { ...entry, publicId: person.id } : entry;
	});
	return entries.map((entry) => authorLink(entry)).join('<span class="toolpage__sep">, </span>');
}

/** @param {PeopleSummary | null} peopleSummary */
function maintainerPeople(peopleSummary) {
	const people = peopleSummary?.people;
	if (!Array.isArray(people)) return [];
	return people.flatMap((person) =>
		(Array.isArray(person.relationships) ? person.relationships : [])
			.filter((relationship) => relationship?.type === "maintainer")
			.map((relationship) => ({
				entry: {
					name: person.displayName || t("tool.unknownMaintainer", "Unknown"),
					publicId: person.id,
					profile: {
						wikiUsername: person.identifiers?.find((item) => item.namespace === "wiki_username")?.value
					}
				},
				relationship
			}))
	);
}

/** @param {any} item */
function maintainerRelationshipRow(item) {
	return `<li class="maint-list__item">
		<div class="maint-list__identity">${avatar(item.entry.name)}<span class="maint-list__name">${authorLink(item.entry)}</span></div>
		${relationshipTrustMarkup(item.relationship)}
	</li>`;
}

/** @param {any} attribution */
function unresolvedMaintainerRow(attribution) {
	const name = attribution?.label || t("tool.unknownMaintainer", "Unknown");
	const relationship = {
		type: "maintainer",
		status: "unverified",
		confidence: attribution?.bestConfidence || 0,
		evidenceCount: attribution?.evidenceCount || attribution?.attributionCount || 0,
		toolhubCanonical: false,
		evidence: []
	};
	return `<li class="maint-list__item">
		<div class="maint-list__identity">${avatar(name)}<span class="maint-list__name"><span${dirAttrs(name)}>${esc(name)}</span><small>${t("tool.identityUnresolved", "Identity unresolved")}</small></span></div>
		${relationshipTrustMarkup(relationship)}
	</li>`;
}

/** @param {string} title @param {string} className @param {string[]} rows */
function maintainerGroup(title, className, rows) {
	return rows.length > 0
		? `<section class="maint-list__group ${className}"><h3>${title}</h3><ul>${rows.join("")}</ul></section>`
		: "";
}

/** @param {PeopleSummary | null} peopleSummary */
function maintainerListMarkup(peopleSummary) {
	if (!peopleSummary) {
		return `<p class="maint-list__empty">${t("tool.maintainerRelationshipsUnavailable", "Maintainer relationship data is currently unavailable.")}</p>`;
	}
	const entries = maintainerPeople(peopleSummary);
	const verified = entries.filter((item) => item.relationship?.status === "verified");
	const other = entries.filter((item) => item.relationship?.status !== "verified");
	const unresolved = (
		Array.isArray(peopleSummary.unresolvedAttributions) ? peopleSummary.unresolvedAttributions : []
	).filter((attribution) =>
		Array.isArray(attribution?.relationshipTypes) ? attribution.relationshipTypes.includes("maintainer") : false
	);
	const markup =
		maintainerGroup(
			t("tool.verifiedMaintainerRelationships", "Verified current relationships"),
			"maint-list__group--verified",
			verified.map((item) => maintainerRelationshipRow(item))
		) +
		maintainerGroup(
			t("tool.otherMaintainerAttributions", "Unverified or previous attributions"),
			"maint-list__group--other",
			[
				...other.map((item) => maintainerRelationshipRow(item)),
				...unresolved.map((attribution) => unresolvedMaintainerRow(attribution))
			]
		);
	return (
		markup ||
		`<p class="maint-list__empty">${t("tool.noMaintainerRelationship", "No maintainer relationship has been verified for this tool yet.")}</p>`
	);
}

/** @param {string | null} qid */
function wikidataChip(qid) {
	const id = String(qid || "").trim();
	if (!id) return "";
	const url = safeUrl(`https://www.wikidata.org/wiki/${encodeURIComponent(id)}`);
	return `<a class="glance toolpage__wikidata" href="${url}" target="_blank" rel="noopener nofollow">${t("tool.wikidataLabel", "Wikidata:")} <span dir="auto">${esc(id)}</span>${icon("external")}</a>`;
}

/** @param {string | { name?: string, url?: string } | null | undefined} entry */
function sponsorEntry(entry) {
	let name = "";
	// Stryker disable next-line StringLiteral: `url` is only ever read through safeUrl(); a non-http(s) sentinel is rejected to "" just like the empty default — equivalent.
	let url = "";
	if (typeof entry === "string") {
		name = entry;
	} else if (entry) {
		name = entry.name || entry.url || "";
		// Stryker disable next-line StringLiteral: safeUrl() rejects any non-http(s) sentinel to "", so the empty fallback is indistinguishable — equivalent.
		url = entry.url || "";
	}
	if (!name) return "";
	const body = esc(name);
	const href = safeUrl(url);
	return href
		? `<a href="${href}" target="_blank" rel="noopener nofollow"${dirAttrs(name)}>${body}</a>`
		: `<span${dirAttrs(name)}>${body}</span>`;
}

/** @param {string[] | string | null | undefined} sponsor */
function sponsorLine(sponsor) {
	const entries = Array.isArray(sponsor) ? sponsor : sponsor ? [sponsor] : [];
	const html = entries
		.map((entry) => sponsorEntry(entry))
		.filter(Boolean)
		.join(", ");
	return html
		? `<div class="toolpage__sponsor"><span class="toolpage__label">${t("tool.sponsorLabel", "Sponsor:")}</span> ${html}</div>`
		: "";
}

/** @param {Tool} tool */
function replacementNote(tool) {
	if (!tool.deprecated || !tool.replacedBy) return "";
	const value = /** @type {string | { name?: string, title?: string } | null} */ (tool.replacedBy);
	const name = typeof value === "string" ? value : (value && (value.name || value.title)) || "";
	if (!name) return "";
	const label = esc(name);
	const linked = /^https?:\/\//i.test(name)
		? `<a href="${safeUrl(name)}" target="_blank" rel="noopener nofollow">${label}</a>`
		: `<a href="${esc(toolHref(name))}"${dirAttrs(name)}>${label}</a>`;
	return `<div class="toolpage__notice">${t("tool.replacedBy", "Replaced by")} ${linked}</div>`;
}

const CATALOG_SOURCE_LABELS = {
	official_toolhub: "Official Toolhub",
	official_toolinfo: "Registered toolinfo.json",
	self_hosted_toolinfo: "Discovered toolinfo.json",
	repository_analysis: "Repository analysis",
	evolved_curation: "Reviewed Evolved correction"
};

/** @param {unknown} value */
function evidenceValue(value) {
	if (Array.isArray(value)) return value.join(", ");
	if (value && typeof value === "object") {
		const localized = /** @type {Record<string, any>} */ (value);
		return String(localized.en || localized.mul || Object.values(localized)[0] || "");
	}
	return String(value ?? "");
}

/** @param {Record<string, any> | null | undefined} projection */
function catalogProvenancePanel(projection) {
	const provenance = projection?.provenance;
	if (!provenance || typeof provenance !== "object") return "";
	const labels = {
		title: t("tool.provenanceTitleField", "Title"),
		description: t("tool.provenanceDescriptionField", "Description"),
		url: t("tool.provenanceUrlField", "Tool URL"),
		repository: t("tool.provenanceRepositoryField", "Repository"),
		icon: t("tool.provenanceIconField", "Icon"),
		tool_type: t("tool.provenanceTypeField", "Tool type"),
		for_wikis: t("tool.provenanceWikisField", "Wikis"),
		technology_used: t("tool.provenanceTechnologyField", "Technology")
	};
	const sections = Object.entries(labels)
		.map(([field, label]) => {
			const rows = Array.isArray(provenance[field]) ? provenance[field] : [];
			if (rows.length === 0) return "";
			const fieldValidation = projection?.validation?.[field] || {};
			const distinct = new Set(
				rows.map((row) => evidenceValue(row.value).trim().toLocaleLowerCase()).filter(Boolean)
			);
			const warning =
				fieldValidation.reachable === false
					? `<span class="catalog-evidence__warning">${t("tool.provenanceUnreachable", "URL currently unreachable")}</span>`
					: rows.some((row) => row.valid === false)
						? `<span class="catalog-evidence__warning">${t("tool.provenanceInvalidEvidence", "invalid evidence retained")}</span>`
						: distinct.size > 1
							? `<span class="catalog-evidence__warning">${t("tool.provenanceContradiction", "sources disagree")}</span>`
							: "";
			const items = rows
				.map((row) => {
					const source =
						/** @type {Record<string, string>} */ (CATALOG_SOURCE_LABELS)[row.source] ||
						row.source ||
						t("tool.provenanceUnknown", "Unknown source");
					const href = safeUrl(row.sourceUrl);
					const sourceMarkup = href
						? `<a href="${href}" target="_blank" rel="noopener nofollow">${esc(source)}</a>`
						: `<span>${esc(source)}</span>`;
					return `<li class="${row.effective ? "catalog-evidence__effective" : ""}"><strong>${esc(evidenceValue(row.value))}</strong> · ${sourceMarkup}${row.effective ? ` · ${t("tool.provenanceEffective", "effective")}` : ` · ${t("tool.provenanceSupporting", "supporting")}`}${row.valid === false ? ` · ${t("tool.provenanceInvalid", "invalid")}` : ""}</li>`;
				})
				.join("");
			return `<details class="catalog-evidence__field"><summary>${esc(label)} ${warning}</summary><ul>${items}</ul></details>`;
		})
		.filter(Boolean)
		.join("");
	if (!sections) return "";
	return `<section class="catalog-evidence" aria-labelledby="catalog-evidence-title"><h2 class="toolpage__h2" id="catalog-evidence-title">${t("tool.provenanceTitle", "Metadata evidence")}</h2><p>${t("tool.provenanceIntro", "Toolhub Evolved keeps the official record intact and shows which local evidence supports each displayed field.")}</p>${sections}</section>`;
}

/** @param {Record<string, any> | null} signals */
function evolvedSignalsPanel(signals) {
	const thanks = signals?.thanks || {};
	const usage = signals?.usage30d || {};
	const health = signals?.health || {};
	const thanksCount = Number(thanks.count || 0);
	const usageCount = Number(usage.count || 0);
	const healthStatus = health.status && health.status !== "unknown" ? String(health.status) : "";
	if (!signedIn() && !thanksCount && !usageCount && !healthStatus) return "";
	return `<div class="panel" data-evolved-signals>
		<h2 class="panel__title">${t("tool.evolvedSignals", "Evolved signals")}</h2>
		<div class="toolpage__signal-list">
			${thanksCount ? `<span class="signal">${t("tool.thanksCount", "$1 thanks on Evolved", String(thanksCount))}</span>` : ""}
			${usageCount ? `<span class="signal">${t("tool.usageCount", "$1 Evolved interactions in 30 days", String(usageCount))}</span>` : ""}
			${healthStatus ? `<span class="signal">${t("tool.healthStatus", "Evolved health: $1", esc(healthStatus))}</span>` : ""}
		</div>
		${
			signedIn()
				? button(
						thanks.userThanked ? t("tool.thanked", "Thanks sent") : t("tool.thankTool", "Thank this tool"),
						{
							variant: "outline",
							attrs: `data-thanks${thanks.userThanked ? ' data-thanked="1"' : ""}`
						}
					)
				: ""
		}
		<p class="at__result" data-signals-result aria-live="polite"></p>
	</div>`;
}

/** @param {Array<Record<string, any>>} media */
function mediaPanel(media) {
	const approved = media
		.map((item) => {
			const url = safeUrl(item.url);
			if (!url) return "";
			const title = item.title || t("tool.screenshot", "Screenshot");
			const license = item.license ? ` · ${esc(item.license)}` : "";
			const label = item.syncLabel || t("tool.evolvedDataLabel", "Evolved data");
			return `<figure class="tool-media__item"><img src="${url}" alt="${esc(title)}" loading="lazy" /><figcaption>${esc(title)}${license} · ${esc(label)}</figcaption></figure>`;
		})
		.filter(Boolean)
		.join("");
	const submit = signedIn()
		? `<form class="tool-media__form" data-media-form>
			<input class="le__input" data-media-url type="url" placeholder="${t("tool.mediaUrl", "Screenshot URL")}" aria-label="${t("tool.mediaUrl", "Screenshot URL")}" />
			<input class="le__input" data-media-license placeholder="${t("tool.mediaLicense", "License")}" aria-label="${t("tool.mediaLicense", "License")}" />
			<input class="le__input" data-media-source placeholder="${t("tool.mediaSource", "Source")}" aria-label="${t("tool.mediaSource", "Source")}" />
			${button(t("tool.submitMedia", "Submit screenshot"), { variant: "outline", type: "submit" })}
		</form>`
		: "";
	if (!approved && !submit) return "";
	return `<div class="panel tool-media">
		<h2 class="panel__title">${t("tool.screenshotsTitle", "Screenshots · Evolved data")}</h2>
		${approved ? `<div class="tool-media__grid">${approved}</div>` : ""}
		${submit}
		<p class="at__result" data-media-result aria-live="polite"></p>
	</div>`;
}

/** @param {string} name */
function bindOptionalToolPanelEvents(name) {
	document.querySelector("[data-thanks]")?.addEventListener("click", async (event) => {
		const btn = /** @type {HTMLElement} */ (event.currentTarget);
		const out = /** @type {HTMLElement | null} */ (document.querySelector("[data-signals-result]"));
		const thanked = btn.getAttribute("data-thanked") === "1";
		try {
			await serverWrite(thanked ? "DELETE" : "POST", `/v1/tools/${encodeURIComponent(name)}/thanks/`);
			btn.setAttribute("data-thanked", thanked ? "0" : "1");
			btn.textContent = thanked ? t("tool.thankTool", "Thank this tool") : t("tool.thanked", "Thanks sent");
			if (out) {
				out.className = "at__result at__result--ok";
				out.textContent = thanked
					? t("tool.thanksRemoved", "Thanks removed.")
					: t("tool.thanksSaved", "Thanks saved.");
			}
		} catch {
			if (out) {
				out.className = "at__result at__result--err";
				out.textContent = t("tool.thanksFailed", "Could not update thanks.");
			}
		}
	});
	document.querySelector("[data-media-form]")?.addEventListener("submit", async (event) => {
		event.preventDefault();
		const form = /** @type {HTMLElement} */ (event.currentTarget);
		/** @param {string} selector */
		const value = (selector) =>
			/** @type {HTMLInputElement | null} */ (form.querySelector(selector))?.value.trim() || "";
		const out = /** @type {HTMLElement | null} */ (document.querySelector("[data-media-result]"));
		try {
			await serverWrite("POST", `/v1/tools/${encodeURIComponent(name)}/media/`, {
				url: value("[data-media-url]"),
				license: value("[data-media-license]"),
				source: value("[data-media-source]")
			});
			if (out) {
				out.className = "at__result at__result--ok";
				out.textContent = t("tool.mediaSubmitted", "Screenshot submitted for review.");
			}
			form.querySelectorAll("input").forEach((input) => {
				/** @type {HTMLInputElement} */ (input).value = "";
			});
		} catch {
			if (out) {
				out.className = "at__result at__result--err";
				out.textContent = t("tool.mediaFailed", "Could not submit screenshot.");
			}
		}
	});
}

/**
 * @param {Tool & { edited?: boolean, annotated?: boolean }} tool
 * @param {string} name
 */
function toolSyncUi(tool, name) {
	const coreViewerOwned = tool.viewerOwned !== false;
	const editViewerOwned = tool.editViewerOwned !== false;
	const annotationViewerOwned = tool.annotationViewerOwned !== false;
	const coreMeta = {
		syncStatus: tool.syncStatus,
		lastError: tool.lastError,
		validationErrors: tool.validationErrors,
		reviewStatus: tool.reviewStatus,
		toolhubResponse: tool.toolhubResponse,
		toolhubStatus: tool.toolhubStatus,
		toolhubCode: tool.toolhubCode,
		origin: tool.origin
	};
	const editMeta = {
		syncStatus: tool.editSyncStatus,
		lastError: tool.editLastError,
		validationErrors: tool.editValidationErrors,
		reviewStatus: tool.editReviewStatus,
		toolhubResponse: tool.editToolhubResponse,
		toolhubStatus: tool.editToolhubStatus,
		toolhubCode: tool.editToolhubCode,
		origin: tool.origin
	};
	const annotationMeta = {
		syncStatus: tool.annotationSyncStatus,
		lastError: tool.annotationLastError,
		validationErrors: tool.annotationValidationErrors,
		reviewStatus: tool.annotationReviewStatus,
		toolhubResponse: tool.annotationToolhubResponse,
		toolhubStatus: tool.annotationToolhubStatus,
		toolhubCode: tool.annotationToolhubCode
	};
	const hasCoreSyncPanel =
		isNewTool(name) || Boolean(tool.lastError || tool.validationErrors?.length || tool.reviewStatus);
	const hasEditSyncPanel =
		Boolean(tool.edited) ||
		Boolean(tool.editLastError || tool.editValidationErrors?.length || tool.editReviewStatus);
	const hasAnnotationSyncPanel =
		Boolean(tool.annotated) ||
		Boolean(tool.annotationLastError || tool.annotationValidationErrors?.length || tool.annotationReviewStatus);
	const needsReconciliation = (/** @type {any} */ meta) =>
		[SYNC_STATUS.localFallback, SYNC_STATUS.syncError].includes(String(meta?.syncStatus || "")) ||
		Boolean(meta?.lastError || meta?.validationErrors?.length);
	const hiddenReconciliation =
		(hasCoreSyncPanel && !coreViewerOwned && needsReconciliation({ ...coreMeta, syncStatus: tool.syncStatus })) ||
		(hasEditSyncPanel &&
			!editViewerOwned &&
			needsReconciliation({
				syncStatus: tool.editSyncStatus,
				lastError: tool.editLastError,
				validationErrors: tool.editValidationErrors
			})) ||
		(hasAnnotationSyncPanel &&
			!annotationViewerOwned &&
			needsReconciliation({
				syncStatus: tool.annotationSyncStatus,
				lastError: tool.annotationLastError,
				validationErrors: tool.annotationValidationErrors
			}));
	const provTags = [
		wikidataChip(tool.wikidata),
		...(signedIn()
			? [
					isNewTool(name) && coreViewerOwned
						? fieldProvenance(t("tool.coreFields", "Core fields"), coreMeta)
						: "",
					tool.edited && editViewerOwned
						? fieldProvenance(t("tool.coreFields", "Core fields"), editMeta)
						: "",
					tool.annotated && annotationViewerOwned
						? fieldProvenance(t("tool.communityAnnotations", "Community annotations"), annotationMeta)
						: ""
				]
			: [])
	]
		.filter(Boolean)
		.join(" ");
	const syncPanels = [
		hasCoreSyncPanel && coreViewerOwned && signedIn()
			? syncStatusPanel(coreMeta, {
					title: t("tool.coreWriteStatus", "Core field write status"),
					guidance:
						tool.origin && tool.origin !== "api"
							? t(
									"syncStatus.crawlerOwnedGuidance",
									"This tool is managed by a crawler. Update its public toolinfo.json source and wait for the next crawl; generic core-field edits are not accepted by official Toolhub."
								)
							: ""
				})
			: "",
		hasEditSyncPanel && editViewerOwned && signedIn()
			? syncStatusPanel(editMeta, { title: t("tool.coreWriteStatus", "Core field write status") })
			: "",
		hasAnnotationSyncPanel && annotationViewerOwned && signedIn()
			? syncStatusPanel(annotationMeta, { title: t("tool.annotationWriteStatus", "Annotation write status") })
			: ""
	]
		.filter(Boolean)
		.join("");
	const reconciliationNotice = hiddenReconciliation
		? `<p class="sync-reconciliation" role="status">${t("syncStatus.reconciliationNotice", "Some tool data needs to be reconciled with official Toolhub.")}</p>`
		: "";
	return { provTags, syncPanels, reconciliationNotice };
}

/** @param {any} viewerContext */
function viewerActionAudience(viewerContext) {
	return ["verified_maintainer", "tool_manager"].includes(viewerContext?.audience)
		? viewerContext.audience
		: "contributor";
}

/** @param {Tool} tool @param {string} audience @param {boolean} canDeleteOfficialTool */
function toolManagementActions(tool, audience, canDeleteOfficialTool) {
	const historyAction = button(t("tool.viewHistory", "View history"), {
		variant: "outline",
		size: "md",
		href: `${toolHref(tool.name)}/history`,
		icon: "history"
	});
	const verifiedMaintainer = audience === "verified_maintainer";
	const toolManager = audience === "tool_manager";
	const groupLabel = verifiedMaintainer
		? t("tool.ownerActions", "Maintainer actions")
		: toolManager
			? t("tool.recordAuthorityActions", "Tool management")
			: t("tool.contributeActions", "Contribute");
	const claimLabel =
		verifiedMaintainer || toolManager
			? t("tool.manageRelationships", "Manage relationships")
			: t("claim.toolAction", "Claim a relationship");
	const editLabel = verifiedMaintainer
		? t("tool.editTool", "Edit tool")
		: toolManager
			? t("tool.editToolhubRecord", "Edit Toolhub record")
			: t("tool.suggestToolChanges", "Suggest tool changes");
	const annotationLabel =
		verifiedMaintainer || toolManager
			? t("tool.editAnnotations", "Edit annotations")
			: t("tool.contributeAnnotations", "Contribute annotations");
	const managementLinks = signedIn()
		? `<div class="toolpage__management" aria-label="${esc(groupLabel)}">
			<span class="toolpage__owner-label">${groupLabel}</span>
			${button(claimLabel, {
				variant: "outline",
				size: "md",
				icon: "group",
				attrs: "data-tool-claim"
			})}
			${historyAction}
			${button(editLabel, { variant: "outline", size: "md", href: `${toolHref(tool.name)}/edit`, icon: "edit" })}
			${button(annotationLabel, { variant: "outline", size: "md", href: `${toolHref(tool.name)}/edit-annotations`, icon: "tag" })}
			${
				canDeleteOfficialTool
					? button(t("tool.deleteOfficialTool", "Delete official tool"), {
							variant: "danger",
							size: "md",
							icon: "reset",
							attrs: "data-tool-delete"
						})
					: ""
			}
		</div>`
		: `<div class="toolpage__management" aria-label="${esc(t("tool.actionsTitle", "Actions"))}">
			${historyAction}
			${button(t("tool.suggestAnEdit", "Suggest an edit"), {
				variant: "outline",
				size: "md",
				href: `${toolHref(tool.name)}/edit`,
				icon: "edit"
			})}
		</div>`;
	return { managementLinks };
}

/** @param {string} name */
export async function viewTool(name) {
	// The name is known from the route, so the local summary read does not have
	// to wait for the canonical record. Running it alongside getTool costs no
	// extra wall time — the upstream read is the slower of the two — and means
	// the health score is present for the first render rather than arriving in
	// a later repaint.
	const summaryReady = attachEvolvedSummaries([{ name }], {
		graceMs: EVOLVED_SUMMARY_GRACE_MS,
		view: SUMMARY_VIEW_FULL
	}).catch(() => null);
	const peopleReady = peopleForTool(name).catch(() => null);
	const viewerContextReady = signedIn()
		? backendGetJson(`/v1/tools/${encodeURIComponent(name)}/viewer-context/`).catch(() => null)
		: Promise.resolve(null);
	const tool =
		/** @type {(Tool & { edited?: boolean, annotated?: boolean, endorsement?: { count?: number } }) | null} */ (
			await getTool(name)
		);
	if (!tool) return viewToolNotFound(name);
	const resolvedTool = tool;
	// Signals, media, and fresh summaries are additive Evolved data. Keep the
	// canonical tool page render independent from their availability and let
	// mount() hydrate their dedicated slots after the primary content exists.
	await summaryReady;
	const [peopleSummary, viewerContext] = await Promise.all([peopleReady, viewerContextReady]);
	// Reads the cache the call above just filled; no further request.
	await attachEvolvedSummaries([tool], { view: SUMMARY_VIEW_FULL });
	const evolvedSummary = /** @type {{ evolvedSummary?: any }} */ (tool).evolvedSummary;
	setIssueContext(() => ({
		kind: "tool",
		name: tool.name,
		title: tool.title,
		url: safeHttpUrl(tool.url),
		repository: safeHttpUrl(tool.repository),
		maintainer: tool.maintainer,
		modified: tool.modified,
		deprecated: Boolean(tool.deprecated),
		experimental: Boolean(tool.experimental),
		health: evolvedSummary?.health?.score ?? null
	}));
	const { provTags, syncPanels, reconciliationNotice } = toolSyncUi(tool, name);
	const tags = keywordTags(tool, { empty: "—" });
	const authors = authorInlineList(tool, peopleSummary);
	const openToolUrl = safeHttpUrl(tool.url);

	// REAL links — render only the ones present on the record.
	const actions = [
		linkOut(t("tool.sourceCode", "Source code"), tool.repository),
		linkOut(t("tool.apiLabel", "API"), tool.apiUrl),
		linkOut(t("tool.userDocs", "User docs"), tool.userDocs),
		linkOut(t("tool.developerDocs", "Developer docs"), tool.devDocs),
		linkOut(t("tool.reportABug", "Report a bug"), tool.bugtracker),
		linkOut(t("tool.giveFeedback", "Give feedback"), tool.feedback),
		linkOut(t("tool.translate", "Translate"), tool.translate)
	].join("");

	// Official Toolhub status flags stay visible alongside Evolved-local panels.
	const realBadge = statusBadge(tool);
	const actionAudience = viewerActionAudience(viewerContext);
	const canDeleteOfficialTool =
		actionAudience === "tool_manager" && officialWriteAvailable() && !isNewTool(tool.name);
	const { managementLinks } = toolManagementActions(tool, actionAudience, canDeleteOfficialTool);
	const deleteResult = canDeleteOfficialTool
		? `<p class="at__result" data-tool-delete-result aria-live="polite"></p>`
		: "";
	// At-a-glance chips (real metadata).
	const glance = glanceChips(tool);

	const maintList = maintainerListMarkup(peopleSummary);
	const complete = completeness(tool);
	// Stryker disable next-line StringLiteral: button() defaults variant to "outline", so "" renders identical markup — equivalent.
	const html = `
	<div class="container page">
		<a class="back" href="/search">${t("tool.backToTools", "← Back to tools")}</a>
		<header class="toolpage__head">
			${toolIcon(tool, "lg")}
			<div class="toolpage__id">
				<h1 class="toolpage__title"${textAttrs(tool.title, tool.titleLanguage)}>${esc(tool.title)}</h1>
				${tool.subtitle ? `<p class="toolpage__subtitle"${textAttrs(tool.subtitle, tool.subtitleLanguage)}>${esc(tool.subtitle)}</p>` : ""}
				<div class="toolpage__by">${t("tool.by", "by")} ${authors}</div>
				${sponsorLine(tool.sponsor)}
				${replacementNote(tool)}
				${provTags ? `<div class="toolpage__prov">${provTags}</div>` : ""}
				${syncPanels}
				${reconciliationNotice}
				<div class="toolpage__glance">${glance}</div>
				<div class="toolpage__row">
					${realBadge}
					${healthScoreChip(evolvedSummary)}
					${maintainerDisclosure(evolvedSummary)}
					<span data-tool-endorsement-slot></span>
					${fitChip(tool)}
					${catalogUpdatedSignal(tool)}
					${repositoryUpdatedSignal(evolvedSummary)}
				</div>
			</div>
			<div class="toolpage__cta">
				${openToolUrl ? button(t("tool.openTool", "Open tool"), { variant: "primary", size: "lg", href: openToolUrl, icon: "external", attrs: 'target="_blank" rel="noopener nofollow"' }) : ""}
				${signedIn() ? favBtn(tool.name, { label: true, cls: "favbtn--btn favbtn--lg" }) : ""}
				<!-- EXPERIMENTAL — Save to a list. Needs: POST/PUT /api/lists/ (Lane B). -->
				${signedIn() ? saveToListControl(tool.name) : ""}
			</div>
		</header>

		<div class="toolpage__grid">
			<div class="toolpage__main">
				<div class="prose"${textAttrs(tool.description, tool.descriptionLanguage)}>${renderMarkdown(tool.description) || `<em>${t("tool.noDescription", "No description provided.")}</em>`}</div>
				<div class="tcard__tags toolpage__tags">${tags}</div>

				<h2 class="toolpage__h2">${t("tool.detailsTitle", "Details")}</h2>
				<div class="detail__meta">
					${metaItem(t("tool.metaType", "Type"), esc(tool.toolType))}
					${metaItem(t("tool.metaLicense", "License"), esc(tool.license))}
					${metaItem(t("tool.metaWorksOn", "Works on"), wikiLabel(tool.forWikis))}
					${metaItem(t("tool.metaInterfaceLanguages", "Interface languages"), langLabel(tool.uiLanguages))}
					${metaItem(t("tool.metaTechnology", "Technology"), (tool.technologyUsed || []).map((/** @type {string} */ item) => esc(item)).join(", "))}
					${metaItem(t("tool.metaAudiences", "Audiences"), (tool.audiences || []).map((/** @type {string} */ item) => esc(item)).join(", "))}
				</div>
				${catalogProvenancePanel(tool.catalogProjection)}

				<div data-related-tools-slot></div>
				<div data-neighborhood-slot></div>
			</div>

				<aside class="toolpage__side">
					<div class="panel">
						<h2 class="panel__title">${t("tool.actionsTitle", "Actions")}</h2>
						<div class="toolpage__actions">${actions || `<span class="meta__v">${t("tool.noLinksProvided", "No links provided")}</span>`}</div>
						<div class="toolpage__sub">
							${managementLinks}
						</div>
						${deleteResult}
					</div>
				<div class="panel">
					<h2 class="panel__title">${t("tool.maintainersTitle", "Maintainer relationships")}</h2>
					<div class="maint-list">${maintList}</div>
				</div>
				<div class="panel">
					<h2 class="panel__title">${t("tool.listingCompleteness", "Listing completeness")}</h2>
					${completenessMeter(complete)}
					${completenessList(complete)}
				</div>
				<div data-evolved-signals-slot></div>
				<div data-media-slot></div>
			</aside>
		</div>
	</div>`;
	function mount() {
		const mountedPath = window.location.pathname;
		const stillCurrentTool = () => window.location.pathname === mountedPath;
		Promise.all([
			backendGetJson(`/v1/tools/${encodeURIComponent(name)}/signals/`).catch(() => null),
			backendGetJson(`/v1/tools/${encodeURIComponent(name)}/media/`).catch(() => null)
		]).then(([signals, media]) => {
			if (!stillCurrentTool()) return;
			const signalsSlot = document.querySelector("[data-evolved-signals-slot]");
			if (signalsSlot) signalsSlot.outerHTML = evolvedSignalsPanel(signals);
			const mediaSlot = document.querySelector("[data-media-slot]");
			const mediaRows = Array.isArray(media?.results) ? media.results : [];
			if (mediaSlot) mediaSlot.outerHTML = mediaPanel(mediaRows);
			bindOptionalToolPanelEvents(name);
		});
		if (signedIn()) {
			serverWrite("POST", `/v1/tools/${encodeURIComponent(name)}/events/`, { eventType: "view" }).catch(() => {});
		}
		document.querySelector("[data-tool-claim]")?.addEventListener("click", () => openClaimDrawer(name));
		afterDetailPrimaryPaint(() => {
			Promise.all([
				listMemberships().catch(() => new Map()),
				import("../lib/core/similarity.js")
					.then(({ getSimilarityIndex, nearestNeighbors }) =>
						getSimilarityIndex().then((simIndex) => nearestNeighbors(resolvedTool, simIndex, 6))
					)
					.catch(() => []),
				import("../lib/core/graph.js")
					.then(({ egoGraph }) =>
						egoGraph(name, 10).then((graph) =>
							// Stryker disable next-line ArrayDeclaration: egoGraph always returns a `nodes` array; the `|| []` fallback is never taken, and the sentinel array's length (1) is still < 3 — equivalent.
							(graph.nodes || []).length >= 3 ? graph : null
						)
					)
					.catch(() => null)
			]).then(([membershipMap, related, ego]) => {
				if (!stillCurrentTool()) return;
				const endorsement = endorsementOf(resolvedTool.name, membershipMap);
				/** @type {any} */ (resolvedTool).endorsement = endorsement;
				const endorsementSlot = document.querySelector("[data-tool-endorsement-slot]");
				if (endorsementSlot) endorsementSlot.innerHTML = endorsementChip(endorsement.count);
				const relatedSlot = document.querySelector("[data-related-tools-slot]");
				if (relatedSlot) relatedSlot.innerHTML = relatedToolsSection(related || []);
				const neighborhoodSlot = document.querySelector("[data-neighborhood-slot]");
				if (neighborhoodSlot) neighborhoodSlot.innerHTML = neighborhoodSection(ego);
				const target = /** @type {HTMLElement | null} */ (document.querySelector("#ego-canvas"));
				if (!target || !ego) return;
				Promise.all([import("../lib/organisms/force-graph.js"), import("../lib/organisms/quickview.js")])
					.then(([{ forceGraph }, { openQuickView }]) => {
						if (!stillCurrentTool() || !target.isConnected) return;
						target.forceGraphHandle = forceGraph(target, ego, { onSelect: openQuickView, height: 320 });
					})
					.catch(() => undefined);
			});
		}, 2200);
		document.querySelector("[data-tool-delete]")?.addEventListener("click", async () => {
			const out = /** @type {HTMLElement | null} */ (document.querySelector("[data-tool-delete-result]"));
			if (out) {
				out.className = "at__result";
				out.textContent = t("tool.publishingToToolhub", "Publishing to official Toolhub…");
			}
			try {
				await officialWrite("DELETE", `/v1/write/tools/${encodeURIComponent(name)}/`);
				clearLocalToolDraft(name);
				clearApiCache();
				navigateTo("/my-tools");
			} catch (error) {
				if (out) {
					out.className = "at__result at__result--err";
					out.textContent = t(
						"tool.officialDeleteFailed",
						"Official Toolhub did not delete the tool: $1",
						backendErrorExplanation(error)
					);
				}
			}
		});
	}
	return { title: t("tool.docTitle", "$1 — Toolhub", tool.title), html, mount };
}

// Tool revision history — live from /api/tools/{name}/revisions/.
/** @param {string} name */
export async function viewToolHistory(name) {
	const [liveT, data] = await Promise.all([
		getTool(name),
		// Stryker disable next-line ObjectLiteral: `{}` is equivalent to `{ results: [] }` because the value is read as `data.results || []`.
		apiGet(`/tools/${encodeURIComponent(name)}/revisions/`, { page_size: "20" }).catch(() => ({ results: [] }))
	]);
	// Local Evolved edits show as the most recent revisions.
	const revs = [...demoRevisionsFor(name), ...(data.results || [])];
	const tool = liveT;
	if (!tool && revs.length === 0) return viewNotFound();
	const title = tool ? tool.title : (revs[0] && revs[0].content_title) || name;
	const rows = revs
		.map((r, i) => {
			const username = (r.user && r.user.username) || "system";
			return `
		<li>${icon("history", "feed__ic")}
			<span class="feed__main">${t("tool.revisionBy", "Revision by")} <strong${dirAttrs(username)}>${esc(username)}</strong> · ${timeTag(r.timestamp)}${r.comment ? ` — <span dir="auto">${esc(r.comment)}</span>` : ""}${i === 0 ? ` <span class="tag">${t("tool.currentTag", "current")}</span>` : ""}</span>
			<span class="feed__when">#${esc(String(r.id))}</span></li>`;
		})
		.join("");
	return {
		title: t("tool.historyDocTitle", "History: $1 — Toolhub", title),
		html: `
		<div class="container page">
			<a class="back" href="${toolHref(name)}">${t("tool.backToName", "← Back to $1", esc(title))}</a>
			<h1 class="page__title">${t("tool.revisionHistoryTitle", "Revision history")}</h1>
			<ul class="feed">${rows || `<li><div class="feed__static">${t("tool.noRevisions", "No revisions recorded.")}</div></li>`}</ul>
		</div>`
	};
}
/** @param {string} name */
export function viewDiffStub(name) {
	const tool = /** @type {Record<string, Tool>} */ (INDEX)[name];
	return prosePage(
		t("tool.revisionDiffTitle", "Revision diff"),
		`
		<p>${t("tool.diffCompareLead", "Compare two revisions of")} <strong>${esc(tool ? tool.title : name)}</strong> ${t("tool.diffCompareTail", "side by side.")}</p>
		<p>${t("tool.diffIntro", "Revision diffs are served from Toolhub's versioning API. In this prototype the\n\t\tdiff viewer is not wired up — see it on the")}
		<a href="https://toolhub.wikimedia.org/" target="_blank" rel="noopener nofollow">${t("tool.liveSite", "live site")}</a>.</p>
		<p><a href="${toolHref(name)}/history">${t("tool.backToHistory", "← Back to history")}</a></p>`
	);
}
