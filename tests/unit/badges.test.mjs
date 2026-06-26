// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "vitest";
import { installStorage } from "./_storage-setup.mjs";
import {
	statusBadge,
	healthBadge,
	popularityBadge,
	endorsementChip,
	completenessMeter,
	completenessList,
	fitChip,
	freshnessNote,
	endorsementOf
} from "../../public_html/lib/atoms/badges.js";
import { icon } from "../../public_html/lib/atoms/icon.js";
import { synthHealth } from "../../public_html/lib/core/synth.js";

let store;
beforeEach(() => {
	store = installStorage();
});
afterEach(() => {
	store.clear();
});

// ---- statusBadge --------------------------------------------------------------
test("statusBadge() renders green status markup for a deprecated tool", () => {
	assert.equal(
		statusBadge({ deprecated: true, status: { level: "green", label: "Healthy" } }),
		'<span class="status status--green"><span class="dot dot--green"></span>Healthy</span>'
	);
});

test("statusBadge() renders red markup for an experimental tool", () => {
	assert.equal(
		statusBadge({ experimental: true, status: { level: "red", label: "Down" } }),
		'<span class="status status--red"><span class="dot dot--red"></span>Down</span>'
	);
});

test("statusBadge() renders yellow markup", () => {
	assert.equal(
		statusBadge({ deprecated: true, status: { level: "yellow", label: "Degraded" } }),
		'<span class="status status--yellow"><span class="dot dot--yellow"></span>Degraded</span>'
	);
});

test("statusBadge() returns empty when neither deprecated nor experimental", () => {
	assert.equal(
		statusBadge({ deprecated: false, experimental: false, status: { level: "green", label: "Healthy" } }),
		""
	);
});

test("statusBadge() defaults to green/Healthy when status object is absent", () => {
	assert.equal(
		statusBadge({ deprecated: true, status: null }),
		'<span class="status status--green"><span class="dot dot--green"></span>Healthy</span>'
	);
});

test("statusBadge() unknown level falls back to green classes", () => {
	assert.equal(
		statusBadge({ deprecated: true, status: { level: "blue", label: "Weird" } }),
		'<span class="status status--green"><span class="dot dot--green"></span>Weird</span>'
	);
});

// ---- healthBadge (synthHealth is a pure fn of name) ---------------------------
test("healthBadge() renders the synthetic health with an 'experimental' extra class", () => {
	// names chosen so synthHealth() returns each level
	assert.equal(synthHealth("t9").level, "red");
	assert.equal(synthHealth("t1").level, "yellow");
	assert.equal(synthHealth("t0").level, "green");
	assert.equal(
		healthBadge({ name: "t9" }),
		'<span class="status status--red experimental"><span class="dot dot--red"></span>Down</span>'
	);
	assert.equal(
		healthBadge({ name: "t1" }),
		'<span class="status status--yellow experimental"><span class="dot dot--yellow"></span>Degraded</span>'
	);
	assert.equal(
		healthBadge({ name: "t0" }),
		'<span class="status status--green experimental"><span class="dot dot--green"></span>Healthy</span>'
	);
});

// ---- popularityBadge ----------------------------------------------------------
test("popularityBadge() renders the popular icon + compact view count", () => {
	assert.equal(
		popularityBadge({ weeklyViews: 1500 }),
		`<span class="views experimental">${icon("popular")} 1.5K views</span>`
	);
});

test("popularityBadge() with zero views", () => {
	assert.equal(
		popularityBadge({ weeklyViews: 0 }),
		`<span class="views experimental">${icon("popular")} 0 views</span>`
	);
});

// ---- endorsementChip ----------------------------------------------------------
test("endorsementChip() returns empty for 0 / null", () => {
	assert.equal(endorsementChip(0), "");
	assert.equal(endorsementChip(null), "");
	assert.equal(endorsementChip(undefined), "");
});

test("endorsementChip() singular label for count 1", () => {
	assert.equal(
		endorsementChip(1),
		`<span class="signal" title="Appears in 1 curated list">${icon("list")} In 1 list</span>`
	);
});

test("endorsementChip() plural label for count > 1", () => {
	assert.equal(
		endorsementChip(5),
		`<span class="signal" title="Appears in 5 curated lists">${icon("list")} In 5 lists</span>`
	);
});

// ---- completenessMeter --------------------------------------------------------
test("completenessMeter() complete state (filled === total)", () => {
	assert.equal(
		completenessMeter({ total: 9, filled: 9 }),
		`<span class="signal signal--complete" title="Listing 9 of 9 fields complete">${icon("check")} Well documented</span>`
	);
});

test("completenessMeter() partial state renders meter + percentage", () => {
	assert.equal(
		completenessMeter({ total: 9, filled: 3 }),
		'<span class="signal" title="Listing 3 of 9 fields complete"><span class="meter" aria-hidden="true"><span class="meter__fill" style="width:33%"></span></span>3/9</span>'
	);
});

test("completenessMeter() zero total renders 0/0 at 0%", () => {
	assert.equal(
		completenessMeter({ total: 0, filled: 0 }),
		'<span class="signal" title="Listing 0 of 0 fields complete"><span class="meter" aria-hidden="true"><span class="meter__fill" style="width:0%"></span></span>0/0</span>'
	);
});

test("completenessMeter() clamps negative filled to 0", () => {
	assert.equal(
		completenessMeter({ total: 9, filled: -5 }),
		'<span class="signal" title="Listing 0 of 9 fields complete"><span class="meter" aria-hidden="true"><span class="meter__fill" style="width:0%"></span></span>0/9</span>'
	);
});

test("completenessMeter() clamps negative total to 0", () => {
	assert.equal(
		completenessMeter({ total: -2, filled: 0 }),
		'<span class="signal" title="Listing 0 of 0 fields complete"><span class="meter" aria-hidden="true"><span class="meter__fill" style="width:0%"></span></span>0/0</span>'
	);
});

test("completenessMeter() clamps filled over total down to total (=> complete)", () => {
	assert.equal(
		completenessMeter({ total: 9, filled: 100 }),
		`<span class="signal signal--complete" title="Listing 9 of 9 fields complete">${icon("check")} Well documented</span>`
	);
});

test("completenessMeter() computes completeness when c lacks a total field", () => {
	assert.equal(
		completenessMeter({}),
		'<span class="signal" title="Listing 0 of 9 fields complete"><span class="meter" aria-hidden="true"><span class="meter__fill" style="width:0%"></span></span>0/9</span>'
	);
});

test("completenessMeter() compute path reflects the tool's filled fields (not {}/true/false)", () => {
	// A tool with description(>=30)/url/keywords => completeness() yields 3/9.
	// Kills the `c || {}` mutants (false/true/&&) which would all collapse to 0/9.
	const tool = { description: "x".repeat(30), url: "https://x.org", keywords: ["a"] };
	assert.equal(
		completenessMeter(tool),
		'<span class="signal" title="Listing 3 of 9 fields complete"><span class="meter" aria-hidden="true"><span class="meter__fill" style="width:33%"></span></span>3/9</span>'
	);
});

// ---- completenessList ---------------------------------------------------------
test("completenessList() renders ok/empty rows", () => {
	assert.equal(
		completenessList({
			items: [
				{ ok: true, label: "A" },
				{ ok: false, label: "B" }
			]
		}),
		`<ul class="complete-list"><li><span class="complete-list__icon">${icon("check")}</span><span>A</span></li><li><span class="complete-list__icon complete-list__icon--empty">○</span><span>B</span></li></ul>`
	);
});

test("completenessList() empty when no items", () => {
	assert.equal(completenessList({}), '<ul class="complete-list"></ul>');
});

// ---- fitChip ------------------------------------------------------------------
test("fitChip() empty when there is no matching user context", () => {
	store.clear();
	assert.equal(fitChip({ forWikis: ["en.wikipedia.org"], audiences: [] }), "");
});

test("fitChip() renders the fit signal when the wiki matches the user context", () => {
	store.setItem("toolhub-context", JSON.stringify({ wiki: "en.wikipedia.org", role: "" }));
	assert.equal(
		fitChip({ forWikis: ["en.wikipedia.org"], audiences: [] }),
		`<span class="signal signal--fit">${icon("check")} Fits you</span>`
	);
});

// ---- freshnessNote ------------------------------------------------------------
test("freshnessNote() renders Maintained for a recently modified tool", () => {
	assert.equal(freshnessNote({ modified: new Date().toISOString() }), '<span class="signal">Maintained</span>');
});

test("freshnessNote() empty for a stale modified date", () => {
	assert.equal(freshnessNote({ modified: "2000-01-01T00:00:00Z" }), "");
});

test("freshnessNote() empty when modified is missing", () => {
	assert.equal(freshnessNote({}), "");
});

// ---- endorsementOf (re-export) ------------------------------------------------
test("endorsementOf() reports membership count from the map", () => {
	const map = new Map([["x", [{ id: "1", title: "T" }]]]);
	assert.deepEqual(endorsementOf("x", map), { count: 1, lists: [{ id: "1", title: "T" }] });
	assert.deepEqual(endorsementOf("missing", map), { count: 0, lists: [] });
});
