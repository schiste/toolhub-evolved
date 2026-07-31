// SPDX-License-Identifier: GPL-3.0-or-later
import { dirAttrs, esc, textAttrs } from "../core/dom.js";
import { t, updatedTimeTag } from "../core/i18n.js";
import { authorHref, toolHref } from "../core/routing.js";
import { completeness } from "../core/signals.js";
import { signedIn } from "../core/session.js";
import { toolIcon } from "../atoms/avatar.js";
import { completenessMeter, endorsementChip, fitChip } from "../atoms/badges.js";
import { icon } from "../atoms/icon.js";
import { wikiShort } from "../atoms/labels.js";
import { favBtn } from "../molecules/favbtn.js";
import { healthScoreChip } from "../molecules/tool-health-summary.js";

export const CARD_TAG_LIMIT = 2;

/** @param {any} summary */
function hasConfirmedMaintainer(summary) {
	return (
		String(summary?.maintainerDimension?.status || "") === "verified-maintainer" ||
		Number(summary?.maintainer?.counts?.verifiedMaintainers || 0) > 0
	);
}

/**
 * @param {Tool} tool
 * @param {any} evolvedSummary
 */
function maintainerByline(tool, evolvedSummary) {
	const confirmed = hasConfirmedMaintainer(evolvedSummary);
	const maintainer = tool.maintainer || t("toolCard.unknownMaintainer", "Unknown");
	const hasOwner = Boolean(tool.maintainer) && maintainer !== t("toolCard.unknownMaintainer", "Unknown");
	const label = confirmed
		? t("toolCard.maintainerConfirmed", "{name}, confirmed maintainer", { name: maintainer })
		: t("toolCard.maintainerUnconfirmed", "{name}, maintainer not confirmed yet", { name: maintainer });
	const owner = hasOwner
		? `<a class="tcard__maint-name${confirmed ? " tcard__maint-name--confirmed" : ""}" href="${esc(authorHref(maintainer))}" title="${esc(label)}" aria-label="${esc(label)}"><span class="tcard__maint-text"${dirAttrs(maintainer)}>${esc(maintainer)}</span>${confirmed ? `<span class="tcard__maint-check" aria-hidden="true">${icon("check")}</span>` : ""}</a>`
		: `<span class="tcard__maint-name" title="${esc(label)}" aria-label="${esc(label)}"><span class="tcard__maint-text"${dirAttrs(maintainer)}>${esc(maintainer)}</span></span>`;
	return `<div class="tcard__maint">${t("toolCard.by", "by")} ${owner}</div>`;
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
	return `
	<article class="tcard${opts.popular ? " tcard--popular" : ""}${completeClass}${healthCornerClass(evolvedSummary)}" data-tool="${esc(tool.name)}">
		<div class="tcard__topline">${topLeft}<span class="tcard__topmeta">${topRight}</span></div>
		<div class="tcard__head">
			${rank}${toolIcon(tool)}
			<div class="tcard__heading">
				<a class="tcard__title" href="${esc(toolHref(tool.name))}"${textAttrs(tool.title, tool.titleLanguage)}>${esc(tool.title)}</a>
				${maintainerByline(tool, evolvedSummary)}
			</div>
		</div>
		<p class="tcard__desc"${textAttrs(tool.description, tool.descriptionLanguage)}>${esc(tool.description)}</p>
		<div class="tcard__tags">${tags}</div>
		<div class="tcard__signals">${signalLine}</div>
	</article>`;
}
