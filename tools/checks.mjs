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

// ---- A11y: accessible names + safe attributes in HTML templates -----------
// A static complement to the runtime axe pass (smoke.spec) and the interaction
// tests: this checks EVERY template at the source, including views that no smoke
// route ever renders. It mirrors how the production Toolhub sources accessible-
// name text from translatewiki — an interpolated name (e.g.
// aria-label="${i18n('message-close')}") is a message lookup and counts as
// present, so this verifies STRUCTURE, never the words. Heading order is
// deliberately NOT checked here: it is a rendered document-order property that a
// per-template scan cannot judge without false positives (this SPA composes each
// page from many fragments), and axe's best-practice heading-order rule already
// covers it at runtime.
const ANY_TAG = /<(\/?)([A-Za-z][\dA-Za-z]*)((?:"[^"]*"|'[^']*'|[^"'>])*)\/?>/g;
const BUTTON_EL = /<button\b((?:"[^"]*"|'[^']*'|[^"'>])*)>([\S\s]*?)<\/button\s*>/gi;
const ANCHOR_EL = /<a\b((?:"[^"]*"|'[^']*'|[^"'>])*)>([\S\s]*?)<\/a\s*>/gi;
const ICON_INTERPOLATION = /\${\s*icon\s*\([^}]*\)\s*}/g;
const CHILD_TAG = /<[^>]*>/g;
const NAME_ATTR = /\b(?:aria-label|aria-labelledby|title)\s*=/i;
// input types that carry their own name (value/none) and need no label.
const SELF_NAMED_INPUTS = new Set(["hidden", "submit", "button", "reset"]);

function lineAt(text, index) {
	return text.slice(0, index).split("\n").length;
}
function attrValue(attrs, name) {
	const m = new RegExp(`\\b${name}\\s*=\\s*["']([^"']*)["']`, "i").exec(attrs);
	return m ? m[1] : null;
}

/**
 * Static accessibility checks over HTML authored in index.html and JS template
 * literals: img alt, labelled form controls, no positive tabindex, named
 * icon-only controls. Accessible names may be literal or interpolated.
 * @param {string} text
 * @param {string} file
 * @returns {{ file: string, line: number, message: string }[]}
 */
export function scanA11y(text, file) {
	const issues = [];
	// Pass 1: ids that an explicit <label for="X"> points at (the for/id pattern).
	const labelFor = new Set();
	for (const m of text.matchAll(ANY_TAG)) {
		if (m[1] || m[2].toLowerCase() !== "label") continue;
		const target = attrValue(m[3], "for");
		if (target) labelFor.add(target);
	}
	// Pass 2: walk tags in order, tracking <label> wrapping depth (implicit names).
	let labelDepth = 0;
	for (const m of text.matchAll(ANY_TAG)) {
		const closing = Boolean(m[1]);
		const tag = m[2].toLowerCase();
		const attrs = m[3] || "";
		if (tag === "label") {
			labelDepth = Math.max(0, labelDepth + (closing ? -1 : 1));
			continue;
		}
		if (closing) continue;
		const line = lineAt(text, m.index);
		const tabindex = attrValue(attrs, "tabindex");
		if (tabindex !== null && Number(tabindex) > 0) {
			issues.push({ file, line, message: `positive tabindex="${tabindex}" — use 0 or -1 to keep DOM order` });
		}
		if (tag === "img" && !/\balt\s*=/i.test(attrs)) {
			issues.push({ file, line, message: `<img> needs an alt attribute (alt="" if decorative)` });
			continue;
		}
		if (tag === "input" || tag === "select" || tag === "textarea") {
			const type = (attrValue(attrs, "type") || "").toLowerCase();
			if (tag === "input" && SELF_NAMED_INPUTS.has(type)) continue;
			const id = attrValue(attrs, "id");
			const named = NAME_ATTR.test(attrs) || labelDepth > 0 || (id !== null && labelFor.has(id));
			if (!named) {
				issues.push({
					file,
					line,
					message: `<${tag}> needs an accessible name (wrap in <label>, add aria-label, or a <label for>)`
				});
			}
		}
	}
	// Icon-only controls: a literal <button>/<a> whose only content is an icon().
	// (The button/iconButton atoms emit a dynamic <${tag}> and already guarantee a
	// name, so they are not matched here — only hand-rolled tags are.)
	for (const [ctl, re] of [
		["button", BUTTON_EL],
		["a", ANCHOR_EL]
	]) {
		for (const m of text.matchAll(re)) {
			const attrs = m[1] || "";
			if (NAME_ATTR.test(attrs) || /\baria-hidden\s*=\s*["']true/i.test(attrs)) continue;
			// Strip icon() interpolations and child markup; any leftover text or a
			// non-icon ${…} (likely a visible label) means the control is named.
			const visible = m[2].replaceAll(ICON_INTERPOLATION, "").replaceAll(CHILD_TAG, "");
			if (/\S/.test(visible)) continue;
			issues.push({ file, line: lineAt(text, m.index), message: `icon-only <${ctl}> needs an aria-label` });
		}
	}
	return issues;
}

// ---- Commented-out code ---------------------------------------------------
// AI tends to leave disabled code behind in comments. eslint's no-warning-
// comments rule already bans the warning markers; this catches dead code.
// The signal (a comment line ending in ; { or }) is cheap and matches intent,
// but on its own it false-positives on prose ("url -> { data, ts }") and on the
// JSDoc type annotations this repo now carries (@returns {{…}[]}). So a
// candidate is CONFIRMED only if it actually parses as JavaScript and contains a
// real statement — dead code parses, prose does not. JSDoc (/** … */) is skipped
// outright: it is types, never disabled code.
const CODE_LINE_END = /[;{}]$/;
const CODE_STATEMENTS = new Set([
	"VariableDeclaration",
	"FunctionDeclaration",
	"ClassDeclaration",
	"IfStatement",
	"ForStatement",
	"ForInStatement",
	"ForOfStatement",
	"WhileStatement",
	"DoWhileStatement",
	"SwitchStatement",
	"TryStatement",
	"ThrowStatement",
	"ReturnStatement",
	"BreakStatement",
	"ContinueStatement",
	"ImportDeclaration",
	"ExportNamedDeclaration",
	"ExportDefaultDeclaration",
	"ExportAllDeclaration"
]);
// Expression statements that DO something (vs. a bare identifier/literal/object,
// which is how prose tends to parse when it parses at all).
const ACTING_EXPRESSIONS = new Set([
	"CallExpression",
	"NewExpression",
	"AssignmentExpression",
	"UpdateExpression",
	"AwaitExpression",
	"YieldExpression"
]);

function looksLikeCode(text) {
	// module catches commented import/export; script+globalReturn catches a bare
	// `return …;`. Either parsing cleanly into a real statement means it is code.
	for (const opts of [{ sourceType: "module" }, { sourceType: "script", ecmaFeatures: { globalReturn: true } }]) {
		let tree;
		try {
			tree = espree.parse(text, { ecmaVersion: 2023, ...opts });
		} catch {
			continue;
		}
		let isCode = false;
		walkAst(tree, (node) => {
			if (
				CODE_STATEMENTS.has(node.type) ||
				(node.type === "ExpressionStatement" && ACTING_EXPRESSIONS.has(node.expression?.type))
			) {
				isCode = true;
			}
		});
		if (isCode) return true;
	}
	return false;
}

/**
 * Flag comments that are actually disabled code (eslint owns the warning
 * markers). JSDoc is exempt. Confirmed by parsing, so prose never trips it.
 * @param {string} code
 * @param {string} file
 * @returns {{ file: string, line: number, message: string }[]}
 */
export function scanComments(code, file) {
	const issues = [];
	let tree;
	try {
		tree = espree.parse(code, { ...ESPREE_OPTS, comment: true });
	} catch {
		return issues; // parse errors are eslint's job
	}
	for (const comment of tree.comments || []) {
		if (code.slice(comment.range[0], comment.range[1]).startsWith("/**")) continue; // JSDoc = types
		const lines = comment.value.split("\n").map((l) => l.replace(/^\s*\*?\s?/, "").trimEnd());
		if (!lines.some((l) => CODE_LINE_END.test(l.trim()))) continue; // the cheap signal
		if (!looksLikeCode(lines.join("\n"))) continue; // the parse-confirm
		issues.push({
			file,
			line: comment.loc.start.line,
			message: `commented-out code — delete it (history keeps it); comments should explain, not disable`
		});
	}
	return issues;
}

// ---- Floating promises (unhandled async data calls) -----------------------
// These core functions return a Promise of data the caller MUST consume. Calling
// one as a bare statement (`apiGet("/x");`) drops the result and silently
// swallows rejections — a real, hard-to-spot bug. Scoped deliberately to the
// data-fetch API: void UI functions (render, refreshHome) are legitimately
// fire-and-forget in event handlers, so flagging them would be the noise the
// gate must avoid. await / return / assignment / .then()/.catch() / `void` all
// satisfy it (a bare `void apiGet(x)` is the explicit fire-and-forget opt-out).
const DATA_FETCHERS = new Set([
	"apiGet",
	"paginate",
	"getTool",
	"getToolsByName",
	"attachEndorsements",
	"egoGraph",
	"toolsByAuthor"
]);

/**
 * Flag floating calls to the async data-fetch API (result dropped, rejection
 * swallowed). await/return/assign/.then/.catch/void all satisfy the check.
 * @param {string} code
 * @param {string} file
 * @returns {{ file: string, line: number, message: string }[]}
 */
export function scanFloating(code, file) {
	const issues = [];
	let tree;
	try {
		tree = espree.parse(code, ESPREE_OPTS);
	} catch {
		return issues; // parse errors are eslint's job
	}
	walkAst(tree, (node) => {
		if (node.type !== "ExpressionStatement" || node.expression?.type !== "CallExpression") return;
		const callee = node.expression.callee;
		if (callee?.type === "Identifier" && DATA_FETCHERS.has(callee.name)) {
			issues.push({
				file,
				line: node.loc.start.line,
				message: `floating promise: ${callee.name}(…) result is dropped — await it, return it, or void it`
			});
		}
	});
	return issues;
}

// ---- HTML well-formedness (balanced tags) ---------------------------------
// Checks that the literal HTML scaffold of each template (and index.html) has
// balanced, properly-nested tags. The trick that keeps this false-positive-free
// in a template-literal codebase: balance only the QUASIS (the literal text),
// replacing every ${…} with an opaque placeholder. So a conditional fragment
// like ${c ? "<div>" : ""} or a nested template lives INSIDE the interpolation
// and never affects balance — only the template's own scaffold is checked. A
// dynamic tag name (<${tag}>) reduces to "< >", which matches no tag and is
// skipped on both ends, so the button/iconButton atoms don't trip it.
const VOID_ELEMENTS = new Set([
	"area",
	"base",
	"br",
	"col",
	"embed",
	"hr",
	"img",
	"input",
	"link",
	"meta",
	"param",
	"source",
	"track",
	"wbr"
]);
const BALANCE_TAG = /<(\/?)([A-Za-z][\dA-Za-z-]*)((?:"[^"]*"|'[^']*'|[^"'>])*?)(\/?)>/g;
const HTML_COMMENT = /<!--[\S\s]*?-->/g;

function unbalancedReason(skeleton) {
	const stack = [];
	for (const m of skeleton.replaceAll(HTML_COMMENT, "").matchAll(BALANCE_TAG)) {
		const tag = m[2].toLowerCase();
		if (VOID_ELEMENTS.has(tag) || m[4]) continue; // void element or self-closing
		if (!m[1]) {
			stack.push(tag);
			continue;
		}
		if (stack.length === 0) return `stray </${tag}>`;
		const open = stack.pop();
		if (open !== tag) return `</${tag}> closes <${open}>`;
	}
	return stack.length > 0 ? `unclosed <${stack[stack.length - 1]}>` : null;
}

/**
 * Flag unbalanced/mis-nested HTML in index.html and in JS template-literal
 * scaffolds (interpolations are treated as opaque, so fragments never trip it).
 * @param {string} code
 * @param {string} file
 * @returns {{ file: string, line: number, message: string }[]}
 */
export function scanBalance(code, file) {
	const issues = [];
	if (!file.endsWith(".js")) {
		const reason = unbalancedReason(code);
		if (reason) issues.push({ file, line: 1, message: `unbalanced HTML: ${reason}` });
		return issues;
	}
	let tree;
	try {
		tree = espree.parse(code, ESPREE_OPTS);
	} catch {
		return issues; // parse errors are eslint's job
	}
	walkAst(tree, (node) => {
		if (node.type !== "TemplateLiteral" || !node.quasis.some((q) => HTML_TAG.test(q.value.raw))) return;
		let skeleton = "";
		node.quasis.forEach((q, i) => {
			skeleton += q.value.raw + (i < node.expressions.length ? "  " : "");
		});
		const reason = unbalancedReason(skeleton);
		if (reason) issues.push({ file, line: node.loc.start.line, message: `unbalanced HTML in template: ${reason}` });
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
	// :(glob) magic makes ** match across path segments INCLUDING zero, so the
	// top-level entry point (public_html/main.js) is covered — a plain
	// "public_html/**/*.js" pathspec silently skips it.
	const files = execFileSync("git", ["ls-files", "public_html/index.html", ":(glob)public_html/**/*.js"], {
		encoding: "utf8"
	})
		.split("\n")
		.filter(Boolean);
	const issues = files.flatMap((file) => {
		const code = readFileSync(file, "utf8");
		const found = [...scanText(code, file), ...scanA11y(code, file), ...scanBalance(code, file)];
		if (file.endsWith(".js")) {
			found.push(...scanTemplates(code, file), ...scanComments(code, file), ...scanFloating(code, file));
		}
		return found;
	});
	for (const issue of issues) console.error(`${issue.file}:${issue.line} ${issue.message}`);
	if (issues.length > 0) {
		console.error(`checks: ${issues.length} issue(s)`);
		process.exit(1);
	}
	console.log("checks: links, routes, HTML escaping/balance, a11y, dead code, and floating promises OK");
}

if (import.meta.url === `file://${process.argv[1]}`) main();
