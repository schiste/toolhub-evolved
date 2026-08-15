// SPDX-License-Identifier: GPL-3.0-or-later
import { TOOLINFO_SCHEMA_VERSION, TOOLINFO_TOOL_TYPES } from "./toolinfo-docs.js";

/** @typedef {{ name: string, wiki_username?: string, developer_username?: string, email?: string, url?: string }} ToolinfoAuthor */

export const TOOLINFO_FILENAME = "toolinfo.json";

export const CORE_TOOLINFO_FIELDS = [
	"_schema",
	"_language",
	"name",
	"title",
	"subtitle",
	"description",
	"url",
	"url_alternates",
	"author",
	"repository",
	"openhub_id",
	"bot_username",
	"deprecated",
	"replaced_by",
	"experimental",
	"for_wikis",
	"icon",
	"license",
	"sponsor",
	"available_ui_languages",
	"technology_used",
	"tool_type",
	"api_url",
	"developer_docs_url",
	"user_docs_url",
	"feedback_url",
	"privacy_policy_url",
	"translate_url",
	"bugtracker_url",
	"keywords"
];

const URL_FIELDS = ["url", "repository", "replaced_by", "icon", "api_url", "translate_url", "bugtracker_url"];
const MULTILINGUAL_URL_FIELDS = ["developer_docs_url", "user_docs_url", "feedback_url", "privacy_policy_url"];
const LANGUAGE_PATTERN = /^(x-.*|[A-Za-z]{2,3}(-.*)?)$/;
const WIKI_PATTERN =
	/^(\*|(.*)?\.?(mediawiki|wiktionary|wiki(pedia|quote|books|source|news|versity|data|voyage|media))\.org)$/i;

/** @param {unknown} value */
function clean(value) {
	return String(value ?? "").trim();
}

/** @param {unknown} value */
function list(value) {
	if (Array.isArray(value)) return value.map((item) => clean(item)).filter(Boolean);
	const scalar = clean(value);
	return scalar ? [scalar] : [];
}

/** @param {unknown} value */
function httpUrl(value) {
	try {
		const parsed = new URL(clean(value));
		return parsed.protocol === "http:" || parsed.protocol === "https:";
	} catch {
		return false;
	}
}

/** @param {unknown} value @returns {ToolinfoAuthor | null} */
function person(value) {
	const raw = typeof value === "string" ? { name: value } : value;
	if (!raw || typeof raw !== "object") return null;
	const source = /** @type {Record<string, any>} */ (raw);
	if (!clean(source.name)) return null;
	/** @type {Record<string, string>} */
	const result = { name: clean(source.name) };
	for (const field of ["wiki_username", "developer_username", "email", "url"]) {
		const fieldValue = clean(source[field]);
		if (fieldValue) result[field] = fieldValue;
	}
	return /** @type {ToolinfoAuthor} */ (result);
}

/** @param {unknown} value @returns {ToolinfoAuthor[]} */
export function normalizeToolinfoAuthors(value) {
	const values = Array.isArray(value) ? value : value ? [value] : [];
	/** @type {ToolinfoAuthor[]} */
	const authors = [];
	for (const item of values) {
		const author = person(item);
		if (author) authors.push(author);
	}
	return authors;
}

/** @param {string} projectName */
export function toolforgeToolinfoName(projectName) {
	const project = clean(projectName).replace(/^toolforge-/i, "");
	return project ? `toolforge-${project}` : "";
}

/** @param {string} projectName */
function projectTitle(projectName) {
	return clean(projectName)
		.split(/[-_]+/)
		.filter(Boolean)
		.map((part) => part.charAt(0).toUpperCase() + part.slice(1))
		.join(" ");
}

/**
 * @param {Record<string, any>} record
 * @param {{ projectName?: string, displayName?: string, wikiUsername?: string, developerUsernames?: string[] }} [context]
 */
export function prefillToolinfo(record = {}, context = {}) {
	const projectName = clean(context.projectName);
	/** @type {Record<string, any>} */
	const result = {};
	for (const field of CORE_TOOLINFO_FIELDS) {
		if (record[field] !== undefined && record[field] !== null && record[field] !== "") {
			result[field] = structuredClone(record[field]);
		}
	}
	result._schema = TOOLINFO_SCHEMA_VERSION;
	result._language = clean(record._language) || "en";
	result.name = projectName ? toolforgeToolinfoName(projectName) : clean(record.name);
	result.title = clean(record.title) || projectTitle(projectName || result.name);
	result.description = clean(record.description);
	result.url = clean(record.url) || (projectName ? `https://${projectName}.toolforge.org/` : "");
	result.for_wikis = list(record.for_wikis);
	if (result.for_wikis.length === 0 && projectName) result.for_wikis = ["*"];
	result.available_ui_languages = list(record.available_ui_languages);
	if (result.available_ui_languages.length === 0) result.available_ui_languages = ["en"];
	result.sponsor = list(record.sponsor);
	result.technology_used = list(record.technology_used);
	result.keywords = Array.isArray(record.keywords)
		? record.keywords
				.map((item) => clean(item))
				.filter(Boolean)
				.join(", ")
		: clean(record.keywords);

	const authors = normalizeToolinfoAuthors(record.author);
	const displayName = clean(context.displayName);
	const wikiUsername = clean(context.wikiUsername);
	const developerUsernames = list(context.developerUsernames);
	const developerUsername = developerUsernames.length === 1 ? developerUsernames[0] : "";
	const identityTokens = new Set(
		[displayName, wikiUsername, ...developerUsernames].map((item) => item.toLowerCase()).filter(Boolean)
	);
	let ownAuthor = authors.find((author) =>
		[author.name, author.wiki_username, author.developer_username]
			.map((item) => clean(item).toLowerCase())
			.some((item) => identityTokens.has(item))
	);
	if (!ownAuthor && authors.length === 0 && displayName) {
		ownAuthor = { name: displayName };
		authors.push(ownAuthor);
	}
	if (ownAuthor) {
		if (wikiUsername && !ownAuthor.wiki_username) ownAuthor.wiki_username = wikiUsername;
		if (developerUsername && !ownAuthor.developer_username) ownAuthor.developer_username = developerUsername;
	}
	result.author = authors;
	return result;
}

/** @param {unknown} value */
export function formatMultilingualUrls(value) {
	if (Array.isArray(value)) {
		return value
			.map((item) =>
				item && typeof item === "object" ? `${clean(item.language)} | ${clean(item.url)}` : clean(item)
			)
			.filter(Boolean)
			.join("\n");
	}
	return clean(value);
}

/** @param {string} value */
export function parseMultilingualUrls(value) {
	const lines = String(value || "")
		.split("\n")
		.map((line) => line.trim())
		.filter(Boolean);
	if (lines.length === 0) return "";
	if (lines.length === 1 && !lines[0].includes("|")) return lines[0];
	return lines.map((line) => {
		const separator = line.indexOf("|");
		return separator < 0
			? { language: "en", url: line }
			: { language: line.slice(0, separator).trim(), url: line.slice(separator + 1).trim() };
	});
}

/** @param {Record<string, any>} values */
export function buildToolinfo(values) {
	/** @type {Record<string, any>} */
	const result = {};
	for (const field of CORE_TOOLINFO_FIELDS) {
		const value = values[field];
		const empty =
			value === undefined || value === null || value === "" || (Array.isArray(value) && value.length === 0);
		if (!empty) result[field] = value;
	}
	result._schema = TOOLINFO_SCHEMA_VERSION;
	result._language = clean(values._language) || "en";
	result.name = clean(values.name);
	result.title = clean(values.title);
	result.description = clean(values.description);
	result.url = clean(values.url);
	result.author = normalizeToolinfoAuthors(values.author);
	if (result.author.length === 0) delete result.author;
	if (!values.deprecated) delete result.replaced_by;
	if (!values.deprecated) delete result.deprecated;
	if (!values.experimental) delete result.experimental;
	return result;
}

/** @param {unknown} value */
function multilingualUrls(value) {
	return Array.isArray(value) ? value : value ? [value] : [];
}

/** @param {Record<string, any>} value @param {{ projectName?: string }} [context] */
export function validateToolinfo(value, context = {}) {
	const errors = [];
	for (const field of ["name", "title", "description", "url"]) {
		if (!clean(value[field])) {
			errors.push(`${field} is required.`);
		}
	}
	if (context.projectName && value.name !== toolforgeToolinfoName(context.projectName)) {
		errors.push(`name must be ${toolforgeToolinfoName(context.projectName)} for this Toolforge project.`);
	}
	for (const field of URL_FIELDS) {
		if (value[field] && !httpUrl(value[field])) {
			errors.push(`${field} must be an http(s) URL.`);
		}
	}
	for (const field of ["url_alternates", ...MULTILINGUAL_URL_FIELDS]) {
		for (const item of multilingualUrls(value[field])) {
			const url = typeof item === "string" ? item : item?.url;
			const language = typeof item === "string" ? "" : item?.language;
			if (!httpUrl(url)) {
				errors.push(`${field} contains an invalid URL.`);
			}
			if (language && !LANGUAGE_PATTERN.test(clean(language))) {
				errors.push(`${field} contains an invalid language code.`);
			}
		}
	}
	if (value.icon && !/^https:\/\/commons\.wikimedia\.org\/wiki\/File:.+\..+$/.test(value.icon)) {
		errors.push("icon must be a Wikimedia Commons File: page URL.");
	}
	if (value.tool_type && !TOOLINFO_TOOL_TYPES.includes(value.tool_type)) {
		errors.push("tool_type is not supported by schema 1.2.2.");
	}
	for (const wiki of list(value.for_wikis)) {
		if (!WIKI_PATTERN.test(wiki)) {
			errors.push(`for_wikis contains an invalid target: ${wiki}.`);
		}
	}
	for (const language of [value._language, ...list(value.available_ui_languages)]) {
		if (language !== "*" && !LANGUAGE_PATTERN.test(clean(language))) {
			errors.push(`Invalid language code: ${language}.`);
		}
	}
	for (const author of normalizeToolinfoAuthors(value.author)) {
		if (author.url && !httpUrl(author.url)) {
			errors.push(`Author URL for ${author.name} is invalid.`);
		}
		if (author.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(author.email)) {
			errors.push(`Author email for ${author.name} is invalid.`);
		}
	}
	return [...new Set(errors)];
}

/** @param {Record<string, any>} value */
export function toolinfoJson(value) {
	return `${JSON.stringify(buildToolinfo(value), null, 2)}\n`;
}
