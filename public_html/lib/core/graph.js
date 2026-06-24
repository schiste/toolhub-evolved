// SPDX-License-Identifier: GPL-3.0-or-later
import { cosine, getSimilarityIndex, nearestNeighbors, vectorFor } from "./similarity.js";
import { getTool } from "./api.js";
import { endorsementOf, fitsContext, listMemberships } from "./signals.js";
import { memoizeAsync, normStr } from "./util.js";

const GLOBAL_NODE_LIMIT = 250;
const COMMUNITY_LIMIT = 8;

function sortedPair(a, b) {
	return a < b ? [a, b] : [b, a];
}

export function knnEdges(names, index, k = 4) {
	const nodeNames = Array.from(new Set(names || [])).filter((name) => index.vectors.has(name));
	const edgeMap = new Map();
	for (const source of nodeNames) {
		const sourceVec = index.vectors.get(source);
		if (!sourceVec || !sourceVec.size) continue;
		const scored = [];
		for (const target of nodeNames) {
			if (target === source) continue;
			const targetVec = index.vectors.get(target);
			if (!targetVec || !targetVec.size) continue;
			const weight = cosine(sourceVec, targetVec);
			if (weight <= 0) continue;
			scored.push({ target, weight });
		}
		scored.sort((a, b) => b.weight - a.weight || a.target.localeCompare(b.target));
		for (const edge of scored.slice(0, k)) {
			const [a, b] = sortedPair(source, edge.target);
			const key = a + "\u0000" + b;
			const prev = edgeMap.get(key);
			if (!prev || edge.weight > prev.weight) edgeMap.set(key, { source: a, target: b, weight: edge.weight });
		}
	}
	return Array.from(edgeMap.values()).sort((a, b) => a.source.localeCompare(b.source) || a.target.localeCompare(b.target));
}

export function detectCommunities(nodes, edges) {
	const ids = Array.from(new Set((nodes || []).map((node) => typeof node === "string" ? node : node.id).filter(Boolean))).sort();
	const labels = new Map(ids.map((id) => [id, id]));
	const adjacency = new Map(ids.map((id) => [id, []]));
	for (const edge of edges || []) {
		if (!adjacency.has(edge.source) || !adjacency.has(edge.target)) continue;
		const weight = Number(edge.weight) || 0;
		adjacency.get(edge.source).push({ id: edge.target, weight });
		adjacency.get(edge.target).push({ id: edge.source, weight });
	}

	for (let pass = 0; pass < 8; pass++) {
		let changed = false;
		for (const id of ids) {
			const scores = new Map();
			for (const neighbor of adjacency.get(id) || []) {
				const label = labels.get(neighbor.id);
				scores.set(label, (scores.get(label) || 0) + neighbor.weight);
			}
			let bestLabel = labels.get(id);
			let bestScore = -1;
			for (const [label, score] of scores) {
				if (score > bestScore || (score === bestScore && String(label).localeCompare(String(bestLabel)) < 0)) {
					bestLabel = label;
					bestScore = score;
				}
			}
			if (bestScore >= 0 && bestLabel !== labels.get(id)) {
				labels.set(id, bestLabel);
				changed = true;
			}
		}
		if (!changed) break;
	}

	const groups = new Map();
	for (const id of ids) {
		const label = labels.get(id);
		if (!groups.has(label)) groups.set(label, []);
		groups.get(label).push(id);
	}
	const ordered = Array.from(groups.entries())
		.sort((a, b) => b[1].length - a[1].length || String(a[0]).localeCompare(String(b[0])));
	const renumbered = new Map();
	ordered.forEach(([label], index) => { renumbered.set(label, index); });
	return new Map(ids.map((id) => [id, renumbered.get(labels.get(id))]));
}

function rankedFrequentTerms(values) {
	const counts = new Map();
	for (const raw of values || []) {
		const value = normStr(raw);
		if (!value) continue;
		counts.set(value, (counts.get(value) || 0) + 1);
	}
	return Array.from(counts.entries())
		.sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
		.map(([value]) => value);
}

function communityTerms(tools) {
	const terms = [];
	const seen = new Set();
	for (const key of ["keywords", "tasks", "audiences"]) {
		for (const term of rankedFrequentTerms((tools || []).flatMap((tool) => tool?.[key] || []))) {
			if (seen.has(term)) continue;
			seen.add(term);
			terms.push(term);
		}
	}
	return terms;
}

function escapeRegExp(value) {
	return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function containsWholeTerm(value, term) {
	if (!value || !term) return false;
	return new RegExp(`(^|[^a-z0-9])${escapeRegExp(term)}([^a-z0-9]|$)`).test(value);
}

function termsOverlap(a, b) {
	return containsWholeTerm(a, b) || containsWholeTerm(b, a);
}

function termAlreadyUsed(term, usedTerms) {
	for (const usedTerm of usedTerms) {
		if (termsOverlap(term, usedTerm)) return true;
	}
	return false;
}

function fallbackCommunityLabel(index, usedLabels) {
	const label = `Cluster ${index + 1}`;
	usedLabels.add(label);
	return label;
}

function communityLabel(terms, index, usedTerms, usedLabels) {
	const topTerm = terms[0] || "";
	const distinctTerm = terms.find((term) => !termAlreadyUsed(term, usedTerms));
	if (!distinctTerm) return fallbackCommunityLabel(index, usedLabels);
	const labelTerms = topTerm && topTerm !== distinctTerm ? [topTerm, distinctTerm] : [distinctTerm];
	const label = labelTerms.join(" · ");
	if (usedLabels.has(label)) return fallbackCommunityLabel(index, usedLabels);
	for (const term of labelTerms) usedTerms.add(term);
	usedLabels.add(label);
	return label;
}

function capCommunities(selected, detected) {
	const groups = new Map();
	for (const item of selected || []) {
		const id = detected.has(item.name) ? detected.get(item.name) : 0;
		if (!groups.has(id)) groups.set(id, []);
		groups.get(id).push(item);
	}
	const ordered = Array.from(groups.entries())
		.sort((a, b) => b[1].length - a[1].length || String(a[0]).localeCompare(String(b[0])));
	const kept = ordered.slice(0, COMMUNITY_LIMIT);
	const remap = new Map();
	kept.forEach(([id], index) => { remap.set(id, index); });
	const nodeCommunities = new Map();
	for (const item of selected || []) {
		const id = detected.has(item.name) ? detected.get(item.name) : 0;
		nodeCommunities.set(item.name, remap.has(id) ? remap.get(id) : "other");
	}
	const usedTerms = new Set();
	const usedLabels = new Set();
	const communityMeta = kept.map(([, items], index) => ({
		id: index,
		label: communityLabel(communityTerms(items.map((item) => item.tool)), index, usedTerms, usedLabels),
		size: items.length,
	}));
	return { nodeCommunities, communityMeta };
}

async function buildGlobalGraph() {
	const [index, lm] = await Promise.all([getSimilarityIndex(), listMemberships()]);
	const ranked = index.tools
		.filter((tool) => tool && tool.name && ((tool.keywords?.length || 0) + (tool.tasks?.length || 0)) > 0)
		.map((tool) => {
			const richness = (tool.keywords?.length || 0)
				+ (tool.tasks?.length || 0)
				+ (tool.audiences?.length || 0)
				+ (tool.forWikis?.length || 0);
			return { name: tool.name, tool, richness, endorsement: endorsementOf(tool.name, lm).count };
		})
		.sort((a, b) => b.richness - a.richness || (a.tool.title || a.name).localeCompare(b.tool.title || b.name));
	const truncated = Math.max(0, ranked.length - GLOBAL_NODE_LIMIT);
	const selected = ranked.slice(0, GLOBAL_NODE_LIMIT);
	const nodeNames = selected.map((item) => item.name);
	const edges = knnEdges(nodeNames, index, 4);
	const detected = detectCommunities(nodeNames, edges);
	const { nodeCommunities, communityMeta } = capCommunities(selected, detected);
	const degree = new Map(nodeNames.map((name) => [name, 0]));
	for (const edge of edges) {
		if (degree.has(edge.source)) degree.set(edge.source, degree.get(edge.source) + 1);
		if (degree.has(edge.target)) degree.set(edge.target, degree.get(edge.target) + 1);
	}
	const nodes = selected.map(({ name, tool, endorsement }) => ({
		id: name,
		title: tool.title || name,
		community: nodeCommunities.get(name) || 0,
		weight: degree.get(name) || 0,
		endorsement,
		fits: fitsContext(tool).fits,
	}));
	return { nodes, edges, communities: communityMeta.length, communityMeta, truncated };
}

export const globalGraph = memoizeAsync(buildGlobalGraph);

function indexWithTool(index, tool) {
	if (index.byName.has(tool.name) && index.vectors.has(tool.name)) return index;
	const byName = new Map(index.byName);
	const vectors = new Map(index.vectors);
	byName.set(tool.name, tool);
	vectors.set(tool.name, vectorFor(tool, index));
	return Object.assign({}, index, {
		tools: index.tools.concat(tool),
		byName,
		vectors,
	});
}

export async function egoGraph(toolName, k = 10) {
	const index = await getSimilarityIndex();
	const tool = index.byName.get(toolName) || await getTool(toolName);
	if (!tool) return { nodes: [], edges: [], center: toolName };
	const workingIndex = indexWithTool(index, tool);
	const neighbors = nearestNeighbors(tool, workingIndex, k);
	const tools = [tool];
	const seen = new Set([tool.name]);
	const scores = new Map([[tool.name, 1]]);
	for (const item of neighbors) {
		if (!item.tool || seen.has(item.tool.name)) continue;
		seen.add(item.tool.name);
		tools.push(item.tool);
		scores.set(item.tool.name, item.score);
	}
	const nodeNames = tools.map((item) => item.name);
	return {
		nodes: tools.map((item) => ({
			id: item.name,
			title: item.title || item.name,
			fits: fitsContext(item).fits,
			center: item.name === tool.name,
			score: scores.get(item.name) || 0,
			weight: item.name === tool.name ? k : (scores.get(item.name) || 0) * k,
		})),
		edges: knnEdges(nodeNames, workingIndex, 3),
		center: tool.name,
	};
}
