// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test } from "vitest";
import { thanksBlock, usageBlock } from "../../public_html/lib/atoms/signals.js";
import { icon } from "../../public_html/lib/atoms/icon.js";
import { synthThanks, synthUsage } from "../../public_html/lib/core/synth.js";

// synthThanks / synthUsage are pure deterministic functions of the tool name.
test("thanksBlock() renders the heart icon, formatted score and plural label", () => {
	assert.equal(synthThanks("t0"), 83); // sanity: drives the expected score below
	const expected =
		'<div class="thanks__agg">' +
		"\n\t\t\t\t\t\t" +
		`<span class="thanks__icon" aria-hidden="true">${icon("heart")}</span>` +
		"\n\t\t\t\t\t\t" +
		'<span class="thanks__score">83</span>' +
		"\n\t\t\t\t\t\t" +
		'<span class="thanks__count">people thanked</span>' +
		"\n\t\t\t\t\t" +
		"</div>";
	assert.equal(thanksBlock({ name: "t0" }), expected);
});

test("usageBlock() renders formatted 30-day usage with plural label", () => {
	assert.equal(synthUsage("t0"), 7496); // sanity: drives the expected count below
	assert.equal(
		usageBlock({ name: "t0" }),
		'<p class="usage"><strong>7,496</strong> editors used this in the last 30 days</p>'
	);
});
