// SPDX-License-Identifier: GPL-3.0-or-later
import { dirAttrs, esc, textAttrs } from "../core/dom.js";
import { t, updatedTimeTag } from "../core/i18n.js";
import { authorAttributionHref, authorHref, personHref, toolHref } from "../core/routing.js";
import { peopleForRole, personForRelationshipLabel, relationshipsForRole } from "../core/relationship-people.js";
import { completeness } from "../core/signals.js";
import { signedIn } from "../core/session.js";
import { toolIcon } from "../atoms/avatar.js";
import { completenessMeter, endorsementChip, fitChip } from "../atoms/badges.js";
import { wikiShort } from "../atoms/labels.js";
import { favBtn } from "../molecules/favbtn.js";
import { healthScoreChip } from "../molecules/tool-health-summary.js";

export const CARD_TAG_LIMIT = 2;
export const CARD_AUTHOR_TEXT_LIMIT = 42;

/** @param {Tool} tool */
function authorNames(tool) {
	const values = Array.isArray(tool.authors) && tool.authors.length > 0 ? tool.authors : [tool.maintainer];
	const seen = new Set();
	return values
		.map((name) => String(name || "").trim())
		.filter((name) => {
			const key = name.toLowerCase();
			if (!name || seen.has(key)) return false;
			seen.add(key);
			return true;
		});
}

/** @param {Tool} tool @param {any} evolvedSummary */
function relationshipPeople(tool, evolvedSummary) {
	const summaryPeople = Array.isArray(evolvedSummary?.maintainer?.people) ? evolvedSummary.maintainer.people : [];
	const accountPerson = tool.accountPerson?.id
		? [{ ...tool.accountPerson, relationships: tool.accountRelationships || [] }]
		: [];
	const byId = new Map();
	for (const person of [...summaryPeople, ...(tool.relationshipPeople || []), ...accountPerson]) {
		if (!person?.id) continue;
		const previous = byId.get(person.id);
		byId.set(person.id, {
			...previous,
			...person,
			relationships: [...(previous?.relationships || []), ...(person.relationships || [])]
		});
	}
	return [...byId.values()];
}

/** @param {Tool} tool @param {string} name @param {any[]} people */
function authorLink(tool, name, people) {
	const person = personForRelationshipLabel(people, name, "author");
	if (person?.id) return personHref(person.id);
	const record = (tool.authorObjs || []).find(
		(author) =>
			String(author?.name || "")
				.trim()
				.toLowerCase() === name.toLowerCase()
	);
	const handle = String(record?.wikiUsername || record?.developerUsername || "").trim();
	return handle ? authorHref(handle) : authorAttributionHref(name);
}

/** @param {string} value */
function characterCount(value) {
	return [...value].length;
}

/** @param {string} value @param {number} limit */
function truncateCharacters(value, limit) {
	const characters = [...value];
	return characters.length <= limit ? value : `${characters.slice(0, Math.max(1, limit - 1)).join("")}…`;
}

/** @param {string[]} names */
function compactAuthorNames(names) {
	const complete = names.join(", ");
	if (characterCount(complete) <= CARD_AUTHOR_TEXT_LIMIT) return complete;
	const visible = [];
	for (const name of names) {
		const candidate = [...visible, name].join(", ");
		const remaining = names.length - visible.length - 1;
		if (characterCount(`${candidate}${remaining > 0 ? ` +${remaining}` : ""}`) > CARD_AUTHOR_TEXT_LIMIT) break;
		visible.push(name);
	}
	const remaining = names.length - visible.length;
	if (visible.length > 0) return `${visible.join(", ")} +${remaining}`;
	const suffix = ` +${Math.max(0, names.length - 1)}`;
	return `${truncateCharacters(names[0], CARD_AUTHOR_TEXT_LIMIT - characterCount(suffix))}${suffix}`;
}

/** @param {any} summary */
function hasConfirmedMaintainer(summary) {
	return (
		String(summary?.maintainerDimension?.status || "") === "verified-maintainer" ||
		Number(summary?.maintainer?.healthCounts?.verifiedPeople || 0) > 0
	);
}

/**
 * @param {Tool} tool
 * @param {any} evolvedSummary
 * @param {string} author
 */
function singleAuthorByline(tool, evolvedSummary, author) {
	const confirmed = hasConfirmedMaintainer(evolvedSummary);
	const maintainer = author || t("toolCard.unknownMaintainer", "Unknown");
	const hasOwner = Boolean(author) && maintainer !== t("toolCard.unknownMaintainer", "Unknown");
	const label = confirmed
		? t("toolCard.maintainerConfirmed", "$1, confirmed maintainer", maintainer)
		: t("toolCard.maintainerUnconfirmed", "$1, maintainer not confirmed yet", maintainer);
	const owner = hasOwner
		? `<a class="tcard__maint-name${confirmed ? " tcard__maint-name--confirmed" : ""}" href="${esc(authorLink(tool, maintainer, relationshipPeople(tool, evolvedSummary)))}"${confirmed ? "" : ` title="${esc(label)}"`} aria-label="${esc(label)}"><span class="tcard__maint-text"${dirAttrs(maintainer)}>${esc(maintainer)}</span></a>`
		: `<span class="tcard__maint-name" title="${esc(label)}" aria-label="${esc(label)}"><span class="tcard__maint-text"${dirAttrs(maintainer)}>${esc(maintainer)}</span></span>`;
	return `<div class="tcard__maint">${t("toolCard.by", "by")} ${owner}</div>`;
}

/** @param {Tool} tool @param {any} evolvedSummary */
function authorByline(tool, evolvedSummary) {
	const names = authorNames(tool);
	if (names.length <= 1) return singleAuthorByline(tool, evolvedSummary, names[0] || "");
	const people = relationshipPeople(tool, evolvedSummary);
	const count = names.length;
	const compact = compactAuthorNames(names);
	const links = names
		.map((name) => `<li><a href="${esc(authorLink(tool, name, people))}"${dirAttrs(name)}>${esc(name)}</a></li>`)
		.join("");
	return `<details class="tcard__authors health-popover" data-route-disclosure="tool-authors:${esc(tool.name)}">
		<summary class="tcard__authors-summary" aria-label="${esc(t("toolCard.showAllAuthors", "Show all $1 authors", count))}"><span>${t("toolCard.by", "by")} <span class="tcard__authors-text"${dirAttrs(compact)}>${esc(compact)}</span></span></summary>
		<div class="tcard__authors-panel health-popover__panel"><strong>${t("toolCard.authors", "Authors")}</strong><ul role="list">${links}</ul></div>
	</details>`;
}

/** @param {Tool} tool @param {any} evolvedSummary */
function maintainerByline(tool, evolvedSummary) {
	const people = relationshipPeople(tool, evolvedSummary);
	const authorIds = new Set(
		authorNames(tool)
			.map((name) => personForRelationshipLabel(people, name, "author")?.id)
			.filter(Boolean)
	);
	const maintainers = peopleForRole(people, "maintainer").filter((person) => !authorIds.has(person.id));
	if (maintainers.length === 0) return "";
	const visible = maintainers.slice(0, 2);
	const links = visible
		.map((person) => {
			const name = String(person.displayName || t("toolCard.unknownMaintainer", "Unknown"));
			const confirmed = relationshipsForRole(person, "maintainer").some(
				(/** @type {any} */ relationship) => relationship?.status === "verified" || relationship?.isVerified
			);
			return `<a class="tcard__maint-name${confirmed ? " tcard__maint-name--confirmed" : ""}" href="${esc(personHref(person.id))}"><span class="tcard__maint-text"${dirAttrs(name)}>${esc(name)}</span></a>`;
		})
		.join(", ");
	const remaining = maintainers.length - visible.length;
	return `<div class="tcard__maint">${t("toolCard.maintainedBy", "Maintained by")} ${links}${remaining > 0 ? ` <span class="tcard__maint-more">+${remaining}</span>` : ""}</div>`;
}

/** @param {any} summary */
function cardHealthScore(summary) {
	const score = Number(summary?.health?.score);
	const unknown = !summary?.health || String(summary.health.grade || "") === "unknown" || !Number.isFinite(score);
	if (unknown) {
		const label = t("toolCard.healthUnknown", "Health score unknown");
		return `<span class="tcard__health-dash" title="${esc(label)}" aria-label="${esc(label)}">—</span>`;
	}
	return healthScoreChip(summary, { compact: true });
}

/** @param {any} summary */
function healthCornerClass(summary) {
	const grade = String(summary?.health?.grade || "unknown");
	if (grade === "strong") return " tcard--health-legendary";
	if (grade === "good") return " tcard--health-great";
	if (grade === "needs-attention") return " tcard--health-needs-attention";
	if (grade === "unknown" || !Number.isFinite(Number(summary?.health?.score))) return " tcard--health-unknown";
	return " tcard--health-risk";
}

/**
 * @param {Tool} tool
 * @param {{ rank?: number; popular?: boolean }} [opts]
 * @returns {string}
 */
export function toolCard(tool, opts = {}) {
	// (3) Tags: 2 + "+N" overflow chip so every card is the same height.
	const allk = tool.keywords || [];
	const tags =
		allk
			.slice(0, CARD_TAG_LIMIT)
			.map(
				(k) =>
					`<a class="tag" href="/search?keywords__term=${encodeURIComponent(k)}"${dirAttrs(k)}>${esc(k)}</a>`
			)
			.join("") +
		(allk.length > CARD_TAG_LIMIT ? `<span class="tag tag--more">+${allk.length - CARD_TAG_LIMIT}</span>` : "");
	const rank = opts.rank ? `<span class="rankbadge" aria-hidden="true">${opts.rank}</span>` : "";
	// (1) Top-right shows ONLY the real deprecated/experimental flags (genuine
	// warnings). The old assumed "Healthy" pill is gone (it had no real data).
	let flag = "";
	if (tool.deprecated) {
		flag = `<span class="tcard__flag status status--red"><span class="dot dot--red"></span>${t("toolCard.deprecated", "Deprecated")}</span>`;
	} else if (tool.experimental) {
		flag = `<span class="tcard__flag status status--yellow"><span class="dot dot--yellow"></span>${t("toolCard.experimental", "Experimental")}</span>`;
	}
	// (1,2,4) Calm footer-left: real tool type + "works on" facet (no colour noise).
	const meta = [tool.toolType && esc(tool.toolType), esc(wikiShort(tool.forWikis))].filter(Boolean).join(" · ");
	const topLeft = `<span class="tcard__meta"${dirAttrs(meta)}>${meta}</span>`;
	const complete = completeness(tool);
	const completeClass = complete.total && complete.filled === complete.total ? " tcard--complete" : "";
	// `endorsement` (an {count,lists} object) is attached at runtime by signals.js but
	// isn't on the ambient Tool type — narrow via a structural cast.
	const endorsement = /** @type {{ endorsement?: { count?: number } }} */ (tool).endorsement;
	const evolvedSummary = /** @type {{ evolvedSummary?: any }} */ (tool).evolvedSummary;
	const trustLine = fitChip(tool);
	const metricLine =
		completenessMeter(complete, { details: true, numeric: true }) +
		cardHealthScore(evolvedSummary) +
		endorsementChip(endorsement && endorsement.count, { compact: true });
	const signalLine = `${trustLine ? `<div class="tcard__signal-row tcard__signal-row--trust">${trustLine}</div>` : ""}<div class="tcard__signal-row tcard__signal-row--metrics">${metricLine}</div>`;
	const favorite = signedIn() ? favBtn(tool.name, { cls: "favbtn--sm favbtn--bare" }) : "";
	const topRight = `${flag}${updatedTimeTag(tool.modified, "tcard__when")}${favorite}`;
	const bylines = [authorByline(tool, evolvedSummary), maintainerByline(tool, evolvedSummary)]
		.filter(Boolean)
		.join("\n\t\t\t\t");
	return `
	<article class="tcard${opts.popular ? " tcard--popular" : ""}${completeClass}${healthCornerClass(evolvedSummary)}" data-tool="${esc(tool.name)}">
		<div class="tcard__topline">${topLeft}<span class="tcard__topmeta">${topRight}</span></div>
		<div class="tcard__head">
			${rank}${toolIcon(tool)}
			<div class="tcard__heading">
				<a class="tcard__title" href="${esc(toolHref(tool.name))}"${textAttrs(tool.title, tool.titleLanguage)}>${esc(tool.title)}</a>
				${bylines}
			</div>
		</div>
		<p class="tcard__desc"${textAttrs(tool.description, tool.descriptionLanguage)}>${esc(tool.description)}</p>
		<div class="tcard__tags">${tags}</div>
		<div class="tcard__signals">${signalLine}</div>
	</article>`;
}
