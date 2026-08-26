// SPDX-License-Identifier: GPL-3.0-or-later
/**
 * A discreet mark on a field nobody wrote a toolinfo.json for.
 *
 * Most of what this catalogue shows was published by a maintainer: a
 * toolinfo.json somewhere, crawled by Toolhub or found by Evolved. Some of it
 * was not. A user script's documentation link is the page the wiki says exists
 * beside it; a gadget's technologies are the file suffixes it ships. Those are
 * transcriptions of public facts, not guesses, and they are worth showing --
 * but a reader deserves to know which is which without having to open the
 * evidence panel and work it out.
 *
 * So the mark is a footnote dagger and nothing else: no colour, no box, no
 * change to the value beside it. It says "this came from somewhere else, and
 * here is where" and then gets out of the way. A field a maintainer published
 * carries no mark at all, which is the common case and should stay silent.
 */
import { esc } from "../core/dom.js";
import { t } from "../core/i18n.js";

/**
 * Sources that are somebody's published toolinfo.json, one way or another.
 *
 * `official_toolhub` is the record Toolhub holds, which is either a crawled
 * toolinfo.json or one its own form wrote; both are the maintainer speaking.
 * Everything else this codebase knows about was derived here, and is marked.
 */
const TOOLINFO_SOURCES = new Set(["official_toolhub", "official_toolinfo", "self_hosted_toolinfo"]);

/**
 * How each derived source is named to a reader.
 *
 * `evolved_curation` is a person rather than a machine, and is still marked:
 * the rule is where the value came from, not how much to trust it, and a
 * reviewed correction is no more a maintainer's toolinfo.json than a wiki page
 * is. Saying so plainly is what keeps the mark honest for both.
 */
const DERIVED_LABELS = {
	wikimedia_user_script: () => t("sourceMark.userScript", "read from the wiki page beside the script"),
	wiki_gadget_definition: () => t("sourceMark.gadget", "read from the wiki's gadget definition"),
	repository_analysis: () => t("sourceMark.repository", "read from the tool's repository"),
	evolved_curation: () => t("sourceMark.curation", "a reviewed Toolhub Evolved correction")
};

/**
 * Return the row that actually supplied a field's displayed value.
 *
 * The projection marks one row `effective` and keeps the rest as supporting
 * evidence. Where nothing is marked -- an older projection, a field with a
 * single source -- the first row is the one that won, which is the order the
 * projection writes them in.
 *
 * @param {unknown} rows
 */
function effectiveRow(rows) {
	if (!Array.isArray(rows) || rows.length === 0) return null;
	return rows.find((row) => row && row.effective) || rows[0];
}

/**
 * Return a discreet mark for one field, or "" when a maintainer published it.
 *
 * "" is the answer for everything unknown as well as everything published: a
 * field with no provenance recorded is not evidence that it was derived, and
 * marking it would put a footnote on most of the catalogue.
 *
 * @param {string} field toolinfo field name, e.g. `user_docs_url`
 * @param {Record<string, any> | null | undefined} projection
 * @returns {string}
 */
export function sourceMark(field, projection) {
	const provenance = projection?.provenance;
	if (!provenance || typeof provenance !== "object") return "";
	const row = effectiveRow(provenance[field]);
	const source = row && typeof row.source === "string" ? row.source : "";
	if (!source || TOOLINFO_SOURCES.has(source)) return "";
	const describe = /** @type {Record<string, () => string>} */ (DERIVED_LABELS)[source];
	const origin = describe ? describe() : source;
	const label = t("sourceMark.aria", "Not from a toolinfo.json: $1", origin);
	return `<sup class="source-mark" role="note" title="${esc(label)}" aria-label="${esc(label)}">†</sup>`;
}
