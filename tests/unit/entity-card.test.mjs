// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test } from "vitest";
import { entityCard } from "../../public_html/lib/organisms/entity-card.js";

test("entityCard reuses the catalog card structure and escapes adapted data", () => {
	const html = entityCard({
		kind: "Person",
		kindDetail: "Stable <identity>",
		title: "Ada & Co",
		href: "/people/ada",
		visual: '<span class="avatar">A</span>',
		subtitle: "3 related tools",
		description: "Toolhub username: Ada <admin>",
		metrics: [
			{ label: "Tools maintained", value: "2", detail: "1 verified" },
			{ label: "Toolhub records owned", value: "1", detail: "1 verified" }
		],
		tags: [{ label: "Official Toolhub account", className: "entity-card__tag--identity" }],
		signals: [{ label: "Verified maintainer relationship", className: "status status--green" }],
		className: "entity-card--verified",
		dataName: "ada & co"
	});

	assert.match(html, /class="tcard entity-card entity-card--verified"/);
	assert.match(html, /class="tcard__topline"/);
	assert.match(html, /class="tcard__head"/);
	assert.match(html, /class="tcard__tags entity-card__tags"/);
	assert.match(html, /<dl class="entity-card__metrics">/);
	assert.match(
		html,
		/<dt[^>]*>Tools maintained<\/dt><dd[^>]*><strong>2<\/strong><small[^>]*>1 verified<\/small><\/dd>/
	);
	assert.match(html, /class="tcard__signals entity-card__signals"/);
	assert.match(html, /href="\/people\/ada"[^>]*>Ada &amp; Co<\/a>/);
	assert.match(html, /Stable &lt;identity&gt;/);
	assert.match(html, /Ada &lt;admin&gt;/);
	assert.doesNotMatch(html, /<admin>/);
});

test("entityCard supports a non-interactive unresolved result", () => {
	const html = entityCard({
		kind: "Unresolved attribution",
		title: "Shared name",
		visual: '<span class="avatar">?</span>',
		description: "Name-only evidence",
		className: "entity-card--unresolved",
		static: true
	});

	assert.match(html, /entity-card--static/);
	assert.match(html, /<span class="tcard__title"/);
	assert.doesNotMatch(html, /<a /);
});
