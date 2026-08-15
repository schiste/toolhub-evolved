// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test } from "vitest";
import { toolCard, CARD_AUTHOR_TEXT_LIMIT, CARD_TAG_LIMIT } from "../../public_html/lib/organisms/tool-card.js";
import { dirAttrs, esc } from "../../public_html/lib/core/dom.js";
import { updatedTimeTag } from "../../public_html/lib/core/i18n.js";
import { completeness } from "../../public_html/lib/core/signals.js";
import { applyExp, setServerUser, signedIn } from "../../public_html/lib/core/session.js";
import { toolIcon } from "../../public_html/lib/atoms/avatar.js";
import { completenessMeter, endorsementChip, fitChip } from "../../public_html/lib/atoms/badges.js";
import { wikiShort } from "../../public_html/lib/atoms/labels.js";
import { favBtn } from "../../public_html/lib/molecules/favbtn.js";
import { healthScoreChip } from "../../public_html/lib/molecules/tool-health-summary.js";
import { legacyToolCardSnapshot } from "./tool-card-snapshot.mjs";
import { authorHref } from "../../public_html/lib/core/routing.js";

// In-file constants are hardcoded here (NOT imported) so a mutation to the
// source constant is not masked by the oracle reading the same mutated value.
const LIMIT = 2;
const BTN_STYLE =
	"appearance: none; border: 0; background: none; padding: 0; color: inherit; font-family: inherit; text-align: start; cursor: pointer;";
/** @param {any} summary */
function hasConfirmedMaintainer(summary) {
	return (
		String(summary?.maintainerDimension?.status || "") === "verified-maintainer" ||
		Number(summary?.maintainer?.counts?.verifiedMaintainers || 0) > 0
	);
}

/** @param {any} t @param {any} evolvedSummary */
function maintainerByline(t, evolvedSummary) {
	const confirmed = hasConfirmedMaintainer(evolvedSummary);
	const maintainer = t.maintainer || "Unknown";
	const label = confirmed ? `${maintainer}, confirmed maintainer` : `${maintainer}, maintainer not confirmed yet`;
	const known = Boolean(t.maintainer) && maintainer !== "Unknown";
	const owner = known
		? `<a class="tcard__maint-name${confirmed ? " tcard__maint-name--confirmed" : ""}" href="${esc(authorHref(maintainer))}"${confirmed ? "" : ` title="${esc(label)}"`} aria-label="${esc(label)}"><span class="tcard__maint-text"${dirAttrs(maintainer)}>${esc(maintainer)}</span></a>`
		: `<span class="tcard__maint-name" title="${esc(label)}" aria-label="${esc(label)}"><span class="tcard__maint-text"${dirAttrs(maintainer)}>${esc(maintainer)}</span></span>`;
	return `<div class="tcard__maint">by ${owner}</div>`;
}

function cardHealthScore(summary) {
	const score = Number(summary?.health?.score);
	const unknown = !summary?.health || String(summary.health.grade || "") === "unknown" || !Number.isFinite(score);
	if (unknown) {
		return '<span class="tcard__health-dash" title="Health score unknown" aria-label="Health score unknown">—</span>';
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
			.map(
				(k) =>
					`<a class="tag" href="/search?keywords__term=${encodeURIComponent(k)}"${dirAttrs(k)}>${esc(k)}</a>`
			)
			.join("") + (allk.length > LIMIT ? `<span class="tag tag--more">+${allk.length - LIMIT}</span>` : "");
	const rank = opts.rank ? `<span class="rankbadge" aria-hidden="true">${opts.rank}</span>` : "";
	let flag = "";
	if (t.deprecated) {
		flag = `<span class="tcard__flag status status--red"><span class="dot dot--red"></span>Deprecated</span>`;
	} else if (t.experimental) {
		flag = `<span class="tcard__flag status status--yellow"><span class="dot dot--yellow"></span>Experimental</span>`;
	}
	const meta = [t.toolType && esc(t.toolType), esc(wikiShort(t.forWikis))].filter(Boolean).join(" · ");
	const topLeft = `<span class="tcard__meta"${dirAttrs(meta)}>${meta}</span>`;
	const complete = completeness(t);
	const completeClass = complete.total && complete.filled === complete.total ? " tcard--complete" : "";
	const endorsement = t.endorsement;
	const evolvedSummary = t.evolvedSummary;
	const trustLine = fitChip(t);
	const metricLine =
		completenessMeter(complete, { details: true, numeric: true }) +
		cardHealthScore(evolvedSummary) +
		endorsementChip(endorsement && endorsement.count, { compact: true });
	const signalLine = `${trustLine ? `<div class="tcard__signal-row tcard__signal-row--trust">${trustLine}</div>` : ""}<div class="tcard__signal-row tcard__signal-row--metrics">${metricLine}</div>`;
	const favorite = signedIn() ? favBtn(t.name, { cls: "favbtn--sm favbtn--bare" }) : "";
	const topRight = `${flag}${updatedTimeTag(t.modified, "tcard__when")}${favorite}`;
	return `\n\t<article class="tcard${opts.popular ? " tcard--popular" : ""}${completeClass}${healthCornerClass(evolvedSummary)}" data-tool="${esc(t.name)}">\n\t\t<div class="tcard__topline">${topLeft}<span class="tcard__topmeta">${topRight}</span></div>\n\t\t<div class="tcard__head">\n\t\t\t${rank}${toolIcon(t)}\n\t\t\t<div class="tcard__heading">\n\t\t\t\t<button class="tcard__title" type="button" data-tool="${esc(t.name)}" aria-label="Quick look: ${esc(t.title)}" style="${BTN_STYLE}"${dirAttrs(t.title)}>${esc(t.title)}</button>\n\t\t\t\t${maintainerByline(t, evolvedSummary)}\n\t\t\t</div>\n\t\t</div>\n\t\t<p class="tcard__desc"${dirAttrs(t.description)}>${esc(t.description)}</p>\n\t\t<div class="tcard__tags">${tags}</div>\n\t\t<div class="tcard__signals">${signalLine}</div>\n\t</article>`;
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
	assert.equal(legacyToolCardSnapshot(toolCard(t, opts)), legacyToolCardSnapshot(oracle(t, opts)), label);
}

test("toolCard exact HTML across every branch (signed in)", () => {
	applyExp(true);
	setServerUser("Grace Hopper");
	check("rank + >limit keywords", base, { rank: 3 });
	check("legacy popular option only adds the compatibility card class", base, { popular: true, rank: 2 });
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
	setServerUser(null);
	check("signed out: no favBtn", base, { rank: 1 });
	applyExp(false);
	check("exp off: no favBtn", base, {});
	applyExp(true);
	setServerUser(null);
});

test("toolCard adds per-field lang attributes when the tool record exposes them", () => {
	applyExp(true);
	setServerUser(null);
	const html = toolCard({ ...base, titleLanguage: "fr", descriptionLanguage: "fr" });
	assert.ok(html.includes('href="/tools/my%20tool" dir="auto" lang="fr">My &lt;Tool&gt;</a>'));
	assert.ok(html.includes('<p class="tcard__desc" dir="auto" lang="fr">A *great* tool</p>'));
});

test("toolCard links tools and tags but leaves unresolved owner labels as text", () => {
	const html = toolCard(base);
	assert.ok(html.includes('class="tcard__title" href="/tools/my%20tool"'));
	assert.ok(html.includes('<span class="tcard__maint-name"'));
	assert.ok(!html.includes("/by/Jane%20%26%20Co"));
	assert.ok(html.includes('class="tag" href="/search?keywords__term=alpha"'));
});

test("toolCard discloses every linked author without overflowing the byline", () => {
	const html = toolCard({
		...base,
		authors: ["Ada Lovelace", "Grace Hopper", "Katherine Johnson with an exceptionally long display name"]
	});
	assert.ok(
		html.includes('<details class="tcard__authors health-popover" data-route-disclosure="tool-authors:my tool">')
	);
	assert.ok(html.includes('aria-label="Show all 3 authors"'));
	assert.ok(html.includes('<span class="tcard__authors-text" dir="auto">Ada Lovelace, Grace Hopper +1</span>'));
	assert.ok(html.includes('<li><span dir="auto">Ada Lovelace</span></li>'));
	assert.ok(html.includes('<li><span dir="auto">Grace Hopper</span></li>'));
	assert.ok(
		html.includes('<li><span dir="auto">Katherine Johnson with an exceptionally long display name</span></li>')
	);
	assert.ok(!html.includes("/by/"));
});

test("toolCard keeps unresolved authors as text and removes duplicate labels", () => {
	const single = toolCard({ ...base, authors: ["Ada Lovelace"] });
	assert.ok(!single.includes('class="tcard__authors"'));
	assert.ok(single.includes('class="tcard__maint-name"'));
	assert.ok(!single.includes("/by/"));

	const deduplicated = toolCard({ ...base, authors: ["Ada Lovelace", "ada lovelace", "Grace Hopper"] });
	assert.ok(deduplicated.includes('aria-label="Show all 2 authors"'));
	assert.equal((deduplicated.match(/<li><span/g) || []).length, 2);
});

test("toolCard uses structured handles only when the catalog supplies one", () => {
	const html = toolCard({
		...base,
		authors: ["Ada Lovelace"],
		authorObjs: [{ name: "Ada Lovelace", wikiUsername: "Ada", developerUsername: null }]
	});
	assert.ok(html.includes('href="/by/Ada"'));
	assert.ok(!html.includes("context=attribution"));
});

test("toolCard uses canonical relationship identity in account-owned context", () => {
	const html = toolCard({
		...base,
		accountPerson: { id: "person-123", slug: "schiste-0123", displayName: "Schiste" },
		accountRelationships: [{ type: "maintainer", status: "verified" }]
	});
	assert.ok(html.includes("Maintained by"));
	assert.ok(html.includes('href="/people/schiste-0123"'));
	assert.ok(html.includes(">Schiste</span></a>"));
	assert.ok(!html.includes("/by/Jane%20%26%20Co"));
});

test("toolCard links every proven author and maintainer from shared relationship evidence", () => {
	const html = toolCard({
		...base,
		authors: ["Catalog alias"],
		evolvedSummary: {
			maintainer: {
				people: [
					{
						id: "person-author",
						displayName: "Canonical Author",
						relationships: [{ type: "author", status: "unverified", observedNames: ["Catalog alias"] }]
					},
					{
						id: "person-maintainer",
						displayName: "Toolforge Maintainer",
						relationships: [{ type: "maintainer", status: "verified", observedNames: [] }]
					}
				]
			}
		}
	});

	assert.ok(html.includes('href="/people/person-author"'));
	assert.ok(html.includes(">Catalog alias</span></a>"));
	assert.ok(html.includes("Maintained by"));
	assert.ok(html.includes('href="/people/person-maintainer"'));
	assert.ok(html.includes("Toolforge Maintainer"));
	assert.ok(!html.includes("context=attribution"));
});

test("toolCard never guesses when one attribution label matches multiple people", () => {
	const html = toolCard({
		...base,
		authors: ["Shared label"],
		relationshipPeople: ["person-one", "person-two"].map((id) => ({
			id,
			displayName: id,
			relationships: [{ type: "author", observedNames: ["Shared label"] }]
		}))
	});

	assert.ok(html.includes('<span class="tcard__maint-name"'));
	assert.ok(!html.includes("/by/Shared%20label"));
	assert.ok(!html.includes("/people/person-one"));
	assert.ok(!html.includes("/people/person-two"));
});

test("toolCard does not repeat one person as both author and maintainer", () => {
	const html = toolCard({
		...base,
		authors: ["Ada"],
		relationshipPeople: [
			{
				id: "person-ada",
				displayName: "Ada",
				relationships: [{ type: "author" }, { type: "maintainer", status: "verified" }]
			}
		]
	});

	assert.ok(html.includes('href="/people/person-ada"'));
	assert.ok(!html.includes("Maintained by"));
});

test("toolCard renders unknown health as a dash in the metric row", () => {
	const html = toolCard(base);
	assert.ok(
		html.includes(
			'<span class="tcard__health-dash" title="Health score unknown" aria-label="Health score unknown">—</span>'
		)
	);
	assert.ok(html.includes('class="tcard tcard--health-unknown"'));
	assert.ok(!html.includes("health-score--unknown"));
});

test("toolCard renders attached health score and confirmed maintainer byline", () => {
	const html = toolCard({
		...base,
		evolvedSummary: {
			health: {
				score: 84,
				grade: "good",
				dimensions: [
					{
						key: "maintainer-status",
						label: "Maintainer status",
						score: 84,
						weight: 1.25,
						confidence: 0.85,
						status: "maintained",
						summary: "Derived from deterministic maintainer signals.",
						includedInScore: true
					}
				],
				calculation: { dimensionCount: 1, includedDimensionCount: 1, includedWeight: 1.25 }
			},
			maintainer: { healthCounts: { maintainers: 2, verifiedPeople: 1, activePeople: 1 } },
			maintainerDimension: { status: "maintained", bestConfidence: 84 }
		}
	});
	assert.ok(html.includes("Health 84"));
	assert.ok(html.includes('class="tcard tcard--health-great"'));
	assert.ok(html.includes("health-score--compact"));
	assert.ok(html.includes('>84</span><span class="health-score__grade">Great</span>'));
	assert.ok(html.includes("<details"));
	assert.ok(html.includes("Local Evolved health score"));
	assert.ok(html.includes("Included dimensions:"));
	assert.ok(html.includes("- Maintainer status: score 84 · weight 1.25 · confidence 85% · maintained"));
	assert.ok(html.includes("84 × 1.25 = 105 weighted points."));
	assert.ok(html.includes("105 weighted points ÷ 1.25 total weight = 84; rounded to 84."));
	assert.ok(html.includes("How the health score system works"));
	assert.ok(html.includes('<details class="health-popover'));
	assert.ok(!html.includes("health-chip--compact"));
	assert.ok(!html.includes("Maintained"));
	assert.ok(html.includes("tcard__maint-name--confirmed"));
	assert.ok(html.includes("Jane &amp; Co, confirmed maintainer"));
	assert.ok(!html.includes("verified maintainer relationship"));
	assert.ok(!html.includes("tcard__maint-status"));
	assert.ok(!html.includes("tcard__maint-check"));
	assert.ok(html.includes("Calculation: weighted average across 1 of 1 dimensions"));
});

test("CARD_TAG_LIMIT export value", () => {
	assert.equal(CARD_TAG_LIMIT, 2);
	assert.equal(CARD_AUTHOR_TEXT_LIMIT, 42);
});
