// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { communityColors, forceGraph } from "../../public_html/lib/organisms/force-graph.js";

// happy-dom has no canvas 2D context, so stub getContext with a permissive
// recorder. Draw calls have no observable effect, so we never assert on it.
function fakeCtx() {
	return new Proxy(
		{},
		{
			get: (t, p) => {
				if (p in t) return t[p];
				const v = typeof p === "string" && /^[a-z]/.test(p) ? () => {} : undefined;
				t[p] = v;
				return v;
			},
			set: () => true
		}
	);
}

let origGetContext;
let origMatchMedia;
let reduced;

beforeEach(() => {
	document.body.innerHTML = "";
	origGetContext = HTMLCanvasElement.prototype.getContext;
	HTMLCanvasElement.prototype.getContext = function (type) {
		// Only "2d" yields a context; anything else is null (so a mutated "2d" literal crashes resize()).
		return /** @type {any} */ (type === "2d" ? fakeCtx() : null);
	};
	origMatchMedia = window.matchMedia;
	reduced = true;
	// Query-sensitive: only the exact reduced-motion query reports `reduced`, so a
	// mutated media-query string resolves to false (animation path) and is caught.
	// @ts-expect-error test stub
	window.matchMedia = (q) => ({ matches: reduced && q === "(prefers-reduced-motion: reduce)" });
});

afterEach(() => {
	HTMLCanvasElement.prototype.getContext = origGetContext;
	window.matchMedia = origMatchMedia;
	document.documentElement.style.cssText = "";
	vi.restoreAllMocks();
});

function setVars(vars) {
	for (const [k, v] of Object.entries(vars)) document.documentElement.style.setProperty(k, v);
}

/** @param {any} data @param {any} [opts] */
function build(data, opts = {}) {
	const container = document.createElement("div");
	document.body.append(container);
	const handle = forceGraph(container, data, opts);
	const canvas = /** @type {HTMLCanvasElement} */ (container.querySelector("canvas"));
	const tip = /** @type {HTMLElement} */ (container.querySelector(".graph__tip"));
	return { container, handle, canvas, tip };
}

/** @param {HTMLElement} canvas @param {number} x @param {number} y */
function move(canvas, x, y) {
	canvas.dispatchEvent(new MouseEvent("mousemove", { clientX: x, clientY: y, bubbles: true }));
}

/* ---- communityColors (pure, fully observable) --------------------------- */
test("communityColors maps each community id (and its string form) through the palette", () => {
	const m = communityColors([{ id: 1 }, { id: "x" }, null, { id: 2 }], { palette: ["red", "blue"] });
	assert.equal(m.get(1), "red");
	assert.equal(m.get("1"), "red");
	assert.equal(m.get("x"), "blue");
	assert.equal(m.get(2), "blue"); // index 3 % 2 === 1 -> "blue"
	assert.equal(m.get("2"), "blue");
	assert.equal(m.get("other"), "GrayText"); // neutral fallback
	assert.equal(m.size, 6);
});

test("communityColors uses opts.neutral and the fallback colour for an empty palette", () => {
	const m = communityColors([{ id: "a" }], { neutral: "custom", palette: [] });
	assert.equal(m.get("a"), "LinkText"); // FALLBACK_COLORS.center when palette empty
	assert.equal(m.get("other"), "custom");
	assert.equal(m.size, 2);
});

test("communityColors handles null/empty meta", () => {
	const m = communityColors(null);
	assert.equal(m.get("other"), "GrayText");
	assert.equal(m.size, 1);
});

const ALL_TOKENS = {
	"--wmf-blue-aaa": "C0",
	"--wmf-green-aaa": "C1",
	"--wmf-red-aaa": "C2",
	"--wmf-orange": "C3",
	"--wmf-purple": "C4",
	"--wmf-yellow": "C5",
	"--wmf-green-light": "C6",
	"--wmf-orange-light": "C7"
};

test("communityColors derives its palette from the --wmf-* design tokens in order", () => {
	setVars({ ...ALL_TOKENS, "--color-text-muted": "MUTED" });
	// No opts.palette -> palette comes from paletteFromTokens(rootStyles()); 8 ids exercise every token.
	const ids = ["a", "b", "c", "d", "e", "f", "g", "h"];
	const m = communityColors(ids.map((id) => ({ id })));
	ids.forEach((id, i) => assert.equal(m.get(id), `C${i}`, `token[${i}]`));
	assert.equal(m.get("other"), "MUTED"); // neutral = --color-text-muted
});

test("communityColors neutral falls back to --color-border when --color-text-muted is unset", () => {
	setVars({ "--color-border": "BORD" });
	const m = communityColors([{ id: "a" }]);
	assert.equal(m.get("other"), "BORD");
});

test("communityColors filters unset palette tokens out (filter(Boolean))", () => {
	// Only the first token is set; the other 7 resolve to "" and must be dropped,
	// leaving a length-1 palette so both ids map to it.
	setVars({ "--wmf-blue-aaa": "ONLY" });
	const m = communityColors([{ id: "a" }, { id: "b" }]);
	assert.equal(m.get("a"), "ONLY");
	assert.equal(m.get("b"), "ONLY"); // index 1 % 1 === 0
});

test("communityColors falls back to design tokens when an explicit palette is empty", () => {
	setVars(ALL_TOKENS);
	// opts.palette = [] is truthy-but-empty, so the token palette is used, not the fallback colour.
	const m = communityColors([{ id: "a" }], { palette: [] });
	assert.equal(m.get("a"), "C0");
});

test("communityColors drops falsy entries from an explicit palette", () => {
	const m = communityColors([{ id: "a" }, { id: "b" }], { palette: ["X", "", "Y"] });
	assert.equal(m.get("a"), "X");
	assert.equal(m.get("b"), "Y"); // "" filtered -> palette is ["X","Y"], index 1 -> "Y"
});

test("communityColors uses fallbacks when computed styles are unavailable", () => {
	// Force rootStyles() to return null (getComputedStyle not a function).
	const orig = globalThis.getComputedStyle;
	// @ts-expect-error test stub
	globalThis.getComputedStyle = undefined;
	try {
		const m = communityColors([{ id: "a" }]);
		assert.equal(m.get("a"), "LinkText"); // empty palette -> FALLBACK_COLORS.center
		assert.equal(m.get("other"), "GrayText"); // neutral fallback chain
	} finally {
		globalThis.getComputedStyle = orig;
	}
});

/* ---- surface creation --------------------------------------------------- */
test("forceGraph builds the canvas + tooltip and returns a {stop, redraw} handle", () => {
	const container = document.createElement("div");
	container.innerHTML = "<span>stale</span>";
	document.body.append(container);
	const handle = forceGraph(container, { nodes: [], edges: [] }, {});
	assert.equal(container.querySelector("span"), null, "stale content cleared");
	// Exactly the canvas + tooltip, in order, with no stray (text) nodes from a
	// non-empty innerHTML reset.
	assert.equal(container.childNodes.length, 2);
	const canvas = /** @type {HTMLElement} */ (container.children[0]);
	const tip = /** @type {HTMLElement} */ (container.children[1]);
	assert.equal(container.firstChild, canvas);
	assert.equal(canvas.tagName, "CANVAS");
	assert.equal(canvas.className, "force-graph");
	assert.equal(canvas.getAttribute("aria-label"), "Tool similarity graph");
	assert.equal(canvas.getAttribute("role"), "img");
	assert.equal(tip.className, "graph__tip");
	assert.equal(/** @type {any} */ (tip).hidden, true);
	assert.equal(typeof handle.stop, "function");
	assert.equal(typeof handle.redraw, "function");
});

test("forceGraph sizes the canvas from container width and the height option", () => {
	const { canvas } = build({ nodes: [], edges: [] }, { height: 480 });
	assert.equal(canvas.width, 720); // max(320, 720) * dpr(1)
	assert.equal(canvas.height, 480); // max(180, 480)
	assert.equal(canvas.style.width, "100%");
	assert.equal(canvas.style.height, "480px");
});

test("forceGraph height option is floored at 180", () => {
	const { canvas } = build({ nodes: [], edges: [] }, { height: 100 });
	assert.equal(canvas.height, 180);
	assert.equal(canvas.style.height, "180px");
});

test("forceGraph honours a custom height above the floor", () => {
	const { canvas } = build({ nodes: [], edges: [] }, { height: 300 });
	assert.equal(canvas.height, 300);
	assert.equal(canvas.style.height, "300px");
});

/* ---- layout: a lone node settles to the centre -------------------------- */
test("a single node settles to the canvas centre (hit-tested via hover)", () => {
	const { canvas, tip } = build({ nodes: [{ id: "n1", title: "Node One" }], edges: [] }, { height: 480 });
	move(canvas, 360, 240); // centre
	assert.equal(tip.hidden, false);
	assert.equal(tip.textContent, "Node One");
	assert.equal(canvas.style.cursor, "pointer");
	// Tooltip is offset by +12 from the pointer.
	assert.equal(tip.style.left, "372px");
	assert.equal(tip.style.top, "252px");
	// It moved away from its seeded ring position.
	move(canvas, 423, 240);
	assert.equal(tip.hidden, true);
});

test("hovering empty space clears the hover state", () => {
	const { canvas, tip } = build({ nodes: [{ id: "n1", title: "Node One" }], edges: [] }, { height: 480 });
	move(canvas, 50, 50);
	assert.equal(tip.hidden, true);
	assert.equal(canvas.style.cursor, "");
});

test("tooltip falls back to the node id when there is no title", () => {
	const { canvas, tip } = build({ nodes: [{ id: "bare" }], edges: [] }, { height: 480 });
	move(canvas, 360, 240);
	assert.equal(tip.textContent, "bare");
});

/* ---- layout: deterministic multi-node fingerprint ----------------------- */
// Pristine settled centres captured from the un-mutated simulation. A physics
// mutation shifts at least one node and breaks the hover hit-test below.
const FP_DATA = {
	nodes: [
		{ id: "A", title: "Alpha", center: true },
		{ id: "B", title: "Beta", weight: 9 },
		{ id: "C", title: "Gamma", community: 1 }
	],
	edges: [
		{ source: "A", target: "B", weight: 0.8 },
		{ source: "B", target: "C", weight: 0.3 }
	]
};

// Scan a region and return, per node id, the exact integer bounding box of the
// pixels where that node is the top-most hit. This fingerprints the full settled
// layout (positions) AND every node's draw size + the findNode hit radius, so any
// physics / seeding / nodeSize / findNode mutation shifts a box and fails here.
function scanBoxes(canvas, tip, x0, x1, y0, y1) {
	const boxes = {};
	for (let y = y0; y <= y1; y++) {
		for (let x = x0; x <= x1; x++) {
			move(canvas, x, y);
			if (tip.hidden) continue;
			const id = /** @type {string} */ (tip.textContent);
			const b = boxes[id] || (boxes[id] = { x0: Infinity, x1: -Infinity, y0: Infinity, y1: -Infinity });
			b.x0 = Math.min(b.x0, x);
			b.x1 = Math.max(b.x1, x);
			b.y0 = Math.min(b.y0, y);
			b.y1 = Math.max(b.y1, y);
		}
	}
	return boxes;
}

test("multi-node layout + node sizing match the pristine fingerprint", () => {
	const { canvas, tip } = build(FP_DATA, { height: 480 });
	const boxes = scanBoxes(canvas, tip, 325, 410, 185, 300);
	// Captured from the un-mutated simulation. Box width/height encode node size
	// (Alpha is the larger center node), box centre encodes settled position.
	assert.deepEqual(boxes, {
		Alpha: { x0: 377, x1: 402, y0: 226, y1: 251 },
		Beta: { x0: 332, x1: 356, y0: 269, y1: 293 },
		Gamma: { x0: 339, x1: 353, y0: 193, y1: 207 }
	});
});

/* ---- pointer interactions ----------------------------------------------- */
test("mouseleave hides the tooltip and resets the cursor", () => {
	const { canvas, tip } = build({ nodes: [{ id: "n1", title: "Node One" }], edges: [] }, { height: 480 });
	move(canvas, 360, 240);
	assert.equal(tip.hidden, false);
	canvas.dispatchEvent(new MouseEvent("mouseleave", { bubbles: true }));
	assert.equal(tip.hidden, true);
	assert.equal(canvas.style.cursor, "");
});

test("clicking a hovered node calls onSelect with its id", () => {
	const onSelect = vi.fn();
	const { canvas } = build({ nodes: [{ id: "n1", title: "Node One" }], edges: [] }, { height: 480, onSelect });
	move(canvas, 360, 240);
	canvas.dispatchEvent(new MouseEvent("click", { bubbles: true }));
	expect(onSelect).toHaveBeenCalledWith("n1");
});

test("clicking with nothing hovered does not call onSelect", () => {
	const onSelect = vi.fn();
	const { canvas } = build({ nodes: [{ id: "n1", title: "Node One" }], edges: [] }, { height: 480, onSelect });
	move(canvas, 50, 50); // empty space
	canvas.dispatchEvent(new MouseEvent("click", { bubbles: true }));
	expect(onSelect).not.toHaveBeenCalled();
});

test("clicking is safe when onSelect is not provided", () => {
	const { canvas } = build({ nodes: [{ id: "n1", title: "Node One" }], edges: [] }, { height: 480 });
	move(canvas, 360, 240);
	assert.doesNotThrow(() => canvas.dispatchEvent(new MouseEvent("click", { bubbles: true })));
});

/* ---- lifecycle ---------------------------------------------------------- */
test("stop() detaches every pointer listener (mousemove, mouseleave, click)", () => {
	const onSelect = vi.fn();
	const { canvas, tip, handle } = build(
		{ nodes: [{ id: "n1", title: "Node One" }], edges: [] },
		{ height: 480, onSelect }
	);
	// Hover first so there is hover state to (not) disturb after stopping.
	move(canvas, 360, 240);
	assert.equal(tip.hidden, false);
	handle.stop();
	// mousemove listener gone: hover state frozen.
	move(canvas, 50, 50);
	assert.equal(tip.hidden, false, "mousemove no longer runs (tooltip unchanged)");
	// mouseleave listener gone: tooltip stays visible.
	canvas.dispatchEvent(new MouseEvent("mouseleave", { bubbles: true }));
	assert.equal(tip.hidden, false, "mouseleave no longer hides the tooltip");
	// click listener gone: onSelect not invoked even though a node is still hovered.
	canvas.dispatchEvent(new MouseEvent("click", { bubbles: true }));
	expect(onSelect).not.toHaveBeenCalled();
	assert.doesNotThrow(() => handle.stop()); // idempotent
});

test("redraw() is callable without throwing", () => {
	const { handle } = build({ nodes: [{ id: "n1", title: "Node One" }], edges: [] }, { height: 480 });
	assert.doesNotThrow(() => handle.redraw());
});

test("reduced motion settles synchronously without scheduling animation frames", () => {
	reduced = true;
	const raf = vi.spyOn(globalThis, "requestAnimationFrame").mockReturnValue(1);
	build({ nodes: [{ id: "n1", title: "Node One" }], edges: [] }, { height: 480 });
	expect(raf).not.toHaveBeenCalled();
});

test("without reduced motion it schedules an animation frame and stop() cancels it", () => {
	reduced = false;
	const raf = vi.spyOn(globalThis, "requestAnimationFrame").mockReturnValue(4242);
	const caf = vi.spyOn(globalThis, "cancelAnimationFrame").mockImplementation(() => {});
	const { handle } = build({ nodes: [{ id: "n1", title: "Node One" }], edges: [] }, { height: 480 });
	expect(raf).toHaveBeenCalledTimes(1);
	handle.stop();
	expect(caf).toHaveBeenCalledWith(4242);
});

test("canvas width follows the container's measured width", () => {
	const container = document.createElement("div");
	Object.defineProperty(container, "clientWidth", { configurable: true, get: () => 500 });
	document.body.append(container);
	forceGraph(container, { nodes: [], edges: [] }, { height: 480 });
	const canvas = /** @type {HTMLCanvasElement} */ (container.querySelector("canvas"));
	assert.equal(canvas.width, 500); // max(320, 500)
});

test("a window resize re-measures the canvas via the resize listener", () => {
	const container = document.createElement("div");
	let cw = 0;
	Object.defineProperty(container, "clientWidth", { configurable: true, get: () => cw });
	document.body.append(container);
	forceGraph(container, { nodes: [{ id: "n1", title: "One" }], edges: [] }, { height: 480 });
	const canvas = /** @type {HTMLCanvasElement} */ (container.querySelector("canvas"));
	assert.equal(canvas.width, 720); // clientWidth 0 -> fallback 720
	cw = 600;
	window.dispatchEvent(new Event("resize"));
	assert.equal(canvas.width, 600); // onResize re-measured (max(320, 600))
});

test("pointer position subtracts the canvas's bounding rect offset", () => {
	const { canvas, tip } = build({ nodes: [{ id: "n1", title: "Node One" }], edges: [] }, { height: 480 });
	canvas.getBoundingClientRect = () => /** @type {DOMRect} */ ({ left: 100, top: 50, width: 0, height: 0 });
	// Node sits at (360,240); to land the pointer there the client coords must be offset.
	move(canvas, 460, 290);
	assert.equal(tip.hidden, false);
	assert.equal(tip.textContent, "Node One");
});

test("a graph with no nodes data renders no hoverable nodes", () => {
	// data.nodes defaults to [] — exercises the `|| []` fallback. A mutated fallback
	// (a non-empty array) would create a phantom node detectable by hover.
	const { canvas, tip } = build({}, { height: 480 });
	for (let y = 12; y < 478; y += 3) {
		for (let x = 12; x < 712; x += 3) {
			move(canvas, x, y);
			if (!tip.hidden) throw new Error(`unexpected hover at ${x},${y}`);
		}
	}
});

test("edges to non-existent nodes are dropped (not fed to the simulation)", () => {
	// The dangling edge's endpoints don't resolve; if the filter kept it, step()
	// would read undefined.x and the build would throw.
	assert.doesNotThrow(() =>
		build(
			{
				nodes: [
					{ id: "n1", title: "One" },
					{ id: "n2", title: "Two" }
				],
				edges: [
					{ source: "n1", target: "n2", weight: 0.5 },
					{ source: "n1", target: "ghost", weight: 0.5 }
				]
			},
			{ height: 480 }
		)
	);
});

test("moving off a node (via mousemove) clears the cursor", () => {
	const { canvas } = build({ nodes: [{ id: "n1", title: "Node One" }], edges: [] }, { height: 480 });
	move(canvas, 360, 240); // onto node
	assert.equal(canvas.style.cursor, "pointer");
	move(canvas, 50, 50); // off node, via onMove's else branch
	assert.equal(canvas.style.cursor, "");
});

test("reduced motion stop() does not cancel a frame it never scheduled", () => {
	reduced = true;
	const caf = vi.spyOn(globalThis, "cancelAnimationFrame").mockImplementation(() => {});
	const { handle } = build({ nodes: [{ id: "n1", title: "Node One" }], edges: [] }, { height: 480 });
	handle.stop();
	expect(caf).not.toHaveBeenCalled(); // raf was 0, so `if (raf)` must stay false
});

test("after stop(), a window resize does not restart the animation", () => {
	reduced = false;
	const raf = vi.spyOn(globalThis, "requestAnimationFrame").mockReturnValue(7);
	vi.spyOn(globalThis, "cancelAnimationFrame").mockImplementation(() => {});
	const { handle } = build({ nodes: [{ id: "n1", title: "Node One" }], edges: [] }, { height: 480 });
	handle.stop();
	raf.mockClear();
	window.dispatchEvent(new Event("resize"));
	expect(raf).not.toHaveBeenCalled(); // start() must bail on `if (stopped) return`
});

test("the animation loop steps, reschedules, and self-stops when detached", () => {
	reduced = false;
	let frame = /** @type {null | (() => void)} */ (null);
	const raf = vi.spyOn(globalThis, "requestAnimationFrame").mockImplementation((cb) => {
		frame = /** @type {() => void} */ (cb);
		return 1;
	});
	const { container, canvas, tip } = build({ nodes: [{ id: "n1", title: "Node One" }], edges: [] }, { height: 480 });
	assert.equal(typeof frame, "function"); // start() scheduled animate
	raf.mockClear();
	/** @type {() => void} */ (frame)(); // run one frame while attached
	expect(raf).toHaveBeenCalledTimes(1); // it reschedules the next frame
	// Detach and run a frame: animate() must self-stop (listeners detached).
	container.remove();
	raf.mockClear();
	/** @type {() => void} */ (frame)();
	expect(raf).not.toHaveBeenCalled();
	document.body.append(canvas);
	move(canvas, 360, 240);
	assert.equal(tip.hidden, true, "listeners were detached by the self-stop");
});

test("after stop() the animation frame does not reschedule itself", () => {
	reduced = false;
	let frame = /** @type {null | (() => void)} */ (null);
	const raf = vi.spyOn(globalThis, "requestAnimationFrame").mockImplementation((cb) => {
		frame = /** @type {() => void} */ (cb);
		return 1;
	});
	vi.spyOn(globalThis, "cancelAnimationFrame").mockImplementation(() => {});
	const { handle } = build({ nodes: [{ id: "n1", title: "Node One" }], edges: [] }, { height: 480 });
	handle.stop(); // sets stopped = true
	raf.mockClear();
	// Canvas is still attached, so only the `stopped` flag can halt the loop.
	/** @type {() => void} */ (frame)();
	expect(raf).not.toHaveBeenCalled();
});

test("removing the canvas from the DOM stops the graph via MutationObserver", async () => {
	const onSelect = vi.fn();
	const { container, canvas, tip } = build(
		{ nodes: [{ id: "n1", title: "Node One" }], edges: [] },
		{ height: 480, onSelect }
	);
	// Remove the canvas from WITHIN the still-attached container: a subtree
	// mutation that the observer only sees with subtree:true.
	container.removeChild(canvas);
	await Promise.resolve();
	await new Promise((r) => {
		setTimeout(r, 0);
	});
	document.body.append(canvas); // re-attach only the canvas to test listeners
	move(canvas, 360, 240);
	assert.equal(tip.hidden, true, "graph stopped: listeners detached");
});

test("a DOM mutation that leaves the canvas attached does NOT stop the graph", () => {
	const { canvas, tip } = build({ nodes: [{ id: "n1", title: "Node One" }], edges: [] }, { height: 480 });
	// Mutate the body while the canvas stays present; the observer must not stop().
	document.body.append(document.createElement("div"));
	return new Promise((resolve) => {
		setTimeout(resolve, 0);
	}).then(() => {
		move(canvas, 360, 240);
		assert.equal(tip.hidden, false, "graph still live: hover works");
		assert.equal(tip.textContent, "Node One");
	});
});
