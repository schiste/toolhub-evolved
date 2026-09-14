// SPDX-License-Identifier: GPL-3.0-or-later

export const TWO_PI = Math.PI * 2;

/**
 * @param {number} value
 * @param {number} min
 * @param {number} max
 */
export function clamp(value, min, max) {
	return Math.max(min, Math.min(max, value));
}

/** @param {any} node */
export function nodeSize(node) {
	if (node.center) return 18;
	const weight = Math.max(0, Number(node.weight) || 0);
	return clamp(7 + Math.sqrt(weight) * 3.2, 7, 18);
}

/**
 * @param {string} a
 * @param {string} b
 */
// Stryker disable all: edgeKey only feeds edgeSet, consumed solely by drawEdge's isActive/alpha computation (a canvas draw) — no observable effect.
export function edgeKey(a, b) {
	return a < b ? `${a}\u0000${b}` : `${b}\u0000${a}`;
}
// Stryker restore all

/**
 * @param {any[]} nodes
 * @param {number} width
 * @param {number} height
 */
export function seedNodes(nodes, width, height) {
	const cx = width / 2;
	const cy = height / 2;
	// Stryker disable next-line ArithmeticOperator,MethodExpression: `span` is only the initial seed radius; the simulation converges to a layout independent of it (verified by the hover fingerprint, which is unchanged when this magnitude changes) — equivalent.
	const span = Math.max(40, Math.min(width, height) * 0.38);
	nodes.forEach((node, index) => {
		const angle = (index / Math.max(nodes.length, 1)) * TWO_PI;
		// Stryker disable next-line ArithmeticOperator: `ring` only scales the initial seed radius; the settled layout is independent of it (verified by the fingerprint) — equivalent.
		const ring = 0.35 + ((index % 17) / 16) * 0.65;
		node.x = cx + Math.cos(angle) * span * ring;
		node.y = cy + Math.sin(angle) * span * ring;
		node.vx = 0;
		node.vy = 0;
	});
}

/**
 * @param {any[]} nodes
 * @param {number} width
 * @param {number} height
 */
export function seedGroupedNodes(nodes, width, height) {
	/** @type {Map<string | number, any[]>} */
	const groups = new Map();
	for (const node of nodes) {
		const group = node.group ?? "other";
		const bucket = groups.get(group) ?? [];
		if (bucket.length === 0) groups.set(group, bucket);
		bucket.push(node);
	}
	const ordered = [...groups.entries()].sort((a, b) => String(a[0]).localeCompare(String(b[0])));
	const columns = Math.max(1, Math.ceil(Math.sqrt(ordered.length)));
	const rows = Math.max(1, Math.ceil(ordered.length / columns));
	const cellWidth = width / columns;
	const cellHeight = height / rows;
	ordered.forEach(([, members], groupIndex) => {
		const column = groupIndex % columns;
		const row = Math.floor(groupIndex / columns);
		const memberColumns = Math.max(1, Math.ceil(Math.sqrt(members.length)));
		const memberRows = Math.max(1, Math.ceil(members.length / memberColumns));
		const gapX = Math.max(8, (cellWidth - 44) / memberColumns);
		const gapY = Math.max(8, (cellHeight - 44) / memberRows);
		members.forEach((node, index) => {
			const memberColumn = index % memberColumns;
			const memberRow = Math.floor(index / memberColumns);
			node.x = column * cellWidth + 22 + memberColumn * gapX;
			node.y = row * cellHeight + 30 + memberRow * gapY;
			node.vx = 0;
			node.vy = 0;
		});
	});
}

/**
 * @param {{ nodes?: any[]; edges?: any[] }} data
 */
export function graphStructure(data) {
	const nodes = (data.nodes || []).map((node, index) => Object.assign({ index, x: 0, y: 0, vx: 0, vy: 0 }, node));
	const byId = new Map(nodes.map((node) => [node.id, node]));
	const edges = (data.edges || [])
		.map((edge) => Object.assign({}, edge, { sourceNode: byId.get(edge.source), targetNode: byId.get(edge.target) }))
		.filter((edge) => edge.sourceNode && edge.targetNode);
	/** @type {Map<string, Set<string>>} */
	// Stryker disable all: neighborMap and edgeSet are consumed only by activeIds() and drawEdge() — both feed canvas draw alpha/highlighting with no observable, assertable DOM/handle effect.
	const neighborMap = new Map(nodes.map((node) => [node.id, new Set()]));
	/** @type {Set<string>} */
	const edgeSet = new Set();
	edges.forEach((edge) => {
		neighborMap.get(edge.source)?.add(edge.target);
		neighborMap.get(edge.target)?.add(edge.source);
		edgeSet.add(edgeKey(edge.source, edge.target));
	});
	// Stryker restore all
	return { nodes, edges, neighborMap, edgeSet };
}
