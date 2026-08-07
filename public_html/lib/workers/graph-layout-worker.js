// SPDX-License-Identifier: GPL-3.0-or-later
import { applyGroupAttraction, integrateNode } from "../core/graph-layout.js";

const TWO_PI = Math.PI * 2;
const THETA = 0.75;

/**
 * One node inside the running simulation: the caller's node plus the velocity
 * and ordinal the integrator needs.
 * @typedef {object} SimNode
 * @property {number} x
 * @property {number} y
 * @property {number} vx
 * @property {number} vy
 * @property {number} index
 * @property {(number | string)[]} [groupValues]
 * @property {boolean} [pinned]
 */

/**
 * A Barnes-Hut quadtree cell. `body` holds a single node until the cell splits;
 * `children` is the four sub-cells once it has.
 * @typedef {object} Quad
 * @property {number} x
 * @property {number} y
 * @property {number} span
 * @property {number} mass
 * @property {number} cx centre of mass, x
 * @property {number} cy centre of mass, y
 * @property {SimNode | null} body
 * @property {Quad[] | null} children
 */

/**
 * @typedef {object} LayoutPayload
 * @property {Array<{ x: number, y: number, groupValues?: (number | string)[], pinned?: boolean }>} nodes
 * @property {number} [width]
 * @property {number} [height]
 * @property {Array<{ source: number, target: number, weight?: number }>} [edges]
 * @property {string} [groupBy]
 * @property {Array<{ id: number | string, size?: number }>} [groupMeta]
 * @property {number} [ticks]
 * @property {string | number} [requestId]
 */

/** @param {number} value @param {number} min @param {number} max @returns {number} */
function clamp(value, min, max) {
	return Math.max(min, Math.min(max, value));
}

/** @param {Quad} quad @param {SimNode} node @returns {number} which of the four sub-cells */
function childIndex(quad, node) {
	return (node.x >= quad.x + quad.span / 2 ? 1 : 0) + (node.y >= quad.y + quad.span / 2 ? 2 : 0);
}

/** @param {Quad} quad @returns {Quad[]} the four new sub-cells, also stored on `quad` */
function subdivide(quad) {
	const half = quad.span / 2;
	const children = [
		makeQuad(quad.x, quad.y, half),
		makeQuad(quad.x + half, quad.y, half),
		makeQuad(quad.x, quad.y + half, half),
		makeQuad(quad.x + half, quad.y + half, half)
	];
	quad.children = children;
	return children;
}

/** @param {number} x @param {number} y @param {number} span @returns {Quad} */
function makeQuad(x, y, span) {
	return { x, y, span, mass: 0, cx: 0, cy: 0, body: null, children: null };
}

/** @param {Quad} quad @param {SimNode} node @returns {void} */
function insert(quad, node) {
	const previousMass = quad.mass;
	quad.mass++;
	quad.cx = (quad.cx * previousMass + node.x) / quad.mass;
	quad.cy = (quad.cy * previousMass + node.y) / quad.mass;
	if (!quad.body && !quad.children) {
		quad.body = node;
		return;
	}
	if (quad.span < 1) return;
	let children = quad.children;
	if (!children) {
		children = subdivide(quad);
		// A cell with no children reached here only by holding a body, so the
		// cast restates the branch condition the checker cannot see.
		const body = /** @type {SimNode} */ (quad.body);
		quad.body = null;
		insert(children[childIndex(quad, body)], body);
	}
	insert(children[childIndex(quad, node)], node);
}

/** @param {SimNode[]} nodes @param {number} width @param {number} height @returns {Quad} */
function tree(nodes, width, height) {
	const root = makeQuad(0, 0, Math.max(width, height));
	for (const node of nodes) insert(root, node);
	return root;
}

/** @param {SimNode} node @param {Quad} quad @param {number} charge @returns {void} */
function repel(node, quad, charge) {
	if (quad.mass === 0 || (quad.mass === 1 && quad.body === node && !quad.children)) return;
	let dx = node.x - quad.cx;
	let dy = node.y - quad.cy;
	let dist2 = dx * dx + dy * dy;
	if (dist2 < 25) {
		dx = (node.index - quad.mass || 1) * 0.1;
		dy = (quad.mass - node.index || 1) * 0.1;
		dist2 = dx * dx + dy * dy;
	}
	const dist = Math.sqrt(dist2);
	if (!quad.children || quad.span / dist < THETA) {
		const force = (charge * charge * 0.0008 * quad.mass) / Math.max(dist2, 64);
		node.vx += (dx / dist) * force;
		node.vy += (dy / dist) * force;
		return;
	}
	for (const child of quad.children) repel(node, child, charge);
}

/**
 * Place one anchor per facet group around a circle, so grouped layouts pull
 * their members outward instead of piling everything at the centre.
 * @param {string | undefined} groupBy
 * @param {Array<{ id: number | string, size?: number }>} groupMeta
 * @param {number} width
 * @param {number} height
 * @returns {Map<string, { x: number, y: number, size: number }>}
 */
function anchors(groupBy, groupMeta, width, height) {
	const out = new Map();
	if (groupBy === "similarity") return out;
	const groups = groupMeta.filter((group) => String(group.id) !== "other");
	const radius = Math.min(width, height) * 0.3;
	groups.forEach((group, index) => {
		const angle = (index / Math.max(groups.length, 1)) * TWO_PI;
		out.set(String(group.id), {
			x: width / 2 + Math.cos(angle) * radius,
			y: height / 2 + Math.sin(angle) * radius,
			size: Math.max(1, Number(group.size) || 1)
		});
	});
	return out;
}

/**
 * Run the force simulation to a fixed tick count and return final positions.
 * @param {LayoutPayload} payload
 * @returns {Array<{ x: number, y: number }>}
 */
export function simulate(payload) {
	const width = Math.max(320, Number(payload.width) || 720);
	const height = Math.max(180, Number(payload.height) || 480);
	const nodes = payload.nodes.map((node, index) => ({ ...node, index, vx: 0, vy: 0 }));
	const groupAnchors = anchors(payload.groupBy, payload.groupMeta || [], width, height);
	const charge = Math.max(260, Math.min(width, height) * 0.85);
	const ticks = clamp(Number(payload.ticks) || 240, 1, 400);
	for (let tick = 0; tick < ticks; tick++) {
		const quad = tree(nodes, width, height);
		for (const node of nodes) repel(node, quad, charge);
		for (const edge of payload.edges || []) {
			const a = nodes[edge.source];
			const b = nodes[edge.target];
			if (!a || !b) continue;
			const weight = clamp(Number(edge.weight) || 0, 0, 1);
			const dx = b.x - a.x;
			const dy = b.y - a.y;
			const dist = Math.max(1, Math.hypot(dx, dy));
			const force = (dist - (96 - weight * 42)) * (0.01 + weight * 0.03);
			a.vx += (dx / dist) * force;
			a.vy += (dy / dist) * force;
			b.vx -= (dx / dist) * force;
			b.vy -= (dy / dist) * force;
		}
		for (const node of nodes) {
			applyGroupAttraction(node, groupAnchors, nodes.length);
			integrateNode(node, width / 2, height / 2, width, height);
		}
	}
	return nodes.map((node) => ({ x: node.x, y: node.y }));
}

if (typeof self !== "undefined") {
	self.onmessage = (event) => {
		const payload = event.data || {};
		self.postMessage({ requestId: payload.requestId, positions: simulate(payload) });
	};
}
