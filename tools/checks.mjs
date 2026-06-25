#!/usr/bin/env node
// SPDX-License-Identifier: GPL-3.0-or-later
// Small, focused checks for HTML authored inside index.html and JS template
// literals — things no standard linter covers. The detection is a pure function
// (scanText) covered by tests/unit/checks.test.mjs; this file is intentionally
// tiny, unlike the old bespoke quality.mjs.
import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";

const ANCHOR = /<a\b[^>]*>/gi;
const ATTR = (name) => new RegExp(`\\b${name}\\s*=\\s*["']([^"']*)["']`, "i");

/**
 * @param {string} text
 * @param {string} file
 * @returns {{ file: string, line: number, message: string }[]}
 */
export function scanText(text, file) {
	const issues = [];
	for (const match of text.matchAll(ANCHOR)) {
		const tag = match[0];
		const line = text.slice(0, match.index).split("\n").length;
		if (/\btarget\s*=\s*["']_blank["']/i.test(tag)) {
			const rel = ATTR("rel").exec(tag);
			// A templated rel value (e.g. rel="${EXTERNAL_REL}") is trusted — we can't
			// evaluate the constant statically, but it's set deliberately.
			const ok = rel && (/\bnoopener\b/i.test(rel[1]) || rel[1].includes("${"));
			if (!ok) issues.push({ file, line, message: `external target="_blank" link must set rel="noopener"` });
		}
		const href = ATTR("href").exec(tag);
		if (href && href[1].includes("/#/")) {
			issues.push({
				file,
				line,
				message: `hash-router URL "${href[1]}" is not allowed (use clean History API routes)`
			});
		}
	}
	return issues;
}

function main() {
	const files = execFileSync("git", ["ls-files", "public_html/index.html", "public_html/**/*.js"], {
		encoding: "utf8"
	})
		.split("\n")
		.filter(Boolean);
	const issues = files.flatMap((file) => scanText(readFileSync(file, "utf8"), file));
	for (const issue of issues) console.error(`${issue.file}:${issue.line} ${issue.message}`);
	if (issues.length > 0) {
		console.error(`checks: ${issues.length} link/route issue(s)`);
		process.exit(1);
	}
	console.log("checks: links and routes OK");
}

if (import.meta.url === `file://${process.argv[1]}`) main();
