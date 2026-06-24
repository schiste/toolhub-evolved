// SPDX-License-Identifier: GPL-3.0-or-later
import { apiGet, normalizeTool } from "./api.js";

let allToolsPromise = null;
let similarityIndexPromise = null;

async function fetchAllTools() {
	const out = [];
	for (let page = 1; page <= 10; page++) {
		let data;
		try {
			data = await apiGet("/search/tools/", { page_size: "100", page: String(page) });
		} catch (e) {
			break;
		}
		const results = data.results || [];
		for (const r of results) out.push(normalizeTool(r));
		if (!data.next || results.length === 0) break;
	}
	return out;
}

export function loadAllTools() {
	if (!allToolsPromise) allToolsPromise = fetchAllTools().catch(() => []);
	return allToolsPromise;
}

/* How much each facet contributes to "closeness". tasks/keywords describe what a
   tool DOES (weighted highest); forWikis is scope; audience/type are coarser.
   This is the main knob for tuning what "similar" means. */
export const FACET_WEIGHTS = { task: 1.4, keyword: 1.0, wiki: 0.8, audience: 0.6, type: 0.5 };

const TERM_FACETS = {
	task: "task",
	kw: "keyword",
	wiki: "wiki",
	aud: "audience",
	type: "type",
};

function facetOf(term) {
	const prefix = term.slice(0, term.indexOf(":"));
	return TERM_FACETS[prefix];
}

function normalizedTermValue(value) {
	return String(value == null ? "" : value).trim().toLowerCase();
}

function pushTerms(out, seen, prefix, values, opts) {
	for (const raw of values || []) {
		const value = normalizedTermValue(raw);
		if (!value || (opts && opts.skipAllWikis && value === "*")) continue;
		const term = prefix + ":" + value;
		if (seen.has(term)) continue;
		seen.add(term);
		out.push(term);
	}
}

function termsOf(tool) {
	const out = [];
	const seen = new Set();
	pushTerms(out, seen, "task", tool.tasks);
	pushTerms(out, seen, "kw", tool.keywords);
	pushTerms(out, seen, "wiki", tool.forWikis, { skipAllWikis: true });
	pushTerms(out, seen, "aud", tool.audiences);
	const type = normalizedTermValue(tool.toolType);
	if (type) pushTerms(out, seen, "type", [type]);
	return out;
}

function idf(term, index) {
	const n = Math.max(index.N || 0, 1);
	const df = index.df.get(term) || 0;
	return Math.log(n / (1 + df)) + 1;
}

function normalizeVector(vector) {
	let magnitude = 0;
	for (const value of vector.values()) magnitude += value * value;
	magnitude = Math.sqrt(magnitude);
	if (!magnitude) return vector;
	for (const [term, value] of vector) vector.set(term, value / magnitude);
	return vector;
}

export function vectorFor(tool, index) {
	const vector = new Map();
	for (const term of termsOf(tool)) {
		const facet = facetOf(term);
		const facetWeight = FACET_WEIGHTS[facet] || 1;
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

export function getSimilarityIndex() {
	if (!similarityIndexPromise) similarityIndexPromise = buildSimilarityIndex();
	return similarityIndexPromise;
}

export function cosine(vecA, vecB) {
	const small = vecA.size <= vecB.size ? vecA : vecB;
	const large = small === vecA ? vecB : vecA;
	let score = 0;
	for (const [term, weight] of small) {
		const other = large.get(term);
		if (other) score += weight * other;
	}
	return Math.max(0, Math.min(1, score));
}

function labelOf(term) {
	const i = term.indexOf(":");
	return i === -1 ? term : term.slice(i + 1);
}

function sharedTermsForVector(sourceVec, otherName, index) {
	const otherVec = index.vectors.get(otherName);
	if (!otherVec) return [];
	const small = sourceVec.size <= otherVec.size ? sourceVec : otherVec;
	const large = small === sourceVec ? otherVec : sourceVec;
	const shared = [];
	for (const [term, weight] of small) {
		const other = large.get(term);
		if (!other) continue;
		shared.push({ label: labelOf(term), weight: weight + other });
	}
	shared.sort((a, b) => b.weight - a.weight || a.label.localeCompare(b.label));
	return shared.slice(0, 5).map((item) => item.label);
}

export function sharedTerms(tool, otherName, index) {
	return sharedTermsForVector(vectorFor(tool, index), otherName, index);
}

export function nearestNeighbors(tool, index, k = 6) {
	const sourceVec = vectorFor(tool, index);
	if (!sourceVec.size) return [];
	const out = [];
	const seen = new Set();
	for (const other of index.tools) {
		if (!other || other.name === tool.name || seen.has(other.name)) continue;
		seen.add(other.name);
		const otherVec = index.vectors.get(other.name);
		if (!otherVec || !otherVec.size) continue;
		const score = cosine(sourceVec, otherVec);
		if (score <= 0) continue;
		out.push({ tool: other, score, shared: sharedTermsForVector(sourceVec, other.name, index) });
	}
	out.sort((a, b) => b.score - a.score || (a.tool.title || a.tool.name).localeCompare(b.tool.title || b.tool.name));
	return out.slice(0, k);
}
