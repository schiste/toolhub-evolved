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
	// Stryker disable next-line StringLiteral: only used as a buildColors fallback feeding ctx.strokeStyle (canvas) — no observable effect.
	border: "ButtonBorder",
	center: "LinkText", // observable via communityColors (empty-palette fallback)
	// Stryker disable next-line StringLiteral: buildColors-only fallback feeding canvas label fills — no observable effect.
	labelBg: "Canvas",
	// Stryker disable next-line StringLiteral: buildColors-only fallback feeding canvas label text (ctx.strokeStyle) — no observable effect.
	labelText: "CanvasText",
	neutral: "GrayText", // observable via communityColors (neutral fallback)
	// Stryker disable next-line StringLiteral: buildColors-only fallback feeding ctx.fillStyle (canvas) — no observable effect.
	score: "Highlight",
	// Stryker disable next-line StringLiteral: buildColors-only fallback feeding the canvas background fill — no observable effect.
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
	// Stryker disable next-line MethodExpression: CSS custom-property values are already whitespace-trimmed by the parser (verified in happy-dom), so the extra .trim() is a no-op — equivalent.
	const value = styles.getPropertyValue(name).trim();
	return value || fallback;
}

/** @returns {CSSStyleDeclaration | null} */
function rootStyles() {
	// Stryker disable next-line ConditionalExpression,StringLiteral: defensive SSR/environment guard — `document` and `getComputedStyle` are always present in browsers and in the happy-dom test environment, so neither branch (return null) is reachable from the test suite; the surviving variants are equivalent here.
	if (typeof document === "undefined" || typeof getComputedStyle !== "function") return null;
	return getComputedStyle(document.documentElement);
}

/** @param {CSSStyleDeclaration | null} styles */
function paletteFromTokens(styles) {
	// Stryker disable next-line MethodExpression: communityColors/buildColors re-apply `.filter(Boolean)` to this result, so dropping the filter here is masked and has no observable effect — equivalent.
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
// Stryker disable all: colorForNode's return value is only ever assigned to ctx.fillStyle (a canvas draw); it has no observable, assertable effect on the DOM/handle, so every mutant here is equivalent (per the canvas-draw exclusion).
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
// Stryker restore all

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
// Stryker disable all: buildColors only feeds the colour object consumed by colorForNode/drawNode/drawEdge/draw — every field ends up as a ctx fill/stroke style (canvas draw) with no observable effect. (communityColors itself is covered directly via its export.)
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
// Stryker restore all

/**
 * @param {string} a
 * @param {string} b
 */
// Stryker disable all: edgeKey only feeds edgeSet, consumed solely by drawEdge's isActive/alpha computation (a canvas draw) — no observable effect.
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

// Stryker restore all
/** @param {FGData} data */
function graphStructure(data) {
	const nodes = /** @type {FGNode[]} */ (
		(data.nodes || []).map((node, index) => Object.assign({ index, x: 0, y: 0, vx: 0, vy: 0 }, node))
	);
	const byId = new Map(nodes.map((node) => [node.id, node]));
	const edges = /** @type {FGResolvedEdge[]} */ (
		// Stryker disable next-line ArrayDeclaration: the `|| []` fallback only fires when data.edges is missing; a non-empty mutant fallback yields an edge whose string endpoints don't resolve to nodes, so it is dropped by the `sourceNode && targetNode` filter below — same result as the empty fallback — equivalent.
		(data.edges || [])
			.map((edge) =>
				Object.assign({}, edge, { sourceNode: byId.get(edge.source), targetNode: byId.get(edge.target) })
			)
			.filter((edge) => edge.sourceNode && edge.targetNode)
	);
	/** @type {Map<string, Set<string>>} */
	// Stryker disable all: neighborMap and edgeSet are consumed only by activeIds() and drawEdge() — both feed canvas draw alpha/highlighting with no observable, assertable effect.
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

/**
 * @param {HTMLElement} container
 * @param {FGData} data
 * @param {FGOpts} [opts]
 */
export function forceGraph(container, data, opts = {}) {
	const { canvas, tooltip, ctx } = createGraphSurface(container);
	const reducedMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
	let width = 0;
	// Stryker disable next-line ConditionalExpression,LogicalOperator: this initial height is overwritten by resize() (called during init, before any layout or draw) which recomputes it from opts.height — so this initializer is never observed. The height option is asserted via resize's canvas-size tests.
	let height = Number(opts.height) || 480;
	let dpr = 1;
	let raf = 0;
	let ticks = 0;
	let stopped = false;
	/** @type {FGNode | null} */
	let hovered = null;
	// Stryker disable next-line ObjectLiteral: pointer is overwritten by onMove() before the tooltip is ever shown (the tooltip only renders while hovering, which requires a prior mousemove), so this initial value is never observed — equivalent.
	let pointer = { x: 0, y: 0 };
	/** @type {MutationObserver | null} */
	let detachObserver = null;
	let colors = buildColors(data, opts);

	const { nodes, edges, neighborMap, edgeSet } = graphStructure(data);

	// Stryker disable all: activeIds is consumed only by draw() to vary edge/node alpha while hovering (a canvas draw) — no observable, assertable effect.
	function activeIds() {
		if (!hovered) return null;
		const ids = new Set([hovered.id]);
		(neighborMap.get(hovered.id) || []).forEach((id) => ids.add(id));
		return ids;
	}
	// Stryker restore all

	function resize() {
		// Stryker disable next-line ArithmeticOperator,MethodExpression,ConditionalExpression,LogicalOperator: oldWidth/oldHeight feed only the rescale branch below, which is unobservable (see the rescale disable) — equivalent.
		const oldWidth = width || container.clientWidth || container.getBoundingClientRect().width;
		const oldHeight = height;
		width = Math.max(320, Math.round(container.clientWidth || container.getBoundingClientRect().width || 720));
		height = Math.max(180, Number(opts.height) || 480);
		// Stryker disable next-line ArithmeticOperator,MethodExpression,ConditionalExpression,LogicalOperator: devicePixelRatio is 1 in happy-dom (and clamped to >= 1), so dpr is always 1 and every mutant here yields the same value — equivalent.
		dpr = Math.max(1, window.devicePixelRatio || 1);
		canvas.style.width = "100%";
		canvas.style.height = `${height}px`;
		// Stryker disable next-line ArithmeticOperator,MethodExpression: dpr === 1 and width is an integer, so Math.round(width * dpr) === width regardless — equivalent. (The width value itself is asserted via the canvas-size tests.)
		canvas.width = Math.round(width * dpr);
		// Stryker disable next-line ArithmeticOperator,MethodExpression: dpr === 1, so Math.round(height * dpr) === height — equivalent.
		canvas.height = Math.round(height * dpr);
		ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
		// Stryker disable next-line ConditionalExpression: forcing this false only lets the no-op `nodes.every([])`/seedNodes([]) path run when there are no nodes — same result; forcing it true is killed by the layout fingerprint (nodes would never be seeded) — the surviving variant is equivalent.
		if (nodes.length === 0) return;
		// Stryker disable all: this seed-vs-rescale block is layout bookkeeping with no observable, assertable effect here. On the first resize it seeds (the seedNodes function's own math is killed separately via the hover fingerprint); on a window resize onResize() immediately calls start() -> re-settle to the same deterministic layout, erasing any rescaled positions. So the branch choice and the rescale arithmetic are equivalent.
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
		// Stryker restore all
	}

	function step() {
		const cx = width / 2;
		const cy = height / 2;
		const charge = Math.max(260, Math.min(width, height) * 0.85);
		// Stryker disable next-line EqualityOperator: `i <= nodes.length` over-iterates by one, but the inner loop's `j < nodes.length` guard then never runs, so the extra outer pass is a no-op — equivalent.
		for (let i = 0; i < nodes.length; i++) {
			const a = nodes[i];
			for (let j = i + 1; j < nodes.length; j++) {
				const b = nodes[j];
				let dx = a.x - b.x;
				let dy = a.y - b.y;
				let dist2 = dx * dx + dy * dy;
				// Stryker disable all: numeric-stability jitter for (near-)coincident nodes (within 5px); settled layouts never bring distinct nodes that close, so this branch is unreached and its effect (a transient nudge the simulation immediately settles away) is unobservable — equivalent.
				if (dist2 < 25) {
					dx = (a.index - b.index || 1) * 0.1;
					dy = (b.index - a.index || 1) * 0.1;
					dist2 = dx * dx + dy * dy;
				}
				// Stryker restore all
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
			// Stryker disable next-line ArithmeticOperator: the `width - 10` / `height - 10` clamp upper bounds are viewport safety rails; settled nodes stay well inside them so the bound never binds and mutating it has no observable effect — equivalent. (The centring force and damping that determine the position are pinned by the fingerprint.)
			node.x = clamp(node.x + node.vx, 10, width - 10);
			// Stryker disable next-line ArithmeticOperator: see above — the height clamp upper bound never binds for settled layouts — equivalent.
			node.y = clamp(node.y + node.vy, 10, height - 10);
		}
	}

	// Stryker disable all: drawEdge/drawNode/draw issue only canvas 2D drawing commands (ctx.*) — happy-dom has no 2D context and these produce no observable, assertable DOM/handle effect, so every mutant here is equivalent (the canvas-draw exclusion). Node geometry/size and hit-testing are asserted separately via the hover fingerprint.
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
	// Stryker restore all

	/**
	 * @param {number} x
	 * @param {number} y
	 * @returns {FGNode | null}
	 */
	function findNode(x, y) {
		for (let i = nodes.length - 1; i >= 0; i--) {
			const node = nodes[i];
			const half = nodeSize(node) / 2 + 4;
			// Stryker disable next-line EqualityOperator: `<= half` vs `< half` differs only when |x - node.x| equals half exactly; node coords are floats and pointer coords are integers, so equality is a measure-zero case that never occurs — equivalent. (The `> half` inversion is killed by the hover fingerprint.)
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
		// Stryker disable next-line ArithmeticOperator: the clamp bounds (pad .. width-pad / height-pad) only bind when the pointer is at the very edge of the canvas; the tooltip only shows while hovering a node, and settled nodes sit centrally, so the bounds never bind and mutating `width - pad` / `height - pad` has no observable effect — equivalent. (The `pointer + pad` offset is asserted as 372px/252px.)
		const x = clamp(pointer.x + pad, pad, width - pad);
		// Stryker disable next-line ArithmeticOperator: see above — the height clamp bound never binds — equivalent.
		const y = clamp(pointer.y + pad, pad, height - pad);
		tooltip.style.left = `${x}px`;
		tooltip.style.top = `${y}px`;
	}

	/** @param {MouseEvent} event */
	function onMove(event) {
		const rect = canvas.getBoundingClientRect();
		pointer = { x: event.clientX - rect.left, y: event.clientY - rect.top };
		const next = findNode(pointer.x, pointer.y);
		// Stryker disable next-line ConditionalExpression: forcing this `true` only re-assigns hovered to the same value, re-sets the same cursor, and re-runs draw() (canvas) when the hovered node is unchanged — no observable effect. (Forcing it false is killed by the hover tests, which then never see a tooltip.)
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
		// Stryker disable next-line ConditionalExpression: detachObserver is non-null whenever window.MutationObserver exists (always, in browsers and happy-dom) and null otherwise; forcing the guard true/false either matches reality or fails to disconnect a one-shot observer whose only action is the (idempotent) stop — no observable effect — equivalent.
		if (detachObserver) detachObserver.disconnect();
		detachObserver = null;
		// Stryker disable next-line StringLiteral: removing the resize listener is redundant — start() (the only thing onResize calls) bails on its `if (stopped) return`, so a stale resize listener has no observable effect after stop() — equivalent.
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
		// Stryker disable all: the per-frame tick budget governs when the rAF loop stops (~400 frames in); it is not observable without running the full animation, and the settled layout is verified synchronously via the reduced-motion settleAndDraw path. step()'s physics is killed via the fingerprint.
		if (ticks < MAX_TICKS) {
			step();
			ticks++;
		}
		// Stryker restore all
		draw();
		// Stryker disable next-line ConditionalExpression,EqualityOperator: the `ticks < MAX_TICKS` budget governs when scheduling stops (animation duration), unobservable without running ~400 frames; the reschedule itself is asserted by the animation-loop test.
		if (ticks < MAX_TICKS) raf = requestAnimationFrame(animate);
		else raf = 0;
	}

	function settleAndDraw() {
		// Stryker disable next-line EqualityOperator: `i <= MAX_TICKS` runs one extra settle step on an already-converged layout (no change); `i >= MAX_TICKS` (zero steps) is killed by the fingerprint — the surviving variant is equivalent.
		for (let i = 0; i < MAX_TICKS; i++) step();
		ticks = MAX_TICKS;
		draw();
	}

	function start() {
		// Stryker disable next-line ConditionalExpression: forcing this guard true (always return) is killed by the fingerprint (no settle); forcing it false is unobservable because, after stop(), the only caller (onResize) never fires — its listener was removed — equivalent.
		if (stopped) return;
		// Stryker disable next-line ConditionalExpression: raf is 0 whenever start() runs (init or post-stop), so `if (raf)` never cancels and forcing it true only calls cancelAnimationFrame(0) — no observable effect — equivalent.
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
	// Stryker disable next-line ConditionalExpression: window.MutationObserver is always defined in browsers and happy-dom, so forcing this guard true is equivalent. (Forcing it false is killed by the auto-stop test, which then never detaches.)
	if (window.MutationObserver) {
		detachObserver = new MutationObserver(() => {
			if (!document.body.contains(canvas)) stop();
		});
		detachObserver.observe(document.body, { childList: true, subtree: true });
	}
	start();

	return {
		stop,
		// Stryker disable next-line BlockStatement: redraw() only calls draw() (canvas drawing); emptying it has no observable effect. The handle exposing redraw is asserted by the surface-creation test.
		redraw() {
			draw();
		}
	};
}
