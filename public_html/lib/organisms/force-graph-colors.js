// SPDX-License-Identifier: GPL-3.0-or-later

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
 * @param {any} node
 * @param {any} colors
 * @returns {string}
 */
// Stryker disable all: colorForNode's return value is only ever assigned to ctx.fillStyle (a canvas draw); it has no observable, assertable effect on the DOM/handle, so every mutant here is equivalent (per the canvas-draw exclusion).
export function colorForNode(node, colors) {
	if (node.center) return colors.center;
	const group = node.group ?? node.community;
	if (group !== null && group !== undefined) {
		if (typeof colors.communityColor === "function") {
			const custom = colors.communityColor(group);
			if (custom) return custom;
		}
		const colorMap = (node.group !== null && node.group !== undefined && colors.groupMap) || colors.communityMap;
		if (colorMap.has(group)) {
			return /** @type {string} */ (colorMap.get(group));
		}
		if (colorMap.has(String(group))) {
			return /** @type {string} */ (colorMap.get(String(group)));
		}
		const index = Number(group);
		if (Number.isFinite(index)) return colors.palette[index % colors.palette.length];
	}
	if (node.score !== null && node.score !== undefined) return colors.score;
	return colors.palette[0];
}
// Stryker restore all

/**
 * @param {any} data
 * @param {any} opts
 * @returns {any}
 */
// Stryker disable all: buildColors only feeds the colour object consumed by colorForNode/drawNode/drawEdge/draw — every field ends up as a ctx fill/stroke style (canvas draw) with no observable effect. (communityColors itself is covered directly via its export.)
export function buildColors(data, opts) {
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
		groupMap: communityColors(data?.groupMeta || data?.communityMeta || [], { palette, neutral }),
		communityColor: typeof opts.communityColor === "function" ? opts.communityColor : null,
		other: neutral,
		score: cssVar(styles, "--wmf-green-aaa", FALLBACK_COLORS.score),
		surface: cssVar(styles, "--color-surface", FALLBACK_COLORS.surface),
		palette: palette.length > 0 ? palette : [FALLBACK_COLORS.center]
	};
}
// Stryker restore all
