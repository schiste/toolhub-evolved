// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test } from "vitest";
import * as similarity from "../../public_html/lib/core/similarity.js";

// Minimal, self-contained (no beforeEach / fetch / storage) tests that pin the
// nearestNeighbors result-sort comparator:
//   out.sort((a, b) => b.score - a.score || (a.title||a.name).localeCompare(b.title||b.name))
// Titles are chosen so equal-score tiebreaking is observable AND so replacing
// the localeCompare argument with the constant "true"/"false" flips the order.

function termsOf(tool) {
	const out = [];
	const seen = new Set();
	for (const raw of tool.keywords || []) {
		const v = String(raw).trim().toLowerCase();
		if (!v) continue;
		const term = `kw:${v}`;
		if (!seen.has(term)) {
			seen.add(term);
			out.push(term);
		}
	}
	return out;
}
function buildIndex(tools) {
	const df = new Map();
	for (const t of tools) for (const term of termsOf(t)) df.set(term, (df.get(term) || 0) + 1);
	const index = { tools, byName: new Map(), vectors: new Map(), df, N: tools.length };
	for (const t of tools) {
		index.byName.set(t.name, t);
		index.vectors.set(t.name, similarity.vectorFor(t, index));
	}
	return index;
}

test("nearestNeighbors equal-score tiebreak sorts by title (kills || and localeCompare-arg mutants)", () => {
	const source = { name: "S0", title: "S0", keywords: ["k"] };
	// Equal scores (all share only "k"). Insertion order is [F, S]; the title
	// tiebreak ("ttt" < "zzz") must reorder to [S, F].
	const first = { name: "F", title: "zzz", keywords: ["k"] };
	const second = { name: "S", title: "ttt", keywords: ["k"] };
	const index = buildIndex([source, first, second]);
	const out = similarity.nearestNeighbors(source, index, 5);
	assert.equal(out.length, 2);
	assert.equal(out[0].score, out[1].score); // scores are equal => tiebreak decides
	// `&&` would leave insertion order [F,S]; localeCompare("true"/"false") would
	// flip because "ttt" > both constants but < "zzz".
	assert.deepEqual(
		out.map((r) => r.tool.name),
		["S", "F"]
	);
});

test("nearestNeighbors tiebreak uses title (not name) on the source side (kills title&&name)", () => {
	const source = { name: "src", title: "src", keywords: ["k"] };
	// Equal scores. Tiebreak by TITLE: "aaa" < "mmm" => [second, first].
	// If the comparator used NAME instead (title && name => name), it would compare
	// "zzz" vs "mmm" => "zzz" > "mmm" => the order flips.
	const first = { name: "bbb", title: "mmm", keywords: ["k"] };
	const second = { name: "zzz", title: "aaa", keywords: ["k"] };
	const index = buildIndex([source, first, second]);
	const out = similarity.nearestNeighbors(source, index, 5);
	assert.deepEqual(
		out.map((r) => r.tool.name),
		["zzz", "bbb"]
	);
});

test("nearestNeighbors distinct scores beat the name tiebreak (kills ||→&&)", () => {
	const source = { name: "src", title: "src", keywords: ["p", "q"] };
	const hi = { name: "Zhi", title: "Zhi", keywords: ["p", "q"] }; // higher score
	const lo = { name: "Alo", title: "Alo", keywords: ["p"] }; // lower score
	const index = buildIndex([source, hi, lo]);
	const out = similarity.nearestNeighbors(source, index, 5);
	assert.ok(out[0].score > out[1].score);
	assert.deepEqual(
		out.map((r) => r.tool.name),
		["Zhi", "Alo"]
	);
});
