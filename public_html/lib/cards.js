// SPDX-License-Identifier: GPL-3.0-or-later
import { $$, avatar, dirAttrs, esc, toolIcon } from "./dom.js";
import { countLabel, updatedTimeTag } from "./i18n.js";
import { signedIn } from "./account.js";
import { demoLists, isFav } from "./store.js";
import { popularityBadge, wikiShort } from "./badges.js";
import { listHref } from "./nav.js";

export const CARD_TAG_LIMIT = 2;
export function favBtn(name, opts) {
	opts = opts || {};
	const on = isFav(name);
	const txt = opts.label ? `<span class="favbtn__t">${on ? "Saved" : "Save"}</span>` : "";
	return `<button class="favbtn${on ? " is-on" : ""}${opts.cls ? " " + opts.cls : ""}" type="button" data-fav="${esc(name)}" aria-pressed="${on}" aria-label="${on ? "Remove from favorites" : "Save to favorites"}"><span class="favbtn__ic" aria-hidden="true">${on ? "★" : "☆"}</span>${txt}</button>`;
}
// Reflect a toggled favorite on its button(s) in place (no full re-render).
export function syncFavButtons(name, on) {
	$$("[data-fav]").filter((b) => b.getAttribute("data-fav") === name).forEach((b) => {
		b.classList.toggle("is-on", on);
		b.setAttribute("aria-pressed", String(on));
		b.setAttribute("aria-label", on ? "Remove from favorites" : "Save to favorites");
		const ic = b.querySelector(".favbtn__ic"); if (ic) ic.textContent = on ? "★" : "☆";
		const t = b.querySelector(".favbtn__t"); if (t) t.textContent = on ? "Saved" : "Save";
	});
}
export function listCardData(l) { return { id: l.id, title: l.title || "Untitled list", description: l.description || "", toolCount: (l.tools || []).length, demo: true }; }
// "Save to a list" control: a native <details> menu of the user's demo lists.
export function saveToListControl(name) {
	const items = demoLists().map((l) => {
		const inIt = (l.tools || []).indexOf(name) !== -1;
		return `<button class="savemenu__item${inIt ? " is-on" : ""}" type="button" data-listadd="${esc(l.id)}" data-tn="${esc(name)}" aria-pressed="${inIt}"><span class="savemenu__mark" aria-hidden="true">${inIt ? "✓" : "＋"}</span> <span${dirAttrs(l.title)}>${esc(l.title || "Untitled list")}</span></button>`;
	}).join("") || '<p class="savemenu__empty">No lists yet.</p>';
	return `<details class="savemenu">
		<summary class="btn btn--outline"><span aria-hidden="true">🔖</span> Save to a list</summary>
		<div class="savemenu__pop">${items}<a class="savemenu__new" href="#/lists/create"><span aria-hidden="true">＋</span> New list…</a></div>
	</details>`;
}

/* ------------------------------------------------------------ card markup */
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
	// The whole card opens the quick-view; (5) a hover cue signals the peek.
	return `
	<article class="tcard${opts.popular ? " tcard--popular" : ""}" data-tool="${esc(t.name)}" role="button" tabindex="0" aria-label="Quick look: ${esc(t.title)}">
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
		<div class="tcard__foot">${footLeft}<span class="tcard__footr">${updatedTimeTag(t.modified, "tcard__when")}${signedIn() ? favBtn(t.name, { cls: "favbtn--sm" }) : ""}</span></div>
		<span class="tcard__hint" aria-hidden="true">🔍</span>
	</article>`;
}
export function listCard(l) {
	const count = countLabel(l.toolCount, "tool", "tools");
	return `
	<a class="lcard" href="${listHref(l.id)}" aria-label="${esc(l.title)} list, ${esc(count)}">
		${avatar(l.title)}
		<div class="lcard__body">
			<div class="lcard__title"${dirAttrs(l.title)}>${esc(l.title)} <span class="lcard__count">${esc(count)}</span>${l.demo ? ' <span class="exp-badge">Demo</span>' : ""}</div>
			<div class="lcard__desc"${dirAttrs(l.description)}>${esc(l.description)}</div>
		</div>
	</a>`;
}
export function grid(cls, items, render) {
	// a11y: a grid of cards is a list (1.3.1). role="list" keeps the semantics
	// even though list-style:none is applied (Safari drops it otherwise).
	return `<ul class="card-grid ${cls}" role="list">${items.map((it, i) => `<li>${render(it, i)}</li>`).join("")}</ul>`;
}
