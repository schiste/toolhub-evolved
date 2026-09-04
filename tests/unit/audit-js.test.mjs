// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test } from "vitest";
import { verdict } from "../../tools/audit-js.mjs";

test("a clean report passes", () => {
	const raw = JSON.stringify({
		metadata: { vulnerabilities: { info: 0, low: 2, moderate: 0, high: 0, critical: 0 } }
	});
	assert.deepEqual(verdict(raw).ok, true);
	assert.equal(verdict(raw).reason, "clean");
});

test("low severity alone does not block, matching --audit-level=moderate", () => {
	const raw = JSON.stringify({
		metadata: { vulnerabilities: { info: 9, low: 9, moderate: 0, high: 0, critical: 0 } }
	});
	assert.equal(verdict(raw).reason, "clean");
});

test("a vulnerability at moderate or above blocks", () => {
	for (const level of ["moderate", "high", "critical"]) {
		const raw = JSON.stringify({ metadata: { vulnerabilities: { info: 0, low: 0, [level]: 1 } } });
		assert.equal(verdict(raw).ok, false, level);
		assert.equal(verdict(raw).reason, "vulnerable", level);
	}
});

test("a registry error does not block, because it is not a fact about the code", () => {
	// npm's own shape on 2026-09-04: { error: 'Service Unavailable' } after a 503
	// from /-/npm/v1/security/audits/quick. Blocking on this buys no safety — the
	// advisory set moves independently of the diff — and nothing in the
	// repository can make it pass.
	const raw = JSON.stringify({ error: "Service Unavailable" });
	assert.equal(verdict(raw).ok, true);
	assert.equal(verdict(raw).reason, "registry-unavailable");
});

test("output that is not JSON is treated as an outage, not as a pass", () => {
	// npm failed before producing a report. The reason is reported so the run is
	// visibly un-audited rather than silently green.
	assert.equal(verdict("npm error something went wrong").reason, "unreadable");
});

test("a report without vulnerability metadata is reported rather than interpreted", () => {
	assert.equal(verdict(JSON.stringify({ auditReportVersion: 2 })).reason, "unrecognized-report");
});
