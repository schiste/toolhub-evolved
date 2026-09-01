// SPDX-License-Identifier: GPL-3.0-or-later
// Generate public_html/i18n/en.json from the sources: every `t("key", "English...")`
// or `tWithElements("key", "English...")` call IS the English catalog, so the
// shipped file can never drift from the code.
//   node tools/i18n-extract.mjs          rewrite en.json
//   node tools/i18n-extract.mjs --check  fail (exit 1) if en.json is stale (CI)
import { readdirSync, readFileSync, mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import * as espree from "espree";

export const MESSAGE_KEY_PATTERN = /^[a-z][A-Za-z0-9]*(?:\.[a-z][A-Za-z0-9]*)+$/;
/** Banana positional parameter, e.g. `$1`. */
const BANANA_PARAM = /\$(\d+)/g;
/** Named `{placeholder}` — the pre-banana syntax, now only ever literal text. */
const NAMED_PLACEHOLDER = /\{([A-Za-z][A-Za-z0-9]*)}/g;
/** Magic-word head, e.g. the `PLURAL` in `{{PLURAL:$1|…}}`. */
const MAGIC_WORD = /\{\{([A-Za-z]+)\s*:/g;
/** Only what lib/core/i18n.js implements; anything else would render verbatim. */
const SUPPORTED_MAGIC_WORDS = new Set(["plural", "bidi"]);
const PROSE_FRAGMENT_KEY = /(?:Body|Copy|Description|Intro|Note|Sentence)(?:Before|After)$/;
const TRANSLATION_CALLS = new Set(["t", "tWithElements"]);
const HTML_I18N_ATTRS = [
	["aria-label", "data-i18n-aria-label"],
	["placeholder", "data-i18n-placeholder"],
	["title", "data-i18n-title"]
];
const HTML_TAG = /<([A-Za-z][\w:-]*)(?:"[^"]*"|'[^']*'|[^'">])*>/g;
const HTML_ATTR = /\s([:\w-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')/g;
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SRC = path.join(ROOT, "public_html");
const I18N_DIR = path.join(SRC, "i18n");
const OUT = path.join(I18N_DIR, "en.json");
/** Message documentation for translators; translatewiki requires it. */
const QQQ = path.join(I18N_DIR, "qqq.json");
/** Generated so shipping a locale is a data change, not a code change. */
const LOCALES = path.join(I18N_DIR, "locales.js");
/** Explicit evidence of human review for shipped translations. */
const REVIEW = path.join(ROOT, ".i18n-review.json");
const LEGACY_DOC_STUB = "TODO: document this message.";
/**
 * How many messages may still carry a legacy stub instead of documentation.
 * This is held at zero: generated context gives each new key a useful baseline,
 * and translators can replace that baseline with more specific human guidance.
 */
const DOCUMENTATION_DEBT = 0;

/** @returns {string[]} all first-party app sources with extractable messages */
function sourceFiles(dir) {
	return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
		const full = path.join(dir, entry.name);
		if (entry.isDirectory()) return sourceFiles(full);
		return entry.name.endsWith(".js") || entry.name.endsWith(".html") ? [full] : [];
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
 * The distinct banana parameter indices a message uses, ascending: `"$2 of $1"`
 * yields `[1, 2]`.
 * @param {string} text
 * @returns {number[]}
 */
export function messageParameters(text) {
	return [...new Set([...text.matchAll(BANANA_PARAM)].map((match) => Number(match[1])))].sort((a, b) => a - b);
}

/** @param {unknown} catalog @returns {Record<string, unknown>} */
function catalogMessages(catalog) {
	if (!catalog || typeof catalog !== "object" || Array.isArray(catalog)) return {};
	return Object.fromEntries(Object.entries(catalog).filter(([key]) => !key.startsWith("@")));
}

/**
 * Require every shipped translation to cover exactly the English key set and
 * preserve banana parameters. Partial translatewiki exports stay unshipped and
 * use English fallback until they are complete.
 * @param {Record<string, string>} source
 * @param {unknown} translated
 * @param {string} locale
 */
export function validateLocaleCatalog(source, translated, locale) {
	const messages = catalogMessages(translated);
	const sourceKeys = Object.keys(source);
	const missing = sourceKeys.filter((key) => typeof messages[key] !== "string" || messages[key] === "");
	const extra = Object.keys(messages).filter((key) => !Object.prototype.hasOwnProperty.call(source, key));
	const problems = [];
	if (missing.length > 0) {
		problems.push(
			`${locale}.json is missing ${missing.length}/${sourceKeys.length} source messages: ${missing.slice(0, 10).join(", ")}`
		);
	}
	if (extra.length > 0) {
		problems.push(`${locale}.json has ${extra.length} unknown messages: ${extra.slice(0, 10).join(", ")}`);
	}
	for (const key of sourceKeys) {
		if (typeof messages[key] !== "string" || messages[key] === "") continue;
		const expected = messageParameters(source[key]);
		const actual = messageParameters(messages[key]);
		if (expected.join(",") !== actual.join(",")) {
			problems.push(
				`${locale}.json message "${key}" parameters differ: expected ${expected.map((n) => `$${n}`).join(", ") || "none"}, got ${actual.map((n) => `$${n}`).join(", ") || "none"}`
			);
		}
	}
	return problems;
}

/**
 * Validate the auditable list of translation pairs a human has reviewed.
 * @param {unknown} manifest
 * @param {Record<string, string>} source
 * @param {Record<string, Record<string, unknown>>} locales
 */
export function validateReviewManifest(manifest, source, locales) {
	const problems = [];
	if (!manifest || typeof manifest !== "object" || Array.isArray(manifest)) {
		return [".i18n-review.json must be an object"];
	}
	if (manifest.version !== 1) problems.push(".i18n-review.json version must be 1");
	if (!Array.isArray(manifest.reviewed)) return [...problems, ".i18n-review.json reviewed must be an array"];
	const seen = new Set();
	for (const [index, record] of manifest.reviewed.entries()) {
		const label = `.i18n-review.json reviewed[${index}]`;
		if (!record || typeof record !== "object" || Array.isArray(record)) {
			problems.push(`${label} must be an object`);
			continue;
		}
		const { locale, key, reviewedAt, reviewedBy } = record;
		const pair = `${locale}:${key}`;
		if (seen.has(pair)) problems.push(`${label} duplicates ${pair}`);
		seen.add(pair);
		if (!Object.prototype.hasOwnProperty.call(locales, locale)) {
			problems.push(`${label} names unshipped locale ${locale}`);
		}
		if (!Object.prototype.hasOwnProperty.call(source, key)) problems.push(`${label} names unknown message ${key}`);
		if (typeof locales[locale]?.[key] !== "string") problems.push(`${label} names untranslated pair ${pair}`);
		if (typeof reviewedBy !== "string" || reviewedBy.trim() === "") problems.push(`${label} needs reviewedBy`);
		if (typeof reviewedAt !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(reviewedAt)) {
			problems.push(`${label} needs reviewedAt in YYYY-MM-DD form`);
		}
	}
	return problems;
}

/**
 * @param {string} key
 * @param {string} fallback
 * @returns {string[]}
 */
export function validateMessageShape(key, fallback, argCount) {
	const problems = [];
	if (!MESSAGE_KEY_PATTERN.test(key)) {
		problems.push(
			`t("${key}") key must be dot-separated ASCII, e.g. "apiExplorer.runRequest"; keep it stable for translatewiki.`
		);
	}
	if (PROSE_FRAGMENT_KEY.test(key)) {
		problems.push(`t("${key}") looks like a split prose fragment; use one whole source message with placeholders.`);
	}
	if (/<\/?[A-Za-z][^>]*>/.test(fallback)) {
		problems.push(
			`t("${key}") fallback contains HTML; keep markup outside messages or move prose to locale fragments.`
		);
	}
	for (const match of fallback.matchAll(MAGIC_WORD)) {
		if (!SUPPORTED_MAGIC_WORDS.has(match[1].toLowerCase())) {
			problems.push(
				`t("${key}") uses {{${match[1]}:…}}, which lib/core/i18n.js does not implement — it would render verbatim.`
			);
		}
	}
	const params = messageParameters(fallback);
	params.forEach((index, position) => {
		if (index !== position + 1) {
			problems.push(
				`t("${key}") parameters must run $1..$n without gaps; got ${params.map((p) => `$${p}`).join(", ")}.`
			);
		}
	});
	// Only call sites know how many arguments are supplied; data-i18n cannot pass any.
	if (typeof argCount === "number") {
		const highest = params.at(-1) ?? 0;
		if (highest !== argCount) {
			problems.push(
				`t("${key}") uses ${highest === 0 ? "no parameters" : `$1..$${highest}`} but is called with ${argCount} argument(s).`
			);
		}
		// `{name}` is literal text in banana, so it is only a mistake where a value was meant.
		if (argCount > 0) {
			for (const named of fallback.matchAll(NAMED_PLACEHOLDER)) {
				problems.push(
					`t("${key}") still has the pre-banana placeholder "{${named[1]}}"; use a positional $n parameter.`
				);
			}
		}
	}
	return problems;
}

/** @param {string} text */
function htmlDecode(text) {
	return text.replaceAll(/&(#x[\dA-Fa-f]+|#\d+|[A-Za-z]+);/g, (raw, entity) => {
		if (entity.startsWith("#x")) return String.fromCodePoint(Number.parseInt(entity.slice(2), 16));
		if (entity.startsWith("#")) return String.fromCodePoint(Number.parseInt(entity.slice(1), 10));
		return { amp: "&", gt: ">", lt: "<", nbsp: " ", quot: '"' }[entity] || raw;
	});
}

/** @param {string} text @param {number} index */
function lineAt(text, index) {
	return text.slice(0, index).split("\n").length;
}

/** @param {string} tag */
function tagAttributes(tag) {
	const attrs = /** @type {Record<string, string>} */ ({});
	for (const match of tag.matchAll(HTML_ATTR)) attrs[match[1]] = htmlDecode(match[2] ?? match[3] ?? "");
	return attrs;
}

/**
 * @param {string} source
 * @param {string} tagName
 * @param {number} afterOpen
 */
function simpleTextFallback(source, tagName, afterOpen) {
	const close = new RegExp(`</${tagName}\\s*>`, "i").exec(source.slice(afterOpen));
	if (!close) return "";
	return htmlDecode(
		source
			.slice(afterOpen, afterOpen + close.index)
			.replaceAll(/<[^>]+>/g, "")
			.trim()
	);
}

/**
 * @param {Record<string, string>} catalog
 * @param {string[]} problems
 * @param {string} loc
 * @param {string} key
 * @param {string} fallback
 */
function addMessage(catalog, problems, loc, key, fallback, argCount) {
	for (const problem of validateMessageShape(key, fallback, argCount)) {
		problems.push(`${loc}: ${problem}`);
	}
	const existing = catalog[key];
	if (existing !== undefined && existing !== fallback) {
		problems.push(`${loc}: key "${key}" has two different fallbacks`);
		return;
	}
	catalog[key] = fallback;
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
		if (rel.endsWith(".html")) {
			for (const match of source.matchAll(HTML_TAG)) {
				const tag = match[0];
				const attrs = tagAttributes(tag);
				const loc = `${rel}:${lineAt(source, match.index ?? 0)}`;
				if (attrs["data-i18n"]) {
					const fallback =
						attrs["data-i18n-fallback"] ||
						simpleTextFallback(source, match[1], (match.index ?? 0) + tag.length);
					if (fallback) {
						addMessage(catalog, problems, loc, attrs["data-i18n"], fallback);
					} else {
						problems.push(`${loc}: data-i18n="${attrs["data-i18n"]}" without text or data-i18n-fallback`);
					}
				}
				for (const [target, keyAttr] of HTML_I18N_ATTRS) {
					if (!attrs[keyAttr]) continue;
					if (attrs[target]) {
						addMessage(catalog, problems, loc, attrs[keyAttr], attrs[target]);
					} else {
						problems.push(`${loc}: ${keyAttr}="${attrs[keyAttr]}" without ${target} fallback`);
					}
				}
			}
			continue;
		}
		const ast = espree.parse(source, { ecmaVersion: "latest", sourceType: "module", loc: true });
		walk(ast, (node) => {
			if (
				node.type !== "CallExpression" ||
				node.callee?.type !== "Identifier" ||
				!TRANSLATION_CALLS.has(node.callee.name)
			) {
				return;
			}
			const [keyArg, fallbackArg] = node.arguments;
			const loc = `${rel}:${node.loc?.start.line ?? "?"}`;
			if (keyArg?.type !== "Literal" || typeof keyArg.value !== "string") {
				problems.push(`${loc}: ${node.callee.name}() call with a non-literal key`);
				return;
			}
			if (fallbackArg?.type !== "Literal" || typeof fallbackArg.value !== "string") {
				problems.push(`${loc}: ${node.callee.name}("${keyArg.value}") without a literal English fallback`);
				return;
			}
			addMessage(catalog, problems, loc, keyArg.value, fallbackArg.value, node.arguments.length - 2);
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

/**
 * Read a catalog's `@metadata` so regenerating never discards the author list
 * translatewiki maintains there.
 * @param {string} file
 * @param {string} locale
 */
function existingMetadata(file, locale) {
	const base = { authors: /** @type {string[]} */ ([]), locale, "message-documentation": "qqq" };
	try {
		const parsed = JSON.parse(readFileSync(file, "utf8"));
		const meta = parsed?.["@metadata"];
		if (meta && typeof meta === "object") return { ...base, ...meta, locale, "message-documentation": "qqq" };
	} catch {
		// No catalog yet, or unreadable — the defaults above are correct.
	}
	return base;
}

/** @param {string} file @returns {Record<string, string>} */
function existingDocs(file) {
	try {
		const parsed = JSON.parse(readFileSync(file, "utf8"));
		if (!parsed || typeof parsed !== "object") return {};
		return Object.fromEntries(
			Object.entries(parsed).filter(([key, value]) => !key.startsWith("@") && typeof value === "string")
		);
	} catch {
		return {};
	}
}

/**
 * @param {Record<string, string>} catalog
 * @param {Record<string, unknown>} [metadata]
 */
export function renderCatalog(catalog, metadata) {
	const body = metadata
		? { "@metadata": metadata, ...sortedCatalog(catalog) }
		: /** @type {Record<string, unknown>} */ (sortedCatalog(catalog));
	return `${JSON.stringify(body, null, "\t")}\n`;
}

/** Turn camelCase and identifier punctuation into short translator-facing prose. */
export function messageKeyContext(key) {
	return key
		.split(".")
		.map((part) =>
			part
				.replaceAll(/([a-z\d])([A-Z])/g, "$1 $2")
				.replaceAll(/[-_]+/g, " ")
				.toLowerCase()
		)
		.join(" › ");
}

/**
 * A deterministic baseline for qqq. It names the interface and purpose from
 * the stable key, then points parameter documentation at the exact English
 * sentence whose value is substituted. Human-written qqq always wins.
 */
export function messageDocumentation(key, fallback) {
	const [area, ...purposeParts] = messageKeyContext(key).split(" › ");
	const purpose = purposeParts.join(" › ") || area;
	const source = fallback.replaceAll(/\s+/g, " ").trim();
	const params = messageParameters(fallback);
	const summary = `Message shown in the ${area} interface for ${purpose}.`;
	if (params.length === 0) return summary;
	return `${summary}\n\nParameters:\n${params
		.map((index) => `* $${index} - Value substituted for $${index} in the source message “${source}”.`)
		.join("\n")}`;
}

/**
 * Documentation catalog: keep whatever a human already wrote and generate a
 * translator-facing baseline for missing or legacy-stubbed entries.
 * @param {Record<string, string>} catalog
 * @param {Record<string, string>} current
 * @returns {Record<string, string>}
 */
export function renderDocsCatalog(catalog, current) {
	/** @type {Record<string, string>} */
	const docs = {};
	for (const key of Object.keys(sortedCatalog(catalog))) {
		if (current[key] && !current[key].startsWith(LEGACY_DOC_STUB)) {
			docs[key] = current[key];
			continue;
		}
		docs[key] = messageDocumentation(key, catalog[key]);
	}
	return docs;
}

/** @param {string[]} locales */
export function renderLocalesModule(locales) {
	return `// SPDX-License-Identifier: GPL-3.0-or-later
// GENERATED by tools/i18n-extract.mjs from the catalogs in this directory.
// Do not edit by hand: run \`npm run i18n:extract\`.
//
// One entry per shipped catalog, so adding a translatewiki export is a data
// change rather than a code change. \`qqq\` is message documentation, not a
// locale, and is never listed here.
export const SHIPPED_LOCALES = ${JSON.stringify([...locales].sort())};
`;
}

/** Locale catalog files actually present on disk. */
function localeCatalogFiles() {
	return readdirSync(I18N_DIR, { withFileTypes: true }).filter(
		(entry) => entry.isFile() && entry.name.endsWith(".json") && !new Set(["en.json", "qqq.json"]).has(entry.name)
	);
}

/** Locale catalogs actually present on disk (qqq is documentation, not a locale). */
function shippedLocales() {
	const found = localeCatalogFiles().map((entry) => entry.name.replace(/\.json$/, ""));
	return [...new Set(["en", ...found])];
}

/** @param {Record<string, string>} source */
function localeQuality(source) {
	/** @type {Record<string, Record<string, unknown>>} */
	const locales = {};
	const problems = [];
	for (const entry of localeCatalogFiles()) {
		const locale = entry.name.replace(/\.json$/, "");
		try {
			const parsed = JSON.parse(readFileSync(path.join(I18N_DIR, entry.name), "utf8"));
			locales[locale] = catalogMessages(parsed);
			problems.push(...validateLocaleCatalog(source, parsed, locale));
		} catch (error) {
			problems.push(`${entry.name} is not valid JSON: ${error instanceof Error ? error.message : String(error)}`);
		}
	}
	let manifest;
	try {
		manifest = JSON.parse(readFileSync(REVIEW, "utf8"));
	} catch (error) {
		problems.push(
			`.i18n-review.json is missing or invalid: ${error instanceof Error ? error.message : String(error)}`
		);
	}
	if (manifest !== undefined) problems.push(...validateReviewManifest(manifest, source, locales));
	return { locales, manifest, problems };
}

function main() {
	const { catalog, problems } = extractCatalogFromFiles(sourceFiles(SRC));
	const quality = localeQuality(catalog);
	problems.push(...quality.problems);
	if (problems.length > 0) {
		console.error(`i18n-extract: ${problems.length} problem(s):\n  ${problems.join("\n  ")}`);
		process.exit(1);
	}
	const docs = renderDocsCatalog(catalog, existingDocs(QQQ));
	const outputs = [
		{ file: OUT, label: "en.json", body: renderCatalog(catalog, existingMetadata(OUT, "en")) },
		{ file: QQQ, label: "qqq.json", body: renderCatalog(docs, existingMetadata(QQQ, "qqq")) },
		{ file: LOCALES, label: "locales.js", body: renderLocalesModule(shippedLocales()) }
	];
	const undocumented = Object.keys(docs).filter((key) => docs[key].startsWith(LEGACY_DOC_STUB));

	if (process.argv.includes("--check")) {
		for (const { file, label, body } of outputs) {
			let current = "";
			try {
				current = readFileSync(file, "utf8");
			} catch {
				// missing file -> stale by definition
			}
			if (current !== body) {
				console.error(`i18n-extract: public_html/i18n/${label} is stale - run \`npm run i18n:extract\``);
				process.exit(1);
			}
		}
		// Documentation debt is zero: generated context is mandatory for every key.
		if (undocumented.length > DOCUMENTATION_DEBT) {
			console.error(
				`i18n-extract: ${undocumented.length} messages lack qqq documentation, above the agreed ceiling of ${DOCUMENTATION_DEBT}.\n` +
					`  Document the new key(s) in public_html/i18n/qqq.json, or lower DOCUMENTATION_DEBT if you backfilled some.\n  ${undocumented.slice(0, 10).join("\n  ")}`
			);
			process.exit(1);
		}
		console.log(
			`i18n-extract: en.json in sync (${Object.keys(catalog).length} keys); ` +
				`qqq documented ${Object.keys(docs).length - undocumented.length}/${Object.keys(docs).length}; ` +
				`${Object.keys(quality.locales).length} translated locale(s), ${quality.manifest?.reviewed?.length ?? 0} human-reviewed pair(s)`
		);
		return;
	}
	mkdirSync(I18N_DIR, { recursive: true });
	for (const { file, body } of outputs) writeFileSync(file, body);
	console.log(
		`i18n-extract: wrote ${Object.keys(catalog).length} keys to public_html/i18n/en.json; ` +
			`${undocumented.length} still need qqq documentation`
	);
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) main();
