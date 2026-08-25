// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { performance } from "node:perf_hooks";
import { test } from "vitest";
import { simulate } from "../../public_html/lib/workers/graph-layout-worker.js";

// Stryker runs this suite from a copy of the repo under .stryker-tmp/sandbox-*,
// against a `simulate` rewritten to report which expressions each test reached.
// That bookkeeping costs real time -- the 2,000-node layout below lands around 6s
// instrumented against 1s as authored -- which breaks the budget test twice over:
// the assertion is false, and the run does not even reach it before vitest's 5s
// timeout kills it. Neither says anything about the code. Left alone they failed
// the dry run, and a failed dry run aborts the whole shard, so the nine other views
// sharing it stopped being mutated over one stopwatch. As authored the budget
// stands; instrumented the clock is ignored and only correctness is asserted, which
// is the half that kills mutants anyway.
const INSTRUMENTED = import.meta.url.includes("/.stryker-tmp/sandbox-");
const BUDGET_TIMEOUT = INSTRUMENTED ? 60_000 : 5_000;

function seededNodes(count) {
	return Array.from({ length: count }, (_, index) => {
		const angle = (index / count) * Math.PI * 2;
		return {
			x: 360 + Math.cos(angle) * (80 + (index % 17) * 5),
			y: 240 + Math.sin(angle) * (80 + (index % 17) * 5),
			groupValues: [index % 2]
		};
	});
}

function distance(a, b) {
	return Math.hypot(a.x - b.x, a.y - b.y);
}

test("worker layout is deterministic and pulls shared facets together", () => {
	const nodes = seededNodes(6);
	nodes[0].groupValues = [0];
	nodes[1].groupValues = [1];
	nodes[2].groupValues = [0];
	nodes[3].groupValues = [1];
	nodes[4].groupValues = [0, 1];
	nodes[5].groupValues = [];
	const payload = {
		width: 720,
		height: 480,
		nodes,
		edges: [],
		groupBy: "project",
		groupMeta: [
			{ id: 0, size: 3 },
			{ id: 1, size: 3 },
			{ id: "other", size: 1 }
		],
		ticks: 200
	};

	const first = simulate(payload);
	const second = simulate(payload);
	const within = (distance(first[0], first[2]) + distance(first[1], first[3])) / 2;
	const across = (distance(first[0], first[1]) + distance(first[2], first[3])) / 2;
	const midpoint = (first[0].x + first[1].x + first[2].x + first[3].x) / 4;

	assert.deepEqual(first, second);
	assert.ok(within < across);
	assert.ok(Math.abs(first[4].x - midpoint) < across / 2);
	assert.notDeepEqual(first[5], first[4]);
});

test(
	"Barnes-Hut layout keeps a 2,000-node overview within its worker budget",
	() => {
		const nodes = seededNodes(2000);
		const started = performance.now();
		const positions = simulate({
			width: 1200,
			height: 800,
			nodes,
			edges: [],
			groupBy: "project",
			groupMeta: [
				{ id: 0, size: 1000 },
				{ id: 1, size: 1000 }
			],
			ticks: 40
		});
		const elapsed = performance.now() - started;

		assert.equal(positions.length, nodes.length);
		assert.ok(positions.every((point) => Number.isFinite(point.x) && Number.isFinite(point.y)));
		if (!INSTRUMENTED) assert.ok(elapsed < 5000, `2,000-node worker layout took ${Math.round(elapsed)}ms`);
	},
	BUDGET_TIMEOUT
);
