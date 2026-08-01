// SPDX-License-Identifier: GPL-3.0-or-later
import { applyGroupAttraction, integrateNode } from "../core/graph-layout.js";

const TWO_PI = Math.PI * 2;
const THETA = 0.75;

function clamp(value, min, max) {
	return Math.max(min, Math.min(max, value));
}

function childIndex(quad, node) {
	return (node.x >= quad.x + quad.span / 2 ? 1 : 0) + (node.y >= quad.y + quad.span / 2 ? 2 : 0);
}

function subdivide(quad) {
	const half = quad.span / 2;
	quad.children = [
		makeQuad(quad.x, quad.y, half),
		makeQuad(quad.x + half, quad.y, half),
		makeQuad(quad.x, quad.y + half, half),
		makeQuad(quad.x + half, quad.y + half, half)
	];
}

function makeQuad(x, y, span) {
	return { x, y, span, mass: 0, cx: 0, cy: 0, body: null, children: null };
}

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
	if (!quad.children) {
		subdivide(quad);
		const body = quad.body;
		quad.body = null;
		insert(quad.children[childIndex(quad, body)], body);
	}
	insert(quad.children[childIndex(quad, node)], node);
}

function tree(nodes, width, height) {
	const root = makeQuad(0, 0, Math.max(width, height));
	for (const node of nodes) insert(root, node);
	return root;
}

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
