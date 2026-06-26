// SPDX-License-Identifier: GPL-3.0-or-later
const TWO_PI = Math.PI * 2;
const MAX_TICKS = 400;
const COMMUNITY_PALETTE = [
	"--wmf-blue-aaa",
	"--wmf-green-aaa",
	"--wmf-red-aaa",
	"--wmf-orange",
	"--wmf-purple",
	"--wmf-yellow",
	"--wmf-green-light",
	"--wmf-orange-light"
];
const FALLBACK_COLORS = {
	border: "ButtonBorder",
	center: "LinkText",
	labelBg: "Canvas",
	labelText: "CanvasText",
	neutral: "GrayText",
	score: "Highlight",
	surface: "Canvas"
};

/**
 * @typedef {object} FGOpts
 * @property {number} [height]
 * @property {string[]} [palette]
 * @property {string} [neutral]
 * @property {boolean} [fitHalo]
 * @property {(id: string) => void} [onSelect]
 * @property {(community: number | string) => string | null | undefined} [communityColor]
 */

/**
 * A working graph node: input fields plus the simulation bookkeeping that
 * graphStructure() attaches (index/x/y/vx/vy are always present afterward).
 * @typedef {object} FGNode
 * @property {string} id
 * @property {number} index
 * @property {number} x
 * @property {number} y
 * @property {number} vx
 * @property {number} vy
 * @property {string} [title]
 * @property {number | string} [community]
 * @property {boolean} [center]
 * @property {number} [weight]
 * @property {number} [score]
 * @property {boolean} [fits]
 */

/**
 * @typedef {object} FGEdge
 * @property {string} source
 * @property {string} target
 * @property {number} [weight]
 */

/**
 * @typedef {FGEdge & { sourceNode: FGNode; targetNode: FGNode }} FGResolvedEdge
 */

/**
 * @typedef {object} FGData
 * @property {Partial<FGNode>[]} [nodes]
 * @property {FGEdge[]} [edges]
 * @property {{ id: string | number }[]} [communityMeta]
 */

/**
 * @typedef {object} FGColors
 * @property {string} border
 * @property {string} center
 * @property {string} fit
 * @property {string} labelBg
 * @property {string} labelText
 * @property {Map<string | number, string>} communityMap
 * @property {((community: number | string) => string | null | undefined) | null} communityColor
 * @property {string} other
 * @property {string} score
 * @property {string} surface
 * @property {string[]} palette
 */

/**
 * @param {number} value
 * @param {number} min
 * @param {number} max
 */
function clamp(value, min, max) {
	return Math.max(min, Math.min(max, value));
}

/**
 * @param {CSSStyleDeclaration | null} styles
 * @param {string} name
 * @param {string} fallback
 * @returns {string}
 */
function cssVar(styles, name, fallback) {
	if (!styles) return fallback;
	const value = styles.getPropertyValue(name).trim();
	return value || fallback;
}

/** @returns {CSSStyleDeclaration | null} */
function rootStyles() {
	if (typeof document === "undefined" || typeof getComputedStyle !== "function") return null;
	return getComputedStyle(document.documentElement);
}

/** @param {CSSStyleDeclaration | null} styles */
function paletteFromTokens(styles) {
	return COMMUNITY_PALETTE.map((token) => cssVar(styles, token, "")).filter(Boolean);
}

/** @param {FGNode} node */
function nodeSize(node) {
	if (node.center) return 18;
	const weight = Math.max(0, Number(node.weight) || 0);
	return clamp(7 + Math.sqrt(weight) * 3.2, 7, 18);
}

/**
 * @param {FGNode} node
 * @param {FGColors} colors
 * @returns {string}
 */
function colorForNode(node, colors) {
	if (node.center) return colors.center;
	if (node.community !== null && node.community !== undefined) {
		if (typeof colors.communityColor === "function") {
			const custom = colors.communityColor(node.community);
			if (custom) return custom;
		}
		if (colors.communityMap.has(node.community)) {
			return /** @type {string} */ (colors.communityMap.get(node.community));
		}
		if (colors.communityMap.has(String(node.community))) {
			return /** @type {string} */ (colors.communityMap.get(String(node.community)));
		}
		const index = Number(node.community);
		if (Number.isFinite(index)) return colors.palette[index % colors.palette.length];
	}
	if (node.score !== null && node.score !== undefined) return colors.score;
	return colors.palette[0];
}

/**
 * @param {{ id: string | number }[] | null | undefined} communityMeta
 * @param {{ palette?: string[]; neutral?: string }} [opts]
 * @returns {Map<string | number, string>}
 */
export function communityColors(communityMeta, opts = {}) {
	const styles = rootStyles();
	const palette = (opts.palette && opts.palette.length > 0 ? opts.palette : paletteFromTokens(styles)).filter(
		Boolean
	);
	const neutral =
		opts.neutral || cssVar(styles, "--color-text-muted", cssVar(styles, "--color-border", FALLBACK_COLORS.neutral));
	const colors = new Map();
	for (const [index, community] of (communityMeta || []).entries()) {
		if (!community) continue;
		const color = palette.length > 0 ? palette[index % palette.length] : FALLBACK_COLORS.center;
		colors.set(community.id, color);
		colors.set(String(community.id), color);
	}
	colors.set("other", neutral);
	return colors;
}

/**
 * @param {FGData} data
 * @param {FGOpts} opts
 * @returns {FGColors}
 */
function buildColors(data, opts) {
	const styles = rootStyles();
	const palette = (opts.palette && opts.palette.length > 0 ? opts.palette : paletteFromTokens(styles)).filter(
		Boolean
	);
	const neutral = cssVar(styles, "--color-text-muted", cssVar(styles, "--color-border", FALLBACK_COLORS.neutral));
	return {
		border: cssVar(styles, "--color-border", FALLBACK_COLORS.border),
		center: cssVar(styles, "--color-progressive-hover", FALLBACK_COLORS.center),
		fit: cssVar(styles, "--color-progressive", FALLBACK_COLORS.center),
		labelBg: cssVar(styles, "--color-surface", FALLBACK_COLORS.labelBg),
		labelText: cssVar(styles, "--color-text", FALLBACK_COLORS.labelText),
		communityMap: communityColors(data?.communityMeta || [], { palette, neutral }),
		communityColor: typeof opts.communityColor === "function" ? opts.communityColor : null,
		other: neutral,
		score: cssVar(styles, "--wmf-green-aaa", FALLBACK_COLORS.score),
		surface: cssVar(styles, "--color-surface", FALLBACK_COLORS.surface),
		palette: palette.length > 0 ? palette : [FALLBACK_COLORS.center]
	};
}

/**
 * @param {string} a
 * @param {string} b
 */
function edgeKey(a, b) {
	return a < b ? `${a}\u0000${b}` : `${b}\u0000${a}`;
}

/**
 * @param {FGNode[]} nodes
 * @param {number} width
 * @param {number} height
 */
function seedNodes(nodes, width, height) {
	const cx = width / 2;
	const cy = height / 2;
	const span = Math.max(40, Math.min(width, height) * 0.38);
	nodes.forEach((node, index) => {
		const angle = (index / Math.max(nodes.length, 1)) * TWO_PI;
		const ring = 0.35 + ((index % 17) / 16) * 0.65;
		node.x = cx + Math.cos(angle) * span * ring;
		node.y = cy + Math.sin(angle) * span * ring;
		node.vx = 0;
		node.vy = 0;
	});
}

/** @param {HTMLElement} container */
function createGraphSurface(container) {
	const canvas = document.createElement("canvas");
	const tooltip = document.createElement("div");
	const ctx = /** @type {CanvasRenderingContext2D} */ (canvas.getContext("2d"));
	canvas.className = "force-graph";
	canvas.setAttribute("aria-label", "Tool similarity graph");
	canvas.setAttribute("role", "img");
	tooltip.className = "graph__tip";
	tooltip.hidden = true;
	container.innerHTML = "";
	container.append(canvas, tooltip);
	return { canvas, tooltip, ctx };
}

/** @param {FGData} data */
function graphStructure(data) {
	const nodes = /** @type {FGNode[]} */ (
		(data.nodes || []).map((node, index) => Object.assign({ index, x: 0, y: 0, vx: 0, vy: 0 }, node))
	);
	const byId = new Map(nodes.map((node) => [node.id, node]));
	const edges = /** @type {FGResolvedEdge[]} */ (
		(data.edges || [])
			.map((edge) =>
				Object.assign({}, edge, { sourceNode: byId.get(edge.source), targetNode: byId.get(edge.target) })
			)
			.filter((edge) => edge.sourceNode && edge.targetNode)
	);
	/** @type {Map<string, Set<string>>} */
	const neighborMap = new Map(nodes.map((node) => [node.id, new Set()]));
	/** @type {Set<string>} */
	const edgeSet = new Set();
	edges.forEach((edge) => {
		neighborMap.get(edge.source)?.add(edge.target);
		neighborMap.get(edge.target)?.add(edge.source);
		edgeSet.add(edgeKey(edge.source, edge.target));
	});
	return { nodes, edges, neighborMap, edgeSet };
}

/**
 * @param {HTMLElement} container
 * @param {FGData} data
 * @param {FGOpts} [opts]
 */
export function forceGraph(container, data, opts = {}) {
	const { canvas, tooltip, ctx } = createGraphSurface(container);
	const reducedMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
	let width = 0;
	let height = Number(opts.height) || 480;
	let dpr = 1;
	let raf = 0;
	let ticks = 0;
	let stopped = false;
	/** @type {FGNode | null} */
	let hovered = null;
	let pointer = { x: 0, y: 0 };
	/** @type {MutationObserver | null} */
	let detachObserver = null;
	let colors = buildColors(data, opts);

	const { nodes, edges, neighborMap, edgeSet } = graphStructure(data);

	function activeIds() {
		if (!hovered) return null;
		const ids = new Set([hovered.id]);
		(neighborMap.get(hovered.id) || []).forEach((id) => ids.add(id));
		return ids;
	}

	function resize() {
		const oldWidth = width || container.clientWidth || container.getBoundingClientRect().width;
		const oldHeight = height;
		width = Math.max(320, Math.round(container.clientWidth || container.getBoundingClientRect().width || 720));
		height = Math.max(180, Number(opts.height) || 480);
		dpr = Math.max(1, window.devicePixelRatio || 1);
		canvas.style.width = "100%";
		canvas.style.height = `${height}px`;
		canvas.width = Math.round(width * dpr);
		canvas.height = Math.round(height * dpr);
		ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
		if (nodes.length === 0) return;
		if (ticks === 0 && nodes.every((node) => node.x === 0 && node.y === 0)) {
			seedNodes(nodes, width, height);
		} else {
			const sx = width / Math.max(oldWidth, 1);
			const sy = height / Math.max(oldHeight, 1);
			nodes.forEach((node) => {
				node.x = width / 2 + (node.x - oldWidth / 2) * sx;
				node.y = height / 2 + (node.y - oldHeight / 2) * sy;
			});
		}
	}

	function step() {
		const cx = width / 2;
		const cy = height / 2;
		const charge = Math.max(260, Math.min(width, height) * 0.85);
		for (let i = 0; i < nodes.length; i++) {
			const a = nodes[i];
			for (let j = i + 1; j < nodes.length; j++) {
				const b = nodes[j];
				let dx = a.x - b.x;
				let dy = a.y - b.y;
				let dist2 = dx * dx + dy * dy;
				if (dist2 < 25) {
					dx = (a.index - b.index || 1) * 0.1;
					dy = (b.index - a.index || 1) * 0.1;
					dist2 = dx * dx + dy * dy;
				}
				const dist = Math.sqrt(dist2);
				const force = (charge * charge * 0.0008) / Math.max(dist2, 64);
				const fx = (dx / dist) * force;
				const fy = (dy / dist) * force;
				a.vx += fx;
				a.vy += fy;
				b.vx -= fx;
				b.vy -= fy;
			}
		}
		for (const edge of edges) {
			const a = edge.sourceNode;
			const b = edge.targetNode;
			const weight = clamp(Number(edge.weight) || 0, 0, 1);
			const rest = 96 - weight * 42;
			const strength = 0.01 + weight * 0.03;
			const dx = b.x - a.x;
			const dy = b.y - a.y;
			const dist = Math.max(1, Math.sqrt(dx * dx + dy * dy));
			const force = (dist - rest) * strength;
			const fx = (dx / dist) * force;
			const fy = (dy / dist) * force;
			a.vx += fx;
			a.vy += fy;
			b.vx -= fx;
			b.vy -= fy;
		}
		for (const node of nodes) {
			node.vx += (cx - node.x) * 0.002;
			node.vy += (cy - node.y) * 0.002;
			node.vx *= 0.82;
			node.vy *= 0.82;
			node.x = clamp(node.x + node.vx, 10, width - 10);
			node.y = clamp(node.y + node.vy, 10, height - 10);
		}
	}

	/**
	 * @param {FGResolvedEdge} edge
	 * @param {Set<string> | null} active
	 */
	function drawEdge(edge, active) {
		const isActive =
			!active ||
			(edgeSet.has(edgeKey(edge.source, edge.target)) && active.has(edge.source) && active.has(edge.target));
		ctx.globalAlpha = active ? (isActive ? 0.48 : 0.06) : 0.22;
		ctx.strokeStyle = colors.border;
		ctx.lineWidth = isActive ? 1.25 : 1;
		ctx.beginPath();
		ctx.moveTo(edge.sourceNode.x, edge.sourceNode.y);
		ctx.lineTo(edge.targetNode.x, edge.targetNode.y);
		ctx.stroke();
	}

	/**
	 * @param {FGNode} node
	 * @param {Set<string> | null} active
	 */
	function drawNode(node, active) {
		const isActive = !active || active.has(node.id);
		const size = nodeSize(node);
		const x = node.x - size / 2;
		const y = node.y - size / 2;
		const isOther = node.community === "other";
		ctx.globalAlpha = active ? (isActive ? (isOther ? 0.72 : 1) : 0.16) : isOther ? 0.62 : 1;
		ctx.fillStyle = colorForNode(node, colors);
		ctx.fillRect(x, y, size, size);
		if (node.center) {
			ctx.strokeStyle = colors.labelText;
			ctx.lineWidth = 2;
			ctx.strokeRect(x - 2, y - 2, size + 4, size + 4);
		}
		if (opts.fitHalo !== false && node.fits) {
			ctx.globalAlpha = isActive ? 1 : 0.16;
			ctx.strokeStyle = colors.fit;
			ctx.lineWidth = 2;
			ctx.strokeRect(x - 4, y - 4, size + 8, size + 8);
		}
	}

	function draw() {
		colors = buildColors(data, opts);
		ctx.globalAlpha = 1;
		ctx.clearRect(0, 0, width, height);
		ctx.fillStyle = colors.surface;
		ctx.fillRect(0, 0, width, height);
		const active = activeIds();
		edges.forEach((edge) => drawEdge(edge, active));
		nodes.filter((node) => active && !active.has(node.id)).forEach((node) => drawNode(node, active));
		nodes.filter((node) => !active || active.has(node.id)).forEach((node) => drawNode(node, active));
		ctx.globalAlpha = 1;
	}

	/**
	 * @param {number} x
	 * @param {number} y
	 * @returns {FGNode | null}
	 */
	function findNode(x, y) {
		for (let i = nodes.length - 1; i >= 0; i--) {
			const node = nodes[i];
			const half = nodeSize(node) / 2 + 4;
			if (Math.abs(x - node.x) <= half && Math.abs(y - node.y) <= half) return node;
		}
		return null;
	}

	function positionTooltip() {
		if (!hovered) {
			tooltip.hidden = true;
			return;
		}
		tooltip.hidden = false;
		tooltip.textContent = hovered.title || hovered.id;
		const pad = 12;
		const x = clamp(pointer.x + pad, pad, width - pad);
		const y = clamp(pointer.y + pad, pad, height - pad);
		tooltip.style.left = `${x}px`;
		tooltip.style.top = `${y}px`;
	}

	/** @param {MouseEvent} event */
	function onMove(event) {
		const rect = canvas.getBoundingClientRect();
		pointer = { x: event.clientX - rect.left, y: event.clientY - rect.top };
		const next = findNode(pointer.x, pointer.y);
		if (next !== hovered) {
			hovered = next;
			canvas.style.cursor = hovered ? "pointer" : "";
			draw();
		}
		positionTooltip();
	}

	function onLeave() {
		hovered = null;
		canvas.style.cursor = "";
		positionTooltip();
		draw();
	}

	function onClick() {
		if (hovered && typeof opts.onSelect === "function") opts.onSelect(hovered.id);
	}

	function stop() {
		stopped = true;
		if (raf) cancelAnimationFrame(raf);
		raf = 0;
		if (detachObserver) detachObserver.disconnect();
		detachObserver = null;
		window.removeEventListener("resize", onResize);
		canvas.removeEventListener("mousemove", onMove);
		canvas.removeEventListener("mouseleave", onLeave);
		canvas.removeEventListener("click", onClick);
	}

	function animate() {
		if (stopped || !document.body.contains(canvas)) {
			stop();
			return;
		}
		if (ticks < MAX_TICKS) {
			step();
			ticks++;
		}
		draw();
		if (ticks < MAX_TICKS) raf = requestAnimationFrame(animate);
		else raf = 0;
	}

	function settleAndDraw() {
		for (let i = 0; i < MAX_TICKS; i++) step();
		ticks = MAX_TICKS;
		draw();
	}

	function start() {
		if (stopped) return;
		if (raf) cancelAnimationFrame(raf);
		if (reducedMotion) settleAndDraw();
		else raf = requestAnimationFrame(animate);
	}

	function onResize() {
		resize();
		ticks = 0;
		start();
	}

	resize();
	canvas.addEventListener("mousemove", onMove);
	canvas.addEventListener("mouseleave", onLeave);
	canvas.addEventListener("click", onClick);
	window.addEventListener("resize", onResize);
	if (window.MutationObserver) {
		detachObserver = new MutationObserver(() => {
			if (!document.body.contains(canvas)) stop();
		});
		detachObserver.observe(document.body, { childList: true, subtree: true });
	}
	start();

	return {
		stop,
		redraw() {
			draw();
		}
	};
}
