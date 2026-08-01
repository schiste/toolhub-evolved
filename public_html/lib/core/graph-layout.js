// SPDX-License-Identifier: GPL-3.0-or-later

/**
 * Apply inverse-frequency attraction for every facet membership on a node.
 * @param {{ x: number, y: number, vx: number, vy: number, groupValues?: (number | string)[] }} node
 * @param {Map<string, { x: number, y: number, size: number }>} groupAnchors
 * @param {number} totalNodes
 */
export function applyGroupAttraction(node, groupAnchors, totalNodes) {
	const memberships = [];
	for (const group of node.groupValues || []) {
		const anchor = groupAnchors.get(String(group));
		if (anchor) memberships.push(anchor);
	}
	for (const anchor of memberships) {
		const rarity = 1 + Math.log((1 + totalNodes) / (1 + anchor.size));
		const strength = (0.0045 * rarity) / memberships.length;
		node.vx += (anchor.x - node.x) * strength;
		node.vy += (anchor.y - node.y) * strength;
	}
}

/**
 * Apply centering, damping, and viewport bounds to one simulated node.
 * @param {{ x: number, y: number, vx: number, vy: number, pinned?: boolean }} node
 * @param {number} centerX
 * @param {number} centerY
 * @param {number} width
 * @param {number} height
 */
export function integrateNode(node, centerX, centerY, width, height) {
	if (node.pinned) {
		node.vx = 0;
		node.vy = 0;
		return;
	}
	node.vx += (centerX - node.x) * 0.002;
	node.vy += (centerY - node.y) * 0.002;
	node.vx *= 0.82;
	node.vy *= 0.82;
	node.x = Math.max(10, Math.min(width - 10, node.x + node.vx));
	node.y = Math.max(10, Math.min(height - 10, node.y + node.vy));
}
