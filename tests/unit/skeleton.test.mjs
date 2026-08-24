// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "vitest";
import {
	cardGridSkeleton,
	loadingRegion,
	routeSkeletonHTML,
	skeletonBlock,
	skeletonLine,
	tableSkeleton
} from "../../public_html/lib/molecules/skeleton.js";

function textExcludingAriaHidden(node) {
	if (node.nodeType === Node.TEXT_NODE) return node.textContent || "";
	if (node.nodeType !== Node.ELEMENT_NODE) return "";
	const el = /** @type {Element} */ (node);
	if (el.getAttribute("aria-hidden") === "true") return "";
	return [...el.childNodes].map((child) => textExcludingAriaHidden(child)).join("");
}

function statusText(html) {
	document.body.innerHTML = html;
	const status = document.querySelector('[role="status"]');
	return textExcludingAriaHidden(/** @type {Element} */ (status))
		.replaceAll(/\s+/g, " ")
		.trim();
}

test("primitive skeleton placeholders are empty decorative shapes", () => {
	assert.equal(skeletonLine("skeleton--w-lg"), '<span class="skeleton skeleton--line skeleton--w-lg"></span>');
	assert.equal(skeletonBlock("skeleton--button"), '<span class="skeleton skeleton--block skeleton--button"></span>');
});

test("card grid skeletons reuse the shared card-grid templates", () => {
	const tools = cardGridSkeleton("tool");
	assert.match(tools, /class="card-grid grid-tools skeleton-grid skeleton-grid--tool"/);
	assert.equal((tools.match(/skeleton-card--tool/g) || []).length, 6);

	const lists = cardGridSkeleton("list");
	assert.match(lists, /class="card-grid grid-lists skeleton-grid skeleton-grid--list"/);
	assert.equal((lists.match(/skeleton-card--list/g) || []).length, 4);
});

test("tableSkeleton renders stable rows and columns without real cell text", () => {
	const html = tableSkeleton({ columns: 3, rows: 2, wrapClass: "recent-table-wrap", tableClass: "recent-table" });
	assert.match(html, /class="recent-table-wrap skeleton-table-wrap"/);
	assert.match(html, /class="recent-table skeleton-table"/);
	assert.equal((html.match(/<tr>/g) || []).length, 2);
	assert.equal((html.match(/<td>/g) || []).length, 6);
	assert.doesNotMatch(html, />[^<]*Loading[^<]*</);
});

test("routeSkeletonHTML chooses route-specific loading shapes", () => {
	assert.match(routeSkeletonHTML("/search"), /route-loading--search/);
	assert.match(routeSkeletonHTML("/search"), /class="browse skeleton-browse"/);
	assert.match(routeSkeletonHTML("/tools/tool-one"), /route-loading--tool/);
	assert.match(routeSkeletonHTML("/tools/tool-one"), /class="toolpage__grid"/);
	assert.match(routeSkeletonHTML("/recent"), /route-loading--table/);
	assert.match(routeSkeletonHTML("/recent"), /class="recent-table skeleton-table"/);
	assert.match(routeSkeletonHTML("/my-tools"), /class="account-records__table skeleton-table"/);
	assert.match(routeSkeletonHTML("/preferences"), /Loading preferences/);
	assert.match(routeSkeletonHTML("/preferences"), /class="account-records__table skeleton-table"/);
	assert.match(routeSkeletonHTML("/crawler-history"), /class="runs skeleton-table"/);
	assert.match(routeSkeletonHTML("/audit-logs"), /Loading audit logs/);
	assert.match(routeSkeletonHTML("/lists"), /skeleton-grid--list/);
	assert.match(routeSkeletonHTML("/lists/42"), /skeleton-grid--tool/);
	// Routes with no purpose-built shape fall back to the generic page skeleton
	// rather than to a spinner, so no route ever renders a bare loading sentence.
	assert.match(routeSkeletonHTML("/"), /route-loading--page/);
	assert.match(routeSkeletonHTML("/api-docs"), /route-loading--page/);
	assert.match(routeSkeletonHTML("/api-docs"), /skeleton-page__paragraph/);
});

test("route skeleton status text excludes hidden placeholder content", () => {
	const html = routeSkeletonHTML("/search");
	assert.match(html, /aria-hidden="true"/);
	assert.equal(statusText(html), "Loading search results");
	// The status is announced, never drawn: the shimmer is the visual signal.
	document.body.innerHTML = html;
	assert.ok(document.querySelector(".route-loading__label")?.classList.contains("visually-hidden"));
});

test("skeleton CSS is token-driven and disables shimmer for reduced motion", () => {
	const css = readFileSync("public_html/styles/molecules.css", "utf8");
	assert.match(css, /background: var\(--color-skeleton-base\)/);
	assert.match(css, /animation: skeleton-sheen 1\.2s ease-in-out infinite/);
	assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
	assert.match(css, /animation: none/);
});

test("loadingRegion announces its label and hides the shapes it wraps", () => {
	const html = loadingRegion({
		label: "Loading <everything>",
		className: "demo-loading",
		bodyClass: "demo-body",
		body: skeletonLine()
	});
	assert.match(html, /class="demo-loading" role="status" aria-live="polite" aria-atomic="true"/);
	assert.match(html, /class="demo-body" aria-hidden="true"/);
	assert.match(html, /Loading &lt;everything&gt;/);
	// Without the label the region would announce nothing at all, since the only
	// thing inside it is aria-hidden.
	assert.equal(statusText(html), "Loading <everything>");
	assert.ok(document.querySelector(".demo-loading > .visually-hidden"));
});
