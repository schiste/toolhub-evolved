// SPDX-License-Identifier: GPL-3.0-or-later
import { dirAttrs, esc, textAttrs } from "../core/dom.js";
import { t, updatedTimeTag } from "../core/i18n.js";
import { completeness } from "../core/signals.js";
import { signedIn } from "../core/session.js";
import { toolIcon } from "../atoms/avatar.js";
import { completenessMeter, endorsementChip, fitChip } from "../atoms/badges.js";
import { icon } from "../atoms/icon.js";
import { wikiShort } from "../atoms/labels.js";
import { favBtn } from "../molecules/favbtn.js";

export const CARD_TAG_LIMIT = 2;
const QUICK_VIEW_BUTTON_STYLE =
	"appearance: none; border: 0; background: none; padding: 0; color: inherit; font-family: inherit; text-align: start; cursor: pointer;";

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
			.map((k) => `<span class="tag" data-q="${esc(k)}"${dirAttrs(k)}>${esc(k)}</span>`)
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
	const footLeft = `<span class="tcard__meta"${dirAttrs(meta)}>${meta}</span>`;
	const complete = completeness(tool);
	const completeClass = complete.total && complete.filled === complete.total ? " tcard--complete" : "";
	// `endorsement` (an {count,lists} object) is attached at runtime by signals.js but
	// isn't on the ambient Tool type — narrow via a structural cast.
	const endorsement = /** @type {{ endorsement?: { count?: number } }} */ (tool).endorsement;
	const signalLine = endorsementChip(endorsement && endorsement.count) + completenessMeter(complete) + fitChip(tool);
	// The whole card opens the quick-view; (5) a hover cue signals the peek.
	return `
	<article class="tcard${opts.popular ? " tcard--popular" : ""}${completeClass}" data-tool="${esc(tool.name)}">
		${flag}
		<div class="tcard__head">
			${rank}${toolIcon(tool)}
			<div class="tcard__heading">
				<button class="tcard__title" type="button" data-tool="${esc(tool.name)}" aria-label="${t("toolCard.quickLook", "Quick look: {title}", { title: esc(tool.title) })}" style="${QUICK_VIEW_BUTTON_STYLE}"${textAttrs(tool.title, tool.titleLanguage)}>${esc(tool.title)}</button>
				<div class="tcard__maint">${t("toolCard.by", "by")} <span${dirAttrs(tool.maintainer)}>${esc(tool.maintainer)}</span></div>
			</div>
		</div>
		<p class="tcard__desc"${textAttrs(tool.description, tool.descriptionLanguage)}>${esc(tool.description)}</p>
		<div class="tcard__tags">${tags}</div>
		<div class="tcard__signals">${signalLine}</div>
		<div class="tcard__foot">${footLeft}<span class="tcard__footr">${updatedTimeTag(tool.modified, "tcard__when")}${signedIn() ? favBtn(tool.name, { cls: "favbtn--sm" }) : ""}</span></div>
		${icon("search", "tcard__hint")}
	</article>`;
}
