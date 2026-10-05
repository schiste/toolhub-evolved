// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test } from "vitest";
import { verdict } from "./audit-js.mjs";

const BRACES_ADVISORY = "https://github.com/advisories/GHSA-vfj7-8cjw-p6xm";
const OTHER_ADVISORY = "https://github.com/advisories/GHSA-0000-0000-0000";

function auditReport({ additional = {}, mutate } = {}) {
	const vulnerabilities = {
		braces: {
			severity: "high",
			via: [{ name: "braces", source: 1240992, url: BRACES_ADVISORY, severity: "high" }]
		},
		"fast-glob": { severity: "high", via: ["micromatch"] },
		globby: { severity: "high", via: ["fast-glob"] },
		micromatch: { severity: "high", via: ["braces"] },
		stylelint: { severity: "high", via: ["fast-glob", "globby", "micromatch"] },
		"stylelint-config-recommended": { severity: "high", via: ["stylelint"] },
		"stylelint-config-standard": { severity: "high", via: ["stylelint", "stylelint-config-recommended"] },
		"stylelint-declaration-strict-value": { severity: "high", via: ["stylelint"] },
		...additional
	};
	mutate?.(vulnerabilities);
	const counts = Object.fromEntries(
		["info", "low", "moderate", "high", "critical"].map((severity) => [
			severity,
			Object.values(vulnerabilities).filter((item) => item.severity === severity).length
		])
	);
	counts.total = Object.values(counts).reduce((total, count) => total + count, 0);
	return { metadata: { vulnerabilities: counts }, vulnerabilities };
}

test("the active exception only waives the GHSA dependency chain", () => {
	const result = verdict(JSON.stringify(auditReport()), new Date("2026-10-05T12:00:00Z"));
	assert.equal(result.ok, true);
	assert.equal(result.reason, "temporarily-waived");
	assert.equal(result.remainingCounts.high, 0);
	assert.deepEqual(result.waived, {
		advisory: "GHSA-vfj7-8cjw-p6xm",
		expiresOn: "2026-11-05",
		packages: [
			"braces",
			"fast-glob",
			"globby",
			"micromatch",
			"stylelint",
			"stylelint-config-recommended",
			"stylelint-config-standard",
			"stylelint-declaration-strict-value"
		]
	});
});

test("the exception stops waiving findings after its expiry date", () => {
	const result = verdict(JSON.stringify(auditReport()), new Date("2026-11-06T00:00:00Z"));
	assert.equal(result.ok, false);
	assert.equal(result.reason, "vulnerable");
	assert.equal(result.remainingCounts.high, 8);
	assert.equal(result.waived, null);
});

test("an unrelated high vulnerability remains blocking", () => {
	const result = verdict(
		JSON.stringify(
			auditReport({
				additional: {
					postcss: {
						severity: "high",
						via: [{ name: "postcss", source: 9876, url: OTHER_ADVISORY, severity: "high" }]
					}
				}
			})
		),
		new Date("2026-10-05T12:00:00Z")
	);
	assert.equal(result.ok, false);
	assert.equal(result.reason, "vulnerable");
	assert.equal(result.remainingCounts.high, 1);
});

test("a shared package with another advisory keeps its dependent chain blocking", () => {
	const result = verdict(
		JSON.stringify(
			auditReport({
				mutate: (vulnerabilities) => {
					vulnerabilities.stylelint.via.push({
						name: "stylelint",
						source: 9876,
						url: OTHER_ADVISORY,
						severity: "high"
					});
				}
			})
		),
		new Date("2026-10-05T12:00:00Z")
	);
	assert.equal(result.ok, false);
	assert.equal(result.reason, "vulnerable");
	assert.equal(result.remainingCounts.high, 4);
	assert.deepEqual(result.waived.packages, ["braces", "fast-glob", "globby", "micromatch"]);
});
