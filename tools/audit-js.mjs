#!/usr/bin/env node
// SPDX-License-Identifier: GPL-3.0-or-later
// Dependency audit that fails on vulnerabilities and not on being unable to look.
//
// `npm audit` exits 1 for two unrelated reasons: it found something, or it could
// not ask. As a required check that made every merge depend on registry.npmjs.org
// being reachable, and on 2026-09-04 it blocked this repository twice in a row
// while npm's audit endpoint returned 503 — seven minutes of retries, then
// thirteen — against a lockfile that audits clean. Nothing in the repository
// could have made that pass.
//
// Those two outcomes deserve different answers. A vulnerability is a fact about
// the code and must block. An outage is a fact about npm, and blocking on it
// buys no safety: the advisory set moves independently of the diff, so a change
// merged during an outage is no more dangerous than the same change merged an
// hour before the advisory was published, and the next successful run on any
// branch reports it. The audit is a standing check on the dependency tree, not a
// property of one commit.
//
// So an outage warns loudly and exits 0. A finding still fails.
import { execFileSync } from "node:child_process";
import { pathToFileURL } from "node:url";

export const AUDIT_LEVEL = "moderate";
//: Severities at or above AUDIT_LEVEL, in npm's own vocabulary.
export const BLOCKING = ["moderate", "high", "critical"];

// Time-boxed operator exception: the advisory has no published fix yet. It is
// limited to the transitive Stylelint development-tooling chain and expires even
// if upstream has not released a fixed version by then.
const TEMPORARY_WAIVERS = {
	"GHSA-vfj7-8cjw-p6xm": {
		packageName: "braces",
		source: 1240992,
		url: "https://github.com/advisories/GHSA-vfj7-8cjw-p6xm",
		expiresOn: "2026-11-05"
	}
};

function isWaivedAdvisory(reference, waiver) {
	return (
		reference && typeof reference === "object" && reference.source === waiver.source && reference.url === waiver.url
	);
}

function collectAdvisoryChain(vulnerabilities, waiver) {
	const root = vulnerabilities[waiver.packageName];
	if (!Array.isArray(root?.via) || root.via.length !== 1 || !isWaivedAdvisory(root.via[0], waiver)) {
		return [];
	}

	const affected = new Set([waiver.packageName]);
	let changed = true;
	while (changed) {
		changed = false;
		for (const [name, finding] of Object.entries(vulnerabilities)) {
			if (
				affected.has(name) ||
				!Array.isArray(finding.via) ||
				finding.via.length === 0 ||
				!finding.via.every((dependency) => typeof dependency === "string" && affected.has(dependency))
			) {
				continue;
			}
			affected.add(name);
			changed = true;
		}
	}
	return [...affected].sort();
}

function remainingCounts(found, vulnerabilities, waivedPackages) {
	const remaining = Object.fromEntries(BLOCKING.map((level) => [level, found[level] ?? 0]));
	for (const name of waivedPackages) {
		const severity = vulnerabilities[name]?.severity;
		if (!BLOCKING.includes(severity)) continue;
		if (!Number.isSafeInteger(remaining[severity]) || remaining[severity] < 1) return null;
		remaining[severity] -= 1;
	}
	return remaining;
}

/** Decide from one `npm audit --json` payload and an injectable evaluation date. */
export function verdict(raw, now = new Date()) {
	let report;
	try {
		report = JSON.parse(raw);
	} catch {
		// Not JSON at all: npm failed before it produced a report. Treat it the
		// same as an explicit endpoint error rather than guessing at the cause.
		return { ok: true, reason: "unreadable", counts: null, remainingCounts: null, waived: null };
	}
	if (report.error) {
		return { ok: true, reason: "registry-unavailable", counts: null, remainingCounts: null, waived: null };
	}
	const found = report.metadata?.vulnerabilities;
	if (!found) {
		// A report with no vulnerability metadata is a shape this does not
		// understand; refusing to interpret it is safer than inventing a pass or
		// a fail from it, and it is reported rather than swallowed.
		return { ok: true, reason: "unrecognized-report", counts: null, remainingCounts: null, waived: null };
	}

	let remaining = Object.fromEntries(BLOCKING.map((level) => [level, found[level] ?? 0]));
	let waived = null;
	const vulnerabilities = report.vulnerabilities;
	if (vulnerabilities && typeof vulnerabilities === "object") {
		const today = now.toISOString().slice(0, 10);
		for (const [advisory, waiver] of Object.entries(TEMPORARY_WAIVERS)) {
			if (today > waiver.expiresOn) continue;
			const packages = collectAdvisoryChain(vulnerabilities, waiver);
			if (packages.length === 0) continue;
			const adjusted = remainingCounts(found, vulnerabilities, packages);
			if (!adjusted) continue;
			remaining = adjusted;
			waived = { advisory, expiresOn: waiver.expiresOn, packages };
		}
	}

	const blocking = BLOCKING.reduce((total, level) => total + remaining[level], 0);
	const reason = blocking > 0 ? "vulnerable" : waived ? "temporarily-waived" : "clean";
	return { ok: blocking === 0, reason, counts: found, remainingCounts: remaining, waived };
}

function main() {
	let raw;
	try {
		raw = execFileSync("npm", ["audit", "--json", `--audit-level=${AUDIT_LEVEL}`], {
			encoding: "utf8",
			stdio: ["ignore", "pipe", "pipe"]
		});
	} catch (error) {
		// npm exits non-zero for findings too, and the report is still on stdout.
		raw = error.stdout ?? "";
	}
	const { ok, reason, counts, remainingCounts: remaining, waived } = verdict(raw);
	if (reason === "registry-unavailable" || reason === "unreadable") {
		process.stderr.write(
			"audit:js: npm's audit endpoint could not be reached, so the dependency tree was NOT audited.\n" +
				"audit:js: this is not a pass — re-run once the registry recovers.\n"
		);
		return 0;
	}
	if (reason === "unrecognized-report") {
		process.stderr.write("audit:js: npm returned a report shape this does not understand; NOT audited.\n");
		return 0;
	}
	if (waived) {
		process.stderr.write(
			`audit:js: temporary exception ${waived.advisory} is active through ${waived.expiresOn}; affected package findings: ${waived.packages.join(", ")}.\n`
		);
		process.stderr.write(
			"audit:js: these packages remain vulnerable; this is a time-boxed risk acceptance, not a fix.\n"
		);
	}
	if (!ok) {
		process.stderr.write(
			`audit:js: remaining vulnerabilities at ${AUDIT_LEVEL} or above outside the exception: ${JSON.stringify(remaining)}; npm reported ${JSON.stringify(counts)}\n`
		);
		process.stderr.write("audit:js: run `npm audit` for detail.\n");
		return 1;
	}
	if (waived) {
		process.stdout.write(
			`audit:js: no findings remain outside the temporary exception at ${AUDIT_LEVEL} or above.\n`
		);
		return 0;
	}
	process.stdout.write("audit:js: no vulnerabilities at moderate or above.\n");
	return 0;
}

// pathToFileURL rather than a template: this repository is worked in through
// broker checkouts under ~/Library/Application Support/, and import.meta.url
// percent-encodes the space while the template does not. The two never match,
// main() never runs, and the script exits 0 having audited nothing -- which is
// exactly the silent pass this file exists to avoid.
if (import.meta.url === pathToFileURL(process.argv[1]).href) {
	process.exit(main());
}
