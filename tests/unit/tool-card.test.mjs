// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test } from "vitest";
import { toolCard, CARD_TAG_LIMIT } from "../../public_html/lib/organisms/tool-card.js";
import { dirAttrs, esc } from "../../public_html/lib/core/dom.js";
import { updatedTimeTag } from "../../public_html/lib/core/i18n.js";
import { completeness } from "../../public_html/lib/core/signals.js";
import { applyExp, setAuth, signedIn } from "../../public_html/lib/core/session.js";
import { toolIcon } from "../../public_html/lib/atoms/avatar.js";
import { completenessMeter, endorsementChip, fitChip, popularityBadge } from "../../public_html/lib/atoms/badges.js";
import { icon } from "../../public_html/lib/atoms/icon.js";
import { wikiShort } from "../../public_html/lib/atoms/labels.js";
import { favBtn } from "../../public_html/lib/molecules/favbtn.js";

// In-file constants are hardcoded here (NOT imported) so a mutation to the
// source constant is not masked by the oracle reading the same mutated value.
const LIMIT = 2;
const BTN_STYLE =
	"appearance: none; border: 0; background: none; padding: 0; color: inherit; font-family: inherit; text-align: start; cursor: pointer;";

/**
 * Pristine oracle: re-derives the exact HTML toolCard() must produce, composing
 * the same (un-mutated) helpers. Any source mutation diverges from this.
 * @param {any} t
 * @param {any} [opts]
 */
function oracle(t, opts = {}) {
	const allk = t.keywords || [];
	const tags =
		allk
			.slice(0, LIMIT)
			.map((k) => `<span class="tag" data-q="${esc(k)}"${dirAttrs(k)}>${esc(k)}</span>`)
			.join("") + (allk.length > LIMIT ? `<span class="tag tag--more">+${allk.length - LIMIT}</span>` : "");
	const rank = opts.rank ? `<span class="rankbadge" aria-hidden="true">${opts.rank}</span>` : "";
	let flag = "";
	if (t.deprecated) {
		flag = `<span class="tcard__flag status status--red"><span class="dot dot--red"></span>Deprecated</span>`;
	} else if (t.experimental) {
		flag = `<span class="tcard__flag status status--yellow"><span class="dot dot--yellow"></span>Experimental</span>`;
	}
	const meta = [t.toolType && esc(t.toolType), esc(wikiShort(t.forWikis))].filter(Boolean).join(" · ");
	const footLeft = opts.popular ? popularityBadge(t) : `<span class="tcard__meta"${dirAttrs(meta)}>${meta}</span>`;
	const complete = completeness(t);
	const completeClass = complete.total && complete.filled === complete.total ? " tcard--complete" : "";
	const endorsement = t.endorsement;
	const signalLine = endorsementChip(endorsement && endorsement.count) + completenessMeter(complete) + fitChip(t);
	return `\n\t<article class="tcard${opts.popular ? " tcard--popular" : ""}${completeClass}" data-tool="${esc(t.name)}">\n\t\t${flag}\n\t\t<div class="tcard__head">\n\t\t\t${rank}${toolIcon(t)}\n\t\t\t<div class="tcard__heading">\n\t\t\t\t<button class="tcard__title" type="button" data-tool="${esc(t.name)}" aria-label="Quick look: ${esc(t.title)}" style="${BTN_STYLE}"${dirAttrs(t.title)}>${esc(t.title)}</button>\n\t\t\t\t<div class="tcard__maint">by <span${dirAttrs(t.maintainer)}>${esc(t.maintainer)}</span></div>\n\t\t\t</div>\n\t\t</div>\n\t\t<p class="tcard__desc"${dirAttrs(t.description)}>${esc(t.description)}</p>\n\t\t<div class="tcard__tags">${tags}</div>\n\t\t<div class="tcard__signals">${signalLine}</div>\n\t\t<div class="tcard__foot">${footLeft}<span class="tcard__footr">${updatedTimeTag(t.modified, "tcard__when")}${signedIn() ? favBtn(t.name, { cls: "favbtn--sm" }) : ""}</span></div>\n\t\t${icon("search", "tcard__hint")}\n\t</article>`;
}

const base = {
	name: "my tool",
	title: "My <Tool>",
	maintainer: "Jane & Co",
	description: "A *great* tool",
	keywords: ["alpha", "beta", "gamma", "delta"],
	toolType: "web app",
	forWikis: "*",
	modified: "2026-06-01T00:00:00Z"
};

// A listing where every completeness field is filled (filled === total).
const complete = {
	name: "complete",
	title: "Complete",
	maintainer: "M",
	description: "A description that is comfortably longer than thirty chars.",
	keywords: ["k"],
	url: "https://x.org",
	repository: "https://git.example/x",
	license: "MIT",
	audiences: ["editors"],
	userDocs: "https://docs",
	icon: "https://icon.png",
	bugtracker: "https://bugs",
	toolType: "bot",
	forWikis: "enwiki",
	modified: "2026-06-01T00:00:00Z"
};

function check(label, t, opts) {
	assert.equal(toolCard(t, opts), oracle(t, opts), label);
}

test("toolCard exact HTML across every branch (signed in)", () => {
	applyExp(true);
	setAuth(true);
	check("rank + >limit keywords", base, { rank: 3 });
	check("popular", base, { popular: true, rank: 2 });
	check("no rank, no popular", base, {});
	check("deprecated flag", { ...base, deprecated: true }, {});
	check("experimental flag", { ...base, experimental: true }, {});
	check("deprecated wins over experimental", { ...base, deprecated: true, experimental: true }, {});
	check("exactly limit keywords (no +N)", { ...base, keywords: ["a", "b"] }, {});
	check("one keyword", { ...base, keywords: ["solo"] }, {});
	check("zero keywords", { ...base, keywords: [] }, {});
	check("missing keywords (|| [])", { ...base, keywords: undefined }, {});
	check("empty toolType drops meta segment", { ...base, toolType: "", forWikis: "enwiki" }, {});
	// toolType with markup pins `t.toolType && esc(t.toolType)` (|| would leak it unescaped).
	check("toolType is escaped", { ...base, toolType: "a<b>&'\"", forWikis: "enwiki" }, {});
	check("endorsement attached", { ...base, endorsement: { count: 5 } }, {});
	check("complete listing -> tcard--complete", complete, {});
	check("complete + popular", complete, { popular: true });
});

test("toolCard favBtn omitted when signed out / exp off", () => {
	applyExp(true);
	setAuth(false);
	check("signed out: no favBtn", base, { rank: 1 });
	applyExp(false);
	check("exp off: no favBtn", base, {});
	applyExp(true);
	setAuth(true);
});

test("CARD_TAG_LIMIT export value", () => {
	assert.equal(CARD_TAG_LIMIT, 2);
});
