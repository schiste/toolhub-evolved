// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test } from "vitest";
import { listCard, listCardData } from "../../public_html/lib/organisms/list-card.js";
import { dirAttrs, esc } from "../../public_html/lib/core/dom.js";
import { countLabel } from "../../public_html/lib/core/i18n.js";
import { listHref } from "../../public_html/lib/core/routing.js";
import { avatar } from "../../public_html/lib/atoms/avatar.js";
import { syncBadge } from "../../public_html/lib/molecules/sync-status.js";

/** @param {any} l */
function oracle(l) {
	const count = countLabel(l.toolCount, "tool", "tools");
	const status = l.local ? syncBadge(l) : "";
	return `\n\t<a class="lcard" href="${listHref(l.id)}" aria-label="${esc(l.title)} list, ${esc(count)}">\n\t\t${avatar(l.title)}\n\t\t<div class="lcard__body">\n\t\t\t<div class="lcard__title"${dirAttrs(l.title)}>${esc(l.title)} <span class="lcard__count">${esc(count)}</span>${status ? ` ${status}` : ""}</div>\n\t\t\t<div class="lcard__desc"${dirAttrs(l.description)}>${esc(l.description)}</div>\n\t\t</div>\n\t</a>`;
}

test("listCard exact HTML, local badge present", () => {
	const l = { id: "L 1", title: "Cool <List>", description: "D & e", toolCount: 3, local: true };
	assert.equal(listCard(l), oracle(l));
});

test("listCard exact HTML, no local badge, singular count", () => {
	const l = { id: "L2", title: "One", description: "", toolCount: 1, local: false };
	assert.equal(listCard(l), oracle(l));
});

test("listCard zero count", () => {
	const l = { id: "L3", title: "Empty", description: "x", toolCount: 0, local: true };
	assert.equal(listCard(l), oracle(l));
});

test("listCardData fully populated", () => {
	assert.deepEqual(listCardData({ id: "A", title: "T", description: "D", tools: [1, 2, 3] }), {
		id: "A",
		title: "T",
		description: "D",
		toolCount: 3,
		local: true,
		syncStatus: "local_draft"
	});
});

test("listCardData falls back for missing title/description/tools", () => {
	assert.deepEqual(listCardData({ id: "B" }), {
		id: "B",
		title: "Untitled list",
		description: "",
		toolCount: 0,
		local: true,
		syncStatus: "local_draft"
	});
});

test("listCardData keeps provided empty title fallback only when falsy", () => {
	// Title present but empty string -> fallback; description present -> kept.
	assert.deepEqual(listCardData({ id: "C", title: "", description: "keep", tools: [1] }), {
		id: "C",
		title: "Untitled list",
		description: "keep",
		toolCount: 1,
		local: true,
		syncStatus: "local_draft"
	});
});

test("listCardData preserves optional provenance metadata", () => {
	assert.deepEqual(
		listCardData({
			id: "D",
			title: "Needs review",
			description: "",
			tools: [],
			syncStatus: "local_fallback",
			lastError: "Denied",
			reviewStatus: "pending",
			validationErrors: ["bad"]
		}),
		{
			id: "D",
			title: "Needs review",
			description: "",
			toolCount: 0,
			local: true,
			syncStatus: "local_fallback",
			lastError: "Denied",
			reviewStatus: "pending",
			validationErrors: ["bad"]
		}
	);
});
