// SPDX-License-Identifier: GPL-3.0-or-later
/** Keep JavaScript coverage moving monotonically toward an explicit 100% target. */
import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const POLICY_PATH = path.join(ROOT, ".coverage-ratchet.json");
const SUMMARY_PATH = path.join(ROOT, "coverage", "coverage-summary.json");
export const METRICS = ["statements", "branches", "functions", "lines"];

/** @param {unknown} value @param {string} label */
function percentage(value, label) {
	const parsed = Number(value);
	if (!Number.isFinite(parsed) || parsed < 0 || parsed > 100) throw new Error(`${label} must be between 0 and 100`);
	return parsed;
}

/**
 * @param {Record<string, any>} summary V8 coverage-summary.json payload
 * @param {{ target: number, minimum: Record<string, number> }} policy
 */
export function evaluateCoverage(summary, policy) {
	if (!summary?.total) throw new Error("coverage summary has no total row");
	const target = percentage(policy?.target, "target");
	const rows = METRICS.map((metric) => {
		const actual = percentage(summary.total[metric]?.pct, `${metric} coverage`);
		const minimum = percentage(policy?.minimum?.[metric], `${metric} minimum`);
		const total = Number(summary.total[metric]?.total ?? 0);
		const covered = Number(summary.total[metric]?.covered ?? 0);
		return { metric, actual, minimum, target, uncovered: Math.max(0, total - covered) };
	});
	return {
		rows,
		failures: rows.filter(({ actual, minimum }) => actual + Number.EPSILON < minimum)
	};
}

/** @param {ReturnType<typeof evaluateCoverage>["rows"]} rows */
export function raisedMinimums(rows) {
	return Object.fromEntries(rows.map(({ metric, actual, minimum }) => [metric, Math.max(actual, minimum)]));
}

function main() {
	const policy = JSON.parse(readFileSync(POLICY_PATH, "utf8"));
	const summary = JSON.parse(readFileSync(SUMMARY_PATH, "utf8"));
	const result = evaluateCoverage(summary, policy);
	for (const row of result.rows) {
		console.log(
			`coverage-ratchet: ${row.metric} ${row.actual.toFixed(2)}% ` +
				`(floor ${row.minimum.toFixed(2)}%, target ${row.target.toFixed(2)}%, ${row.uncovered} uncovered)`
		);
	}
	if (result.failures.length > 0) {
		console.error(
			`coverage-ratchet: regression in ${result.failures.map(({ metric }) => metric).join(", ")}; ` +
				"add tests or restore the covered behavior"
		);
		process.exitCode = 1;
		return;
	}
	if (process.argv.includes("--update")) {
		const updated = { ...policy, minimum: raisedMinimums(result.rows) };
		writeFileSync(POLICY_PATH, `${JSON.stringify(updated, null, "\t")}\n`);
		console.log("coverage-ratchet: committed floors updated without lowering any metric");
	}
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) main();
