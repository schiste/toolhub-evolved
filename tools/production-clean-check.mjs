// SPDX-License-Identifier: GPL-3.0-or-later
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { relative, resolve } from "node:path";

const ROOT = resolve(new URL("..", import.meta.url).pathname);

const REMOVED_FILES = ["public_html/lib/core/synth.js", "public_html/lib/atoms/signals.js"];

const CHECKS = [
	{
		path: "public_html",
		patterns: [
			[/SAMPLE_TOOLINFO/g, "bundled sample Toolinfo payload"],
			[/data-sample/g, "sample Toolinfo button"],
			[/Sign in demo/g, "browser-local demo sign-in"],
			[/Reset demo data/g, "browser-local reset control"],
			[/resetDemoData/g, "browser-local reset i18n key"],
			[/signInDemo/g, "browser-local sign-in i18n key"],
			[/sort=views/g, "fake popularity route"],
			[/popularThisWeek/g, "fake popularity sort key"],
			[/pseudo-random/g, "deterministic fake metric copy"],
			[/Deterministic per tool/g, "deterministic fake metric copy"],
			[/shotstrip/g, "placeholder screenshot strip"],
			[/background-shot-placeholder/g, "placeholder screenshot background"],
			[/Screenshots · Evolved preview/g, "placeholder screenshot copy"],
			[/healthBadge/g, "fake health badge"],
			[/popularityBadge/g, "fake popularity badge"],
			[/thanksBlock/g, "fake thanks aggregate"],
			[/usageBlock/g, "fake usage aggregate"],
			[/from ["'][^"']*synth\.js["']/g, "synthetic signal module import"]
		]
	},
	{
		path: "README.md",
		patterns: [
			[/browser-local demo/g, "signed-out demo mode"],
			[/synthetic signals/g, "fake signal production copy"]
		]
	},
	{
		path: "docs/RUNBOOK.md",
		patterns: [[/browser-local demo/g, "signed-out demo mode"]]
	},
	{
		path: "docs/deploy-toolforge.md",
		patterns: [[/browser-local demo/g, "signed-out demo mode"]]
	}
];

/** @param {string} path */
function listFiles(path) {
	const abs = resolve(ROOT, path);
	const stat = existsSync(abs) ? statSync(abs) : null;
	if (!stat) return [];
	if (stat.isFile()) return [abs];
	const files = [];
	for (const entry of readdirSync(abs, { withFileTypes: true })) {
		const child = resolve(abs, entry.name);
		if (entry.isDirectory()) files.push(...listFiles(relative(ROOT, child)));
		else if (entry.isFile()) files.push(child);
	}
	return files;
}

const failures = [];
for (const file of REMOVED_FILES) {
	if (existsSync(resolve(ROOT, file))) failures.push(`${file}: removed fake-data file exists`);
}

for (const check of CHECKS) {
	for (const file of listFiles(check.path)) {
		const rel = relative(ROOT, file);
		const text = readFileSync(file, "utf8");
		for (const [pattern, label] of check.patterns) {
			pattern.lastIndex = 0;
			if (pattern.test(text)) failures.push(`${rel}: ${label}`);
		}
	}
}

if (failures.length > 0) {
	console.error("production-clean-check failed:");
	for (const failure of failures) console.error(`- ${failure}`);
	process.exit(1);
}

console.log("production-clean-check: no production-facing fixtures, demo writes, or fake signal paths found");
