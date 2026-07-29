// SPDX-License-Identifier: GPL-3.0-or-later
// Generate public_html/i18n/en.json from the sources: every `t("key", "English...")`
// call IS the English catalog, so the shipped file can never drift from the code.
//   node tools/i18n-extract.mjs          rewrite en.json
//   node tools/i18n-extract.mjs --check  fail (exit 1) if en.json is stale (CI)
import { readdirSync, readFileSync, mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import * as espree from "espree";

export const MESSAGE_KEY_PATTERN = /^[a-z][A-Za-z0-9]*(?:\.[a-z][A-Za-z0-9]*)+$/;
const PLACEHOLDER_PATTERN = /^[A-Za-z][A-Za-z0-9]*$/;
const PLACEHOLDER = /\{([^}]*)}/g;
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SRC = path.join(ROOT, "public_html");
const OUT = path.join(SRC, "i18n", "en.json");

/** @returns {string[]} all first-party app modules */
function jsFiles(dir) {
	return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
		const full = path.join(dir, entry.name);
		if (entry.isDirectory()) return jsFiles(full);
		return entry.name.endsWith(".js") ? [full] : [];
	});
}

/** Depth-first AST walk (espree nodes are plain objects). */
function walk(node, visit) {
	if (!node || typeof node.type !== "string") return;
	visit(node);
	for (const value of Object.values(node)) {
		if (Array.isArray(value)) {
			for (const child of value) walk(child, visit);
		} else if (value && typeof value === "object" && typeof value.type === "string") {
			walk(value, visit);
		}
	}
}

/**
 * @param {string} text
 * @returns {string[]}
 */
export function messagePlaceholders(text) {
	return [...text.matchAll(PLACEHOLDER)].map((match) => match[1]);
}

/**
 * @param {string} key
 * @param {string} fallback
 * @returns {string[]}
 */
export function validateMessageShape(key, fallback) {
	const problems = [];
	if (!MESSAGE_KEY_PATTERN.test(key)) {
		problems.push(
			`t("${key}") key must be dot-separated ASCII, e.g. "apiExplorer.runRequest"; keep it stable for translatewiki.`
		);
	}
	if (/<\/?[A-Za-z][^>]*>/.test(fallback)) {
		problems.push(
			`t("${key}") fallback contains HTML; keep markup outside messages or move prose to locale fragments.`
		);
	}
	for (const name of messagePlaceholders(fallback)) {
		if (!PLACEHOLDER_PATTERN.test(name)) {
			problems.push(`t("${key}") placeholder "{${name}}" must be a simple named parameter like "{count}".`);
		}
	}
	return problems;
}

/**
 * @param {Record<string, string>} catalog
 * @returns {Record<string, string>}
 */
function sortedCatalog(catalog) {
	return Object.fromEntries(Object.entries(catalog).sort(([a], [b]) => a.localeCompare(b)));
}

/**
 * @param {Iterable<[string, string]>} entries pairs of relative filename and source text
 * @returns {{ catalog: Record<string, string>, problems: string[] }}
 */
export function extractCatalogFromEntries(entries) {
	const catalog = /** @type {Record<string, string>} */ ({});
	const problems = [];
	for (const [rel, source] of entries) {
		const ast = espree.parse(source, { ecmaVersion: "latest", sourceType: "module", loc: true });
		walk(ast, (node) => {
			if (node.type !== "CallExpression" || node.callee?.type !== "Identifier" || node.callee.name !== "t")
				return;
			const [keyArg, fallbackArg] = node.arguments;
			const loc = `${rel}:${node.loc?.start.line ?? "?"}`;
			if (keyArg?.type !== "Literal" || typeof keyArg.value !== "string") {
				problems.push(`${loc}: t() call with a non-literal key`);
				return;
			}
			if (fallbackArg?.type !== "Literal" || typeof fallbackArg.value !== "string") {
				problems.push(`${loc}: t("${keyArg.value}") without a literal English fallback`);
				return;
			}
			for (const problem of validateMessageShape(keyArg.value, fallbackArg.value))
				problems.push(`${loc}: ${problem}`);
			const existing = catalog[keyArg.value];
			if (existing !== undefined && existing !== fallbackArg.value) {
				problems.push(`${loc}: key "${keyArg.value}" has two different fallbacks`);
				return;
			}
			catalog[keyArg.value] = fallbackArg.value;
		});
	}
	return { catalog: sortedCatalog(catalog), problems };
}

/**
 * @param {string[]} files
 * @param {string} [root]
 * @returns {{ catalog: Record<string, string>, problems: string[] }}
 */
export function extractCatalogFromFiles(files, root = ROOT) {
	return extractCatalogFromEntries(files.map((file) => [path.relative(root, file), readFileSync(file, "utf8")]));
}

/** @param {Record<string, string>} catalog */
export function renderCatalog(catalog) {
	return `${JSON.stringify(sortedCatalog(catalog), null, "\t")}\n`;
}

function main() {
	const { catalog, problems } = extractCatalogFromFiles(jsFiles(SRC));
	if (problems.length > 0) {
		console.error(`i18n-extract: ${problems.length} problem(s):\n  ${problems.join("\n  ")}`);
		process.exit(1);
	}
	const body = renderCatalog(catalog);
	if (process.argv.includes("--check")) {
		let current = "";
		try {
			current = readFileSync(OUT, "utf8");
		} catch {
			// missing file -> stale by definition
		}
		if (current !== body) {
			console.error("i18n-extract: public_html/i18n/en.json is stale - run `npm run i18n:extract`");
			process.exit(1);
		}
		console.log(`i18n-extract: en.json is in sync (${Object.keys(catalog).length} keys)`);
		return;
	}
	mkdirSync(path.dirname(OUT), { recursive: true });
	writeFileSync(OUT, body);
	console.log(`i18n-extract: wrote ${Object.keys(catalog).length} keys to public_html/i18n/en.json`);
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) main();
