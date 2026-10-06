// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "vitest";
import { verdict } from "./audit-js.mjs";

const PACKAGE_LOCK = JSON.parse(readFileSync("package-lock.json", "utf8"));

const BRACES_ADVISORY = "https://github.com/advisories/GHSA-vfj7-8cjw-p6xm";
const OTHER_ADVISORY = "https://github.com/advisories/GHSA-0000-0000-0000";

function auditReport({ additional = {}, mutate } = {}) {
	const vulnerabilities = {
		braces: {
			severity: "high",
			isDirect: false,
			via: [{ name: "braces", source: 1240992, url: BRACES_ADVISORY, severity: "high" }]
		},
		"fast-glob": { severity: "high", via: ["micromatch"] },
		globby: { severity: "high", via: ["fast-glob"] },
		micromatch: { severity: "high", via: ["braces"] },
		stylelint: {
			severity: "high",
			isDirect: true,
			via: ["fast-glob", "globby", "micromatch"]
		},
		"stylelint-config-recommended": { severity: "high", via: ["stylelint"] },
		"stylelint-config-standard": {
			severity: "high",
			isDirect: true,
			via: ["stylelint", "stylelint-config-recommended"]
		},
		"stylelint-declaration-strict-value": { severity: "high", isDirect: true, via: ["stylelint"] },
		...additional
	};
	mutate?.(vulnerabilities);
	for (const [name, finding] of Object.entries(vulnerabilities)) {
		finding.nodes ??= [`node_modules/${name}`];
	}
	const counts = Object.fromEntries(
		["info", "low", "moderate", "high", "critical"].map((severity) => [
			severity,
			Object.values(vulnerabilities).filter((item) => item.severity === severity).length
		])
	);
	counts.total = Object.values(counts).reduce((total, count) => total + count, 0);
	return { metadata: { vulnerabilities: counts }, vulnerabilities };
}

function auditLockfile(report, productionPackages = []) {
	const production = new Set(productionPackages);
	const packages = {};
	for (const [name, finding] of Object.entries(report.vulnerabilities)) {
		for (const node of finding.nodes) {
			packages[node] = production.has(name) ? {} : { dev: true };
		}
	}
	return { packages };
}

function auditVerdict(raw, now, productionPackages = []) {
	const report = JSON.parse(raw);
	return verdict(raw, now, auditLockfile(report, productionPackages));
}

test("the active exception only waives the GHSA dependency chain", () => {
	const result = auditVerdict(JSON.stringify(auditReport()), new Date("2026-10-05T12:00:00Z"));
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
	const result = auditVerdict(JSON.stringify(auditReport()), new Date("2026-11-06T00:00:00Z"));
	assert.equal(result.ok, false);
	assert.equal(result.reason, "vulnerable");
	assert.equal(result.remainingCounts.high, 8);
	assert.equal(result.waived, null);
});

test("an unrelated high vulnerability remains blocking", () => {
	const result = auditVerdict(
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
	const result = auditVerdict(
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

test("the exception remains active through its inclusive expiry date", () => {
	const result = auditVerdict(JSON.stringify(auditReport()), new Date("2026-11-05T23:59:59Z"));
	assert.equal(result.ok, true);
	assert.equal(result.reason, "temporarily-waived");
	assert.equal(result.waived.expiresOn, "2026-11-05");
});

function assertAuditBlocksWaiver(report, packageLock, expectedHighCount = 8) {
	const result = verdict(JSON.stringify(report), new Date("2026-10-05T12:00:00Z"), packageLock);
	assert.equal(result.ok, false);
	assert.equal(result.reason, "vulnerable");
	assert.equal(result.remainingCounts.high, expectedHighCount);
	assert.equal(result.waived, null);
}

function assertAuditRemainsBlocking(mutate, expectedHighCount = 8, productionPackages = []) {
	const report = auditReport({ mutate });
	assertAuditBlocksWaiver(report, auditLockfile(report, productionPackages), expectedHighCount);
}

test("a braces finding with a different advisory source remains blocking", () => {
	assertAuditRemainsBlocking((vulnerabilities) => {
		vulnerabilities.braces.via[0].source = 9876;
	});
});

test("a braces finding with a different advisory URL remains blocking", () => {
	assertAuditRemainsBlocking((vulnerabilities) => {
		vulnerabilities.braces.via[0].url = OTHER_ADVISORY;
	});
});

test("a direct braces dependency is not covered by the exception", () => {
	assertAuditRemainsBlocking((vulnerabilities) => {
		vulnerabilities.braces.isDirect = true;
	});
});

test("an unapproved production dependent remains blocking", () => {
	assertAuditRemainsBlocking(
		(vulnerabilities) => {
			vulnerabilities["production-server"] = {
				severity: "high",
				via: ["braces"],
				isDirect: true
			};
		},
		9,
		["production-server"]
	);
});

test("an allowlisted package on a production path remains blocking", () => {
	assertAuditRemainsBlocking(
		(vulnerabilities) => {
			vulnerabilities.micromatch.isDirect = true;
		},
		8,
		["micromatch"]
	);
});

test("a braces finding with a different advisory name remains blocking", () => {
	assertAuditRemainsBlocking((vulnerabilities) => {
		vulnerabilities.braces.via[0].name = "not-braces";
	});
});

test("the current lockfile supports the reviewed development-only chain", () => {
	const report = auditReport();
	const result = verdict(JSON.stringify(report), new Date("2026-10-05T12:00:00Z"), PACKAGE_LOCK);

	assert.equal(result.ok, true);
	assert.deepEqual(result.waived.packages, [
		"braces",
		"fast-glob",
		"globby",
		"micromatch",
		"stylelint",
		"stylelint-config-recommended",
		"stylelint-config-standard",
		"stylelint-declaration-strict-value"
	]);
});

test("a nested development-only node is verified by its exact lockfile path", () => {
	const report = auditReport();
	const packageLock = auditLockfile(report);
	const nestedNode = "node_modules/stylelint/node_modules/micromatch";
	report.vulnerabilities.micromatch.nodes = [nestedNode];
	packageLock.packages[nestedNode] = { dev: true };
	const result = verdict(JSON.stringify(report), new Date("2026-10-05T12:00:00Z"), packageLock);

	assert.equal(result.ok, true);
	assert.ok(result.waived.packages.includes("micromatch"));
});

test("one production node among multiple package paths blocks the exception", () => {
	const report = auditReport();
	const packageLock = auditLockfile(report);
	const productionNode = "node_modules/production-server/node_modules/micromatch";
	report.vulnerabilities.micromatch.nodes.push(productionNode);
	packageLock.packages[productionNode] = { dev: false };
	assertAuditBlocksWaiver(report, packageLock);
});

test("missing node evidence blocks the exception", () => {
	const report = auditReport();
	const packageLock = auditLockfile(report);
	delete report.vulnerabilities.micromatch.nodes;
	assertAuditBlocksWaiver(report, packageLock);
});

test("empty node evidence blocks the exception", () => {
	const report = auditReport();
	report.vulnerabilities.micromatch.nodes = [];
	assertAuditBlocksWaiver(report, auditLockfile(report));
});

test("an unmatched lockfile node path blocks the exception", () => {
	const report = auditReport();
	const packageLock = auditLockfile(report);
	report.vulnerabilities.micromatch.nodes = ["node_modules/unknown/node_modules/micromatch"];
	assertAuditBlocksWaiver(report, packageLock);
});
