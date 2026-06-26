#!/usr/bin/env node
// SPDX-License-Identifier: GPL-3.0-or-later
// Small, focused checks for HTML authored inside index.html and JS template
// literals — things no standard linter covers. The detection is a pure function
// (scanText) covered by tests/unit/checks.test.mjs; this file is intentionally
// tiny, unlike the old bespoke quality.mjs.
import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import * as espree from "espree";

const ANCHOR = /<a\b[^>]*>/gi;
const ATTR = (name) => new RegExp(`\\b${name}\\s*=\\s*["']([^"']*)["']`, "i");

// ---- XSS: unescaped interpolation in HTML template literals ----------------
const ESPREE_OPTS = { ecmaVersion: 2023, sourceType: "module", loc: true, range: true };
const HTML_TAG = /<\/?[a-z]/i;
// Free-text record fields that carry untrusted catalog/user data. Interpolating
// one raw (e.g. `${tool.title}`) instead of `${esc(tool.title)}` is the classic
// XSS mistake this gate catches. Internal/config member access (opts.type,
// classes.dot, arr.length) is intentionally NOT flagged — escaping those would
// be noise. This is a targeted tripwire, not full taint analysis.
const RISKY_FIELDS = new Set([
	"title",
	"name",
	"description",
	"label",
	"comment",
	"summary",
	"text",
	"message",
	"content",
	"author",
	"maintainer",
	"url",
	"keyword"
]);

function astChildren(node) {
	const kids = [];
	for (const key of Object.keys(node)) {
		if (key === "loc" || key === "range" || key === "parent") continue;
		const value = node[key];
		if (Array.isArray(value)) {
			for (const child of value) if (child && typeof child.type === "string") kids.push(child);
		} else if (value && typeof value.type === "string") {
			kids.push(value);
		}
	}
	return kids;
}

function walkAst(node, visit) {
	if (!node || typeof node.type !== "string") return;
	visit(node);
	for (const child of astChildren(node)) walkAst(child, visit);
}

// Is this interpolation safe to drop into HTML without esc()? Calls (components/
// helpers escape by contract), bare identifiers (usually pre-built HTML), and
// literals are accepted; raw data access (obj.prop) is the flagged XSS risk.
function isSafeInterpolation(node) {
	if (!node) return true;
	switch (node.type) {
		case "Literal":
		case "TemplateLiteral": // nested templates are validated on their own
		case "TaggedTemplateExpression":
		case "Identifier":
		case "CallExpression":
		case "NewExpression":
			return true;
		case "MemberExpression":
			return !RISKY_FIELDS.has(node.property?.name);
		case "ConditionalExpression":
			return isSafeInterpolation(node.consequent) && isSafeInterpolation(node.alternate);
		case "LogicalExpression":
			return node.operator === "&&"
				? isSafeInterpolation(node.right)
				: isSafeInterpolation(node.left) && isSafeInterpolation(node.right);
		case "BinaryExpression":
			return isSafeInterpolation(node.left) && isSafeInterpolation(node.right);
		default:
			return true; // unknown shapes: don't false-positive
	}
}

/**
 * Flag raw data interpolated into HTML template literals without esc()/a helper.
 * @param {string} code
 * @param {string} file
 * @returns {{ file: string, line: number, message: string }[]}
 */
export function scanTemplates(code, file) {
	const issues = [];
	let tree;
	try {
		tree = espree.parse(code, ESPREE_OPTS);
	} catch {
		return issues; // parse errors are eslint's job
	}
	walkAst(tree, (node) => {
		if (node.type !== "TemplateLiteral" || !node.quasis.some((q) => HTML_TAG.test(q.value.raw))) return;
		for (const expr of node.expressions) {
			if (isSafeInterpolation(expr)) continue;
			const src = code.slice(expr.range[0], expr.range[1]);
			issues.push({
				file,
				line: expr.loc.start.line,
				message: `unescaped interpolation in HTML: \${${src}} — wrap in esc() or a component helper`
			});
		}
	});
	return issues;
}

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
	const issues = files.flatMap((file) => {
		const code = readFileSync(file, "utf8");
		const found = scanText(code, file);
		if (file.endsWith(".js")) found.push(...scanTemplates(code, file));
		return found;
	});
	for (const issue of issues) console.error(`${issue.file}:${issue.line} ${issue.message}`);
	if (issues.length > 0) {
		console.error(`checks: ${issues.length} issue(s)`);
		process.exit(1);
	}
	console.log("checks: links, routes, and HTML escaping OK");
}

if (import.meta.url === `file://${process.argv[1]}`) main();
