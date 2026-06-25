// SPDX-License-Identifier: GPL-3.0-or-later
import { dirAttrs, esc } from "../core/dom.js";
import { updatedTimeTag } from "../core/i18n.js";
import { completeness } from "../core/signals.js";
import { signedIn } from "../core/session.js";
import { toolIcon } from "../atoms/avatar.js";
import { completenessMeter, endorsementChip, fitChip, popularityBadge } from "../atoms/badges.js";
import { icon } from "../atoms/icon.js";
import { wikiShort } from "../atoms/labels.js";
import { favBtn } from "../molecules/favbtn.js";

export const CARD_TAG_LIMIT = 2;
export function toolCard(t, opts) {
	opts = opts || {};
	// (3) Tags: 2 + "+N" overflow chip so every card is the same height.
	const allk = t.keywords || [];
	const tags = allk.slice(0, CARD_TAG_LIMIT).map((k) => `<span class="tag" data-q="${esc(k)}"${dirAttrs(k)}>${esc(k)}</span>`).join("")
		+ (allk.length > CARD_TAG_LIMIT ? `<span class="tag tag--more">+${allk.length - CARD_TAG_LIMIT}</span>` : "");
	const rank = opts.rank ? `<span class="rankbadge" aria-hidden="true">${opts.rank}</span>` : "";
	// (1) Top-right shows ONLY the real deprecated/experimental flags (genuine
	// warnings). The old assumed "Healthy" pill is gone (it had no real data).
	let flag = "";
	if (t.deprecated) flag = `<span class="tcard__flag status status--red"><span class="dot dot--red"></span>Deprecated</span>`;
	else if (t.experimental) flag = `<span class="tcard__flag status status--yellow"><span class="dot dot--yellow"></span>Experimental</span>`;
	// (1,2,4) Calm footer-left: real tool type + "works on" facet (no colour noise).
	const meta = [t.toolType && esc(t.toolType), esc(wikiShort(t.forWikis))].filter(Boolean).join(" · ");
	// EXPERIMENTAL — popularity (only the home "Popular" grid; shown when toggle on).
	const footLeft = opts.popular
		? popularityBadge(t)
		: `<span class="tcard__meta"${dirAttrs(meta)}>${meta}</span>`;
	const complete = completeness(t);
	const completeClass = complete.total && complete.filled === complete.total ? " tcard--complete" : "";
	const signalLine = endorsementChip(t.endorsement && t.endorsement.count) + completenessMeter(complete) + fitChip(t);
	// The whole card opens the quick-view; (5) a hover cue signals the peek.
	return `
	<article class="tcard${opts.popular ? " tcard--popular" : ""}${completeClass}" data-tool="${esc(t.name)}" role="button" tabindex="0" aria-label="Quick look: ${esc(t.title)}">
		${flag}
		<div class="tcard__head">
			${rank}${toolIcon(t)}
			<div class="tcard__heading">
				<div class="tcard__title"${dirAttrs(t.title)}>${esc(t.title)}</div>
				<div class="tcard__maint">by <span${dirAttrs(t.maintainer)}>${esc(t.maintainer)}</span></div>
			</div>
		</div>
		<p class="tcard__desc"${dirAttrs(t.description)}>${esc(t.description)}</p>
		<div class="tcard__tags">${tags}</div>
		<div class="tcard__signals">${signalLine}</div>
		<div class="tcard__foot">${footLeft}<span class="tcard__footr">${updatedTimeTag(t.modified, "tcard__when")}${signedIn() ? favBtn(t.name, { cls: "favbtn--sm" }) : ""}</span></div>
		${icon("search", "tcard__hint")}
	</article>`;
}
