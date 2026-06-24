// SPDX-License-Identifier: GPL-3.0-or-later
const TWO_PI = Math.PI * 2;
const MAX_TICKS = 400;
const COMMUNITY_PALETTE = [
	["--wmf-blue-aaa", "#0c57a8"],
	["--wmf-green-aaa", "#246342"],
	["--wmf-red-aaa", "#970302"],
	["--wmf-orange", "#ee8019"],
	["--wmf-purple", "#5748b5"],
	["--wmf-yellow", "#f0bc00"],
	["--wmf-green-light", "#cbe0d5"],
	["--wmf-orange-light", "#fbdfc5"],
];

function clamp(value, min, max) {
	return Math.max(min, Math.min(max, value));
}

function cssVar(styles, name, fallback) {
	if (!styles) return fallback;
	const value = styles.getPropertyValue(name).trim();
	return value || fallback;
}

function rootStyles() {
	if (typeof document === "undefined" || typeof getComputedStyle !== "function") return null;
	return getComputedStyle(document.documentElement);
}

function paletteFromTokens(styles) {
	return COMMUNITY_PALETTE
		.map(([token, fallback]) => cssVar(styles, token, fallback))
		.filter(Boolean);
}

function nodeSize(node) {
	if (node.center) return 18;
	const weight = Math.max(0, Number(node.weight) || 0);
	return clamp(7 + Math.sqrt(weight) * 3.2, 7, 18);
}

function colorForNode(node, colors) {
	if (node.center) return colors.center;
	if (node.community != null) {
		if (typeof colors.communityColor === "function") {
			const custom = colors.communityColor(node.community);
			if (custom) return custom;
		}
		if (colors.communityMap.has(node.community)) return colors.communityMap.get(node.community);
		if (colors.communityMap.has(String(node.community))) return colors.communityMap.get(String(node.community));
		const index = Number(node.community);
		if (Number.isFinite(index)) return colors.palette[index % colors.palette.length];
	}
	if (node.score != null) return colors.score;
	return colors.palette[0];
}

export function communityColors(communityMeta, opts = {}) {
	const styles = rootStyles();
	const palette = (opts.palette && opts.palette.length ? opts.palette : paletteFromTokens(styles)).filter(Boolean);
	const neutral = opts.neutral || cssVar(styles, "--color-text-muted", cssVar(styles, "--color-border", "#72777d"));
	const colors = new Map();
	for (const [index, community] of (communityMeta || []).entries()) {
		if (!community) continue;
		const color = palette[index % Math.max(palette.length, 1)] || "#0c57a8";
		colors.set(community.id, color);
		colors.set(String(community.id), color);
	}
	colors.set("other", neutral);
	return colors;
}

function buildColors(data, opts) {
	const styles = rootStyles();
	const palette = (opts.palette && opts.palette.length ? opts.palette : paletteFromTokens(styles)).filter(Boolean);
	const neutral = cssVar(styles, "--color-text-muted", cssVar(styles, "--color-border", "#72777d"));
	return {
		border: cssVar(styles, "--color-border", "#d4d7db"),
		center: cssVar(styles, "--color-progressive-hover", "#09437f"),
		fit: cssVar(styles, "--color-progressive", "#0c57a8"),
		labelBg: cssVar(styles, "--color-surface", "#fff"),
		labelText: cssVar(styles, "--color-text", "#1b1b1b"),
		communityMap: communityColors(data?.communityMeta || [], { palette, neutral }),
		communityColor: typeof opts.communityColor === "function" ? opts.communityColor : null,
		other: neutral,
		score: cssVar(styles, "--wmf-green-aaa", "#246342"),
		surface: cssVar(styles, "--color-surface", "#fff"),
		palette: palette.length ? palette : ["#0c57a8"],
	};
}

function edgeKey(a, b) {
	return a < b ? a + "\u0000" + b : b + "\u0000" + a;
}

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

export function forceGraph(container, data, opts = {}) {
	const canvas = document.createElement("canvas");
	const tooltip = document.createElement("div");
	const ctx = canvas.getContext("2d");
	const fitHalo = opts.fitHalo !== false;
	const reducedMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
	let width = 0;
	let height = Number(opts.height) || 480;
	let dpr = 1;
	let raf = 0;
	let ticks = 0;
	let stopped = false;
	let hovered = null;
	let pointer = { x: 0, y: 0 };
	let detachObserver = null;
	let colors = buildColors(data, opts);

	canvas.className = "force-graph";
	canvas.setAttribute("aria-label", "Tool similarity graph");
	canvas.setAttribute("role", "img");
	tooltip.className = "graph__tip";
	tooltip.hidden = true;
	container.innerHTML = "";
	container.append(canvas, tooltip);

	const nodes = (data.nodes || []).map((node, index) => Object.assign({ index, x: 0, y: 0, vx: 0, vy: 0 }, node));
	const byId = new Map(nodes.map((node) => [node.id, node]));
	const edges = (data.edges || [])
		.map((edge) => Object.assign({}, edge, { sourceNode: byId.get(edge.source), targetNode: byId.get(edge.target) }))
		.filter((edge) => edge.sourceNode && edge.targetNode);
	const neighborMap = new Map(nodes.map((node) => [node.id, new Set()]));
	const edgeSet = new Set();
	edges.forEach((edge) => {
		neighborMap.get(edge.source).add(edge.target);
		neighborMap.get(edge.target).add(edge.source);
		edgeSet.add(edgeKey(edge.source, edge.target));
	});

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
		canvas.style.height = height + "px";
		canvas.width = Math.round(width * dpr);
		canvas.height = Math.round(height * dpr);
		ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
		if (!nodes.length) return;
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
			const strength = 0.010 + weight * 0.030;
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

	function drawEdge(edge, active) {
		const isActive = !active || edgeSet.has(edgeKey(edge.source, edge.target)) && active.has(edge.source) && active.has(edge.target);
		ctx.globalAlpha = active ? (isActive ? 0.48 : 0.06) : 0.22;
		ctx.strokeStyle = colors.border;
		ctx.lineWidth = isActive ? 1.25 : 1;
		ctx.beginPath();
		ctx.moveTo(edge.sourceNode.x, edge.sourceNode.y);
		ctx.lineTo(edge.targetNode.x, edge.targetNode.y);
		ctx.stroke();
	}

	function drawNode(node, active) {
		const isActive = !active || active.has(node.id);
		const size = nodeSize(node);
		const x = node.x - size / 2;
		const y = node.y - size / 2;
		const isOther = node.community === "other";
		ctx.globalAlpha = active ? (isActive ? (isOther ? 0.72 : 1) : 0.16) : (isOther ? 0.62 : 1);
		ctx.fillStyle = colorForNode(node, colors);
		ctx.fillRect(x, y, size, size);
		if (node.center) {
			ctx.strokeStyle = colors.labelText;
			ctx.lineWidth = 2;
			ctx.strokeRect(x - 2, y - 2, size + 4, size + 4);
		}
		if (fitHalo && node.fits) {
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
		tooltip.style.left = x + "px";
		tooltip.style.top = y + "px";
	}

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
		},
	};
}
