// SPDX-License-Identifier: GPL-3.0-or-later
import { normalizeTool, paginate } from "./api.js";
import { memoizeAsync, normStr } from "./util.js";

export const loadAllTools = memoizeAsync(() =>
	// Stryker disable next-line ArrowFunction,ArrayDeclaration: paginate never rejects (it swallows per-page errors), so this defensive .catch(() => []) is unreachable; memoizeAsync also caches the single outcome, so the success and failure paths cannot both be exercised.
	paginate("/search/tools/", {}, { pageSize: 100, maxPages: 10, map: normalizeTool }).catch(() => [])
);

/* How much each facet contributes to "closeness". tasks/keywords describe what a
   tool DOES (weighted highest); forWikis is scope; audience/type are coarser.
   This is the main knob for tuning what "similar" means. */
export const FACET_WEIGHTS = { task: 1.4, keyword: 1.0, wiki: 0.8, audience: 0.6, type: 0.5 };

const TERM_FACETS = {
	task: "task",
	// Stryker disable next-line StringLiteral: blanking maps facetOf("kw:…") to "", whose FACET_WEIGHTS lookup falls back to 1 — identical to the real "keyword" weight of 1.0.
	kw: "keyword",
	wiki: "wiki",
	aud: "audience",
	type: "type"
};

/**
 * @typedef {{ tools: Tool[], byName: Map<string, Tool>, vectors: Map<string, Map<string, number>>, df: Map<string, number>, N: number }} SimIndex
 */

/** @param {string} term */
function facetOf(term) {
	const prefix = term.slice(0, term.indexOf(":"));
	return TERM_FACETS[/** @type {keyof typeof TERM_FACETS} */ (prefix)];
}

/**
 * @param {string[]} out
 * @param {Set<string>} seen
 * @param {string} prefix
 * @param {unknown[] | null | undefined} values
 * @param {{ skipAllWikis?: boolean }} [opts]
 */
function pushTerms(out, seen, prefix, values, opts) {
	for (const raw of values || []) {
		const value = normStr(raw);
		if (!value || (opts && opts.skipAllWikis && value === "*")) continue;
		const term = `${prefix}:${value}`;
		if (seen.has(term)) continue;
		seen.add(term);
		out.push(term);
	}
}

/** @param {Tool} tool */
function termsOf(tool) {
	/** @type {string[]} */
	const out = [];
	/** @type {Set<string>} */
	const seen = new Set();
	pushTerms(out, seen, "task", tool.tasks);
	pushTerms(out, seen, "kw", tool.keywords);
	pushTerms(out, seen, "wiki", tool.forWikis, { skipAllWikis: true });
	pushTerms(out, seen, "aud", tool.audiences);
	const type = normStr(tool.toolType);
	// Stryker disable next-line ConditionalExpression: pushTerms already skips empty values, so calling it unconditionally on an empty type still emits no term (if(true) is equivalent).
	if (type) pushTerms(out, seen, "type", [type]);
	return out;
}

/**
 * @param {string} term
 * @param {SimIndex} index
 */
function idf(term, index) {
	const n = Math.max(index.N || 0, 1);
	const df = index.df.get(term) || 0;
	return Math.log(n / (1 + df)) + 1;
}

/**
 * @param {Map<string, number>} vector
 * @returns {Map<string, number>}
 */
function normalizeVector(vector) {
	let magnitude = 0;
	for (const value of vector.values()) magnitude += value * value;
	magnitude = Math.sqrt(magnitude);
	// Stryker disable next-line ConditionalExpression: magnitude is 0 only for an empty vector, where the normalization loop below is a no-op — so skipping the early return is observationally equivalent.
	if (!magnitude) return vector;
	for (const [term, value] of vector) vector.set(term, value / magnitude);
	return vector;
}

/**
 * @param {Tool} tool
 * @param {SimIndex} index
 * @returns {Map<string, number>}
 */
export function vectorFor(tool, index) {
	/** @type {Map<string, number>} */
	const vector = new Map();
	for (const term of termsOf(tool)) {
		const facet = facetOf(term);
		const facetWeight = FACET_WEIGHTS[/** @type {keyof typeof FACET_WEIGHTS} */ (facet)] || 1;
		vector.set(term, idf(term, index) * facetWeight);
	}
	return normalizeVector(vector);
}

async function buildSimilarityIndex() {
	const tools = await loadAllTools();
	const N = tools.length;
	const df = new Map();
	for (const tool of tools) {
		for (const term of termsOf(tool)) {
			df.set(term, (df.get(term) || 0) + 1);
		}
	}

	const index = { tools, byName: new Map(), vectors: new Map(), df, N };
	for (const tool of tools) {
		index.byName.set(tool.name, tool);
		index.vectors.set(tool.name, vectorFor(tool, index));
	}
	return index;
}

export const getSimilarityIndex = memoizeAsync(buildSimilarityIndex);

/**
 * @param {Map<string, number>} vecA
 * @param {Map<string, number>} vecB
 */
export function cosine(vecA, vecB) {
	// Stryker disable next-line ConditionalExpression,EqualityOperator: smaller/larger selection is a pure performance optimization; the dot product is commutative, so iterating either map yields the identical score.
	const small = vecA.size <= vecB.size ? vecA : vecB;
	const large = small === vecA ? vecB : vecA;
	let score = 0;
	for (const [term, weight] of small) {
		const other = large.get(term);
		if (other) score += weight * other;
	}
	return Math.max(0, Math.min(1, score));
}

/** @param {string} term */
function labelOf(term) {
	const i = term.indexOf(":");
	// Stryker disable next-line ConditionalExpression,UnaryOperator: labelOf only ever receives "prefix:value" terms (fixed facet prefixes), so indexOf(":") is always >= 2; the i === -1 branch is dead and the slice branch is always taken.
	return i === -1 ? term : term.slice(i + 1);
}

/**
 * @param {Map<string, number>} sourceVec
 * @param {string} otherName
 * @param {SimIndex} index
 * @returns {string[]}
 */
function sharedTermsForVector(sourceVec, otherName, index) {
	const otherVec = index.vectors.get(otherName);
	// Stryker disable next-line ConditionalExpression,ArrayDeclaration: nearestNeighbors only calls this after confirming the neighbor has a non-empty vector (line below), so otherVec is always present and the !otherVec guard is dead.
	if (!otherVec) return [];
	// Stryker disable next-line ConditionalExpression,EqualityOperator: smaller/larger selection is a pure optimization; collecting shared terms (with the commutative weight + other) is order-independent.
	const small = sourceVec.size <= otherVec.size ? sourceVec : otherVec;
	// Stryker disable next-line ConditionalExpression,EqualityOperator: smaller/larger selection is a pure optimization; the shared-term set and combined weights are identical either way.
	const large = small === sourceVec ? otherVec : sourceVec;
	/** @type {Array<{ label: string, weight: number }>} */
	const shared = [];
	for (const [term, weight] of small) {
		const other = large.get(term);
		if (!other) continue;
		shared.push({ label: labelOf(term), weight: weight + other });
	}
	shared.sort((a, b) => b.weight - a.weight || a.label.localeCompare(b.label));
	return shared.slice(0, 5).map((item) => item.label);
}

/**
 * @param {Tool} tool
 * @param {SimIndex} index
 * @param {number} [k]
 * @returns {Array<{ tool: Tool, score: number, shared: string[] }>}
 */
export function nearestNeighbors(tool, index, k = 6) {
	const sourceVec = vectorFor(tool, index);
	// Stryker disable next-line ConditionalExpression: an empty source vector makes every cosine 0, which is filtered by the score <= 0 guard below, so the result is [] with or without this early return.
	if (sourceVec.size === 0) return [];
	/** @type {Array<{ tool: Tool, score: number, shared: string[] }>} */
	const out = [];
	/** @type {Set<string>} */
	const seen = new Set();
	for (const other of index.tools) {
		if (!other || other.name === tool.name || seen.has(other.name)) continue;
		seen.add(other.name);
		const otherVec = index.vectors.get(other.name);
		// Stryker disable next-line ConditionalExpression: an empty otherVec yields cosine 0, already filtered by the score <= 0 guard below, so the otherVec.size === 0 short-circuit is a redundant optimization.
		if (!otherVec || otherVec.size === 0) continue;
		const score = cosine(sourceVec, otherVec);
		if (score <= 0) continue;
		out.push({ tool: other, score, shared: sharedTermsForVector(sourceVec, other.name, index) });
	}
	out.sort((a, b) => b.score - a.score || (a.tool.title || a.tool.name).localeCompare(b.tool.title || b.tool.name));
	return out.slice(0, k);
}
