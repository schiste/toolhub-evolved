// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test } from "vitest";
import { evaluateCoverage, raisedMinimums } from "../../tools/js-coverage-ratchet.mjs";

function summary(values) {
	return {
		total: Object.fromEntries(
			Object.entries(values).map(([metric, pct]) => [metric, { pct, covered: pct, total: 100 }])
		)
	};
}

const policy = {
	target: 100,
	minimum: { statements: 90, branches: 80, functions: 92, lines: 91 }
};

test("coverage ratchet reports progress to 100 without rejecting improvements", () => {
	const result = evaluateCoverage(summary({ statements: 91, branches: 81, functions: 93, lines: 92 }), policy);
	assert.deepEqual(result.failures, []);
	assert.deepEqual(
		result.rows.map(({ target }) => target),
		[100, 100, 100, 100]
	);
	assert.deepEqual(
		result.rows.map(({ uncovered }) => uncovered),
		[9, 19, 7, 8]
	);
});

test("coverage ratchet identifies every regressing metric", () => {
	const result = evaluateCoverage(summary({ statements: 89.99, branches: 80, functions: 91.99, lines: 91 }), policy);
	assert.deepEqual(
		result.failures.map(({ metric }) => metric),
		["statements", "functions"]
	);
});

test("coverage floor updates are monotonic", () => {
	const result = evaluateCoverage(summary({ statements: 95, branches: 79, functions: 94, lines: 90 }), policy);
	assert.deepEqual(raisedMinimums(result.rows), { statements: 95, branches: 80, functions: 94, lines: 91 });
});

test("invalid policy and summary data fail closed", () => {
	assert.throws(() => evaluateCoverage({}, policy), /no total row/);
	assert.throws(
		() =>
			evaluateCoverage(summary({ statements: 90, branches: 80, functions: 92, lines: 91 }), {
				...policy,
				target: 101
			}),
		/between 0 and 100/
	);
});
