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

/** Decide from one `npm audit --json` payload. Returns {ok, reason, counts}. */
export function verdict(raw) {
	let report;
	try {
		report = JSON.parse(raw);
	} catch {
		// Not JSON at all: npm failed before it produced a report. Treat it the
		// same as an explicit endpoint error rather than guessing at the cause.
		return { ok: true, reason: "unreadable", counts: null };
	}
	if (report.error) {
		return { ok: true, reason: "registry-unavailable", counts: null };
	}
	const found = report.metadata?.vulnerabilities;
	if (!found) {
		// A report with no vulnerability metadata is a shape this does not
		// understand; refusing to interpret it is safer than inventing a pass or
		// a fail from it, and it is reported rather than swallowed.
		return { ok: true, reason: "unrecognized-report", counts: null };
	}
	const blocking = BLOCKING.reduce((total, level) => total + (found[level] ?? 0), 0);
	return { ok: blocking === 0, reason: blocking === 0 ? "clean" : "vulnerable", counts: found };
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
	const { ok, reason, counts } = verdict(raw);
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
	if (!ok) {
		process.stderr.write(`audit:js: vulnerabilities at ${AUDIT_LEVEL} or above: ${JSON.stringify(counts)}\n`);
		process.stderr.write("audit:js: run `npm audit` for detail.\n");
		return 1;
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
