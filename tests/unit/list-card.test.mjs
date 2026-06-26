// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test } from "vitest";
import { listCard, listCardData } from "../../public_html/lib/organisms/list-card.js";
import { dirAttrs, esc } from "../../public_html/lib/core/dom.js";
import { countLabel } from "../../public_html/lib/core/i18n.js";
import { listHref } from "../../public_html/lib/core/routing.js";
import { avatar } from "../../public_html/lib/atoms/avatar.js";

/** @param {any} l */
function oracle(l) {
	const count = countLabel(l.toolCount, "tool", "tools");
	return `\n\t<a class="lcard" href="${listHref(l.id)}" aria-label="${esc(l.title)} list, ${esc(count)}">\n\t\t${avatar(l.title)}\n\t\t<div class="lcard__body">\n\t\t\t<div class="lcard__title"${dirAttrs(l.title)}>${esc(l.title)} <span class="lcard__count">${esc(count)}</span>${l.demo ? ' <span class="exp-badge">Demo</span>' : ""}</div>\n\t\t\t<div class="lcard__desc"${dirAttrs(l.description)}>${esc(l.description)}</div>\n\t\t</div>\n\t</a>`;
}

test("listCard exact HTML, demo badge present", () => {
	const l = { id: "L 1", title: "Cool <List>", description: "D & e", toolCount: 3, demo: true };
	assert.equal(listCard(l), oracle(l));
});

test("listCard exact HTML, no demo badge, singular count", () => {
	const l = { id: "L2", title: "One", description: "", toolCount: 1, demo: false };
	assert.equal(listCard(l), oracle(l));
});

test("listCard zero count", () => {
	const l = { id: "L3", title: "Empty", description: "x", toolCount: 0, demo: true };
	assert.equal(listCard(l), oracle(l));
});

test("listCardData fully populated", () => {
	assert.deepEqual(listCardData({ id: "A", title: "T", description: "D", tools: [1, 2, 3] }), {
		id: "A",
		title: "T",
		description: "D",
		toolCount: 3,
		demo: true
	});
});

test("listCardData falls back for missing title/description/tools", () => {
	assert.deepEqual(listCardData({ id: "B" }), {
		id: "B",
		title: "Untitled list",
		description: "",
		toolCount: 0,
		demo: true
	});
});

test("listCardData keeps provided empty title fallback only when falsy", () => {
	// Title present but empty string -> fallback; description present -> kept.
	assert.deepEqual(listCardData({ id: "C", title: "", description: "keep", tools: [1] }), {
		id: "C",
		title: "Untitled list",
		description: "keep",
		toolCount: 1,
		demo: true
	});
});
