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
	evolved_curation: () => t("sourceMark.curation", "a reviewed Toolhub Evolved correction"),
	llm_inference: () => t("sourceMark.inference", "read off the source code by a language model")
};

/**
 * What a language model read, where the source alone does not say.
 *
 * Both inference lanes publish under `llm_inference`, because both are the same
 * kind of claim and the projection ranks them alike. They do not read the same
 * thing: a user script's answer comes from its source code, and a gadget's from
 * the description its wiki shows -- `wiki_gadgets` stores no source to read. One
 * label for both would have told roughly 10,000 gadget keywords that they came
 * from source code that was never opened, which is exactly the confusion the
 * mark exists to prevent.
 */
const INFERENCE_LANE_LABELS = {
	gadget: () => t("sourceMark.inferenceGadget", "read off the gadget's own description by a language model")
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
	return markFor(effectiveRow(provenance[field]));
}

/**
 * Return the mark for one value inside a list field, or "" when a maintainer supplied it.
 *
 * `sourceMark` answers for a whole field, which is right while a field has one
 * source. `keywords` no longer does: below `KEYWORD_FILL_FLOOR` the projection
 * lets inference extend a list somebody else started, so one list can hold a
 * maintainer's word and a model's side by side. A per-field mark cannot say
 * that -- it resolves to whichever row won the field, which is the maintainer's,
 * and would print no mark at all while displaying the model's words as theirs.
 *
 * Values are matched the way the projection folds them, so the mark follows the
 * value rather than its casing.
 *
 * @param {string} field toolinfo field name, e.g. `keywords`
 * @param {unknown} value the single displayed value
 * @param {Record<string, any> | null | undefined} projection
 * @returns {string}
 */
export function valueMark(field, value, projection) {
	const provenance = projection?.provenance;
	if (!provenance || typeof provenance !== "object") return "";
	const rows = provenance[field];
	if (!Array.isArray(rows)) return "";
	const wanted = String(value ?? "")
		.trim()
		.toLowerCase();
	if (!wanted) return "";
	const row = rows.find(
		(candidate) =>
			candidate &&
			candidate.effective &&
			String(candidate.value ?? "")
				.trim()
				.toLowerCase() === wanted
	);
	return markFor(row);
}

/**
 * Render the footnote for one provenance row, or "" when it is a maintainer's.
 *
 * @param {Record<string, any> | null | undefined} row
 */
function markFor(row) {
	const source = row && typeof row.source === "string" ? row.source : "";
	if (!source || TOOLINFO_SOURCES.has(source)) return "";
	// Scoped to the inference source rather than read off any row that happens
	// to carry a lane: `lane` describes which text a model was given, so a
	// future transcribing source that recorded one would otherwise inherit a
	// sentence about a language model that never ran.
	const lane = source === "llm_inference" && row && typeof row.lane === "string" ? row.lane : "";
	const describe =
		/** @type {Record<string, () => string>} */ (INFERENCE_LANE_LABELS)[lane] ||
		/** @type {Record<string, () => string>} */ (DERIVED_LABELS)[source];
	const origin = describe ? describe() : source;
	const label = t("sourceMark.aria", "Not from a toolinfo.json: $1", origin);
	return `<sup class="source-mark" role="note" title="${esc(label)}" aria-label="${esc(label)}">†</sup>`;
}
