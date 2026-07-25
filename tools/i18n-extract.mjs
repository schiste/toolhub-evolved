// SPDX-License-Identifier: GPL-3.0-or-later
// Generate public_html/i18n/en.json from the sources: every `t("key", "English…")`
// call IS the English catalog, so the shipped file can never drift from the code.
//   node tools/i18n-extract.mjs          rewrite en.json
//   node tools/i18n-extract.mjs --check  fail (exit 1) if en.json is stale (CI)
import { readdirSync, readFileSync, mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import * as espree from "espree";

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
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
		if (Array.isArray(value)) for (const child of value) walk(child, visit);
		else if (value && typeof value === "object" && typeof value.type === "string") walk(value, visit);
	}
}

const catalog = {};
const problems = [];
for (const file of jsFiles(SRC)) {
	const ast = espree.parse(readFileSync(file, "utf8"), { ecmaVersion: "latest", sourceType: "module" });
	walk(ast, (node) => {
		if (node.type !== "CallExpression" || node.callee?.type !== "Identifier" || node.callee.name !== "t") return;
		const [keyArg, fallbackArg] = node.arguments;
		const rel = path.relative(ROOT, file);
		if (keyArg?.type !== "Literal" || typeof keyArg.value !== "string") {
			problems.push(`${rel}: t() call with a non-literal key (line ${node.loc?.start.line ?? "?"})`);
			return;
		}
		if (fallbackArg?.type !== "Literal" || typeof fallbackArg.value !== "string") {
			problems.push(`${rel}: t("${keyArg.value}") without a literal English fallback`);
			return;
		}
		const existing = catalog[keyArg.value];
		if (existing !== undefined && existing !== fallbackArg.value) {
			problems.push(`${rel}: key "${keyArg.value}" has two different fallbacks`);
			return;
		}
		catalog[keyArg.value] = fallbackArg.value;
	});
}

if (problems.length > 0) {
	console.error(`i18n-extract: ${problems.length} problem(s):\n  ${problems.join("\n  ")}`);
	process.exit(1);
}

const sorted = Object.fromEntries(Object.entries(catalog).sort(([a], [b]) => a.localeCompare(b)));
const body = `${JSON.stringify(sorted, null, "\t")}\n`;

if (process.argv.includes("--check")) {
	let current = "";
	try {
		current = readFileSync(OUT, "utf8");
	} catch {
		// missing file → stale by definition
	}
	if (current !== body) {
		console.error("i18n-extract: public_html/i18n/en.json is stale — run `npm run i18n:extract`");
		process.exit(1);
	}
	console.log(`i18n-extract: en.json is in sync (${Object.keys(sorted).length} keys)`);
} else {
	mkdirSync(path.dirname(OUT), { recursive: true });
	writeFileSync(OUT, body);
	console.log(`i18n-extract: wrote ${Object.keys(sorted).length} keys to public_html/i18n/en.json`);
}
