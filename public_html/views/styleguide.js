// SPDX-License-Identifier: GPL-3.0-or-later
import { esc } from "../lib/core/dom.js";
import { INDEX } from "../lib/core/api.js";
import { DEMO_KEYS, DEMO_NS } from "../lib/core/store.js";
import { avatar, toolIcon } from "../lib/atoms/avatar.js";
import { healthBadge, popularityBadge, statusBadge } from "../lib/atoms/badges.js";
import { TOOL_TYPES, fArea, fCheck, fInput, fSelect } from "../lib/atoms/form-fields.js";
import { glanceChips, keywordTags, linkOut, metaItem, wikiLabel } from "../lib/atoms/labels.js";
import { reviewsBlock, usageBlock } from "../lib/atoms/signals.js";
import { renderFacetGroup } from "../lib/molecules/facet-group.js";
import { favBtn } from "../lib/molecules/favbtn.js";
import { renderPager } from "../lib/molecules/pager.js";
import { saveToListControl } from "../lib/molecules/savemenu.js";
import { grid } from "../lib/organisms/grid.js";
import { listCard } from "../lib/organisms/list-card.js";
import { quickViewBody } from "../lib/organisms/quickview.js";
import { toolCard } from "../lib/organisms/tool-card.js";
import {
	FIXTURE_FACET_GROUP,
	FIXTURE_FACETS,
	FIXTURE_LIST,
	FIXTURE_SELECTED_FACETS,
	FIXTURE_TOOL,
	FIXTURE_TOOL_DEPRECATED,
	FIXTURE_TOOL_EXPERIMENTAL,
} from "./_fixtures.js";

const STYLEGUIDE_TOOLS = [FIXTURE_TOOL, FIXTURE_TOOL_DEPRECATED, FIXTURE_TOOL_EXPERIMENTAL];

const FALLBACK_TOKENS = {
	colors: [
		"--color-surface", "--color-surface-muted", "--color-surface-pattern", "--color-row-hover",
		"--color-overlay-modal", "--color-badge-neutral", "--color-border", "--color-border-hover",
		"--color-border-accent", "--color-text", "--color-text-secondary", "--color-text-muted",
		"--color-progressive", "--color-progressive-hover", "--color-progressive-subtle",
		"--color-interactive-subtle", "--color-hero-tint", "--color-favorite", "--color-success",
		"--color-success-subtle", "--color-destructive", "--color-destructive-subtle", "--color-warning",
		"--color-warning-subtle", "--color-warning-text",
	],
	wmf: [
		"--wmf-white", "--wmf-green-aaa", "--wmf-blue-aaa", "--wmf-red-aaa", "--wmf-orange",
		"--wmf-yellow", "--wmf-purple", "--wmf-red-light", "--wmf-orange-light", "--wmf-green-light",
	],
	fs: ["--fs-caption", "--fs-body", "--fs-subtitle", "--fs-title", "--fs-headline", "--fs-display"],
	radius: ["--radius-sm", "--radius-md", "--radius-lg", "--radius-pill"],
	shadow: ["--shadow", "--shadow-hover", "--shadow-popover", "--shadow-modal", "--shadow-sm"],
	space: ["--space-0", "--space-1", "--space-2", "--space-3", "--space-4", "--space-5", "--space-6", "--space-7", "--space-8"],
};

function seedFixtureIndex() {
	STYLEGUIDE_TOOLS.forEach((tool) => { INDEX[tool.name] = tool; });
}

function withStyleguideDemoState(render) {
	if (typeof localStorage === "undefined") return render();
	const favKey = DEMO_NS + DEMO_KEYS.favorites;
	const listsKey = DEMO_NS + DEMO_KEYS.lists;
	const prevFavs = localStorage.getItem(favKey);
	const prevLists = localStorage.getItem(listsKey);
	const lists = [
		{
			id: "demo-styleguide-campaign",
			title: FIXTURE_LIST.title,
			description: FIXTURE_LIST.description,
			tools: [FIXTURE_TOOL.name, FIXTURE_TOOL_EXPERIMENTAL.name],
		},
		{
			id: "demo-styleguide-review",
			title: "Review queue",
			description: "Tools saved for later evaluation.",
			tools: [FIXTURE_TOOL_DEPRECATED.name],
		},
	];
	try {
		localStorage.setItem(favKey, JSON.stringify([FIXTURE_TOOL_DEPRECATED.name]));
		localStorage.setItem(listsKey, JSON.stringify(lists));
		return render();
	} finally {
		if (prevFavs == null) localStorage.removeItem(favKey);
		else localStorage.setItem(favKey, prevFavs);
		if (prevLists == null) localStorage.removeItem(listsKey);
		else localStorage.setItem(listsKey, prevLists);
	}
}

function section(title, body) {
	return `<section class="sg-section" aria-labelledby="sg-${esc(title.toLowerCase().replace(/\s+/g, "-"))}">
		<h2 class="sg-section__title" id="sg-${esc(title.toLowerCase().replace(/\s+/g, "-"))}">${esc(title)}</h2>
		${body}
	</section>`;
}

function example(name, layer, html, opts) {
	opts = opts || {};
	const shown = html || '<span class="sg-empty">No visual markup in this state.</span>';
	return `<figure class="sg-example${opts.wide ? " sg-example--wide" : ""}${opts.compact ? " sg-example--compact" : ""}">
		<div class="sg-example__demo">${shown}</div>
		<figcaption class="sg-example__caption"><code>${esc(name)}</code><span>${esc(layer)}</span></figcaption>
	</figure>`;
}

function tokenSection() {
	return section("Tokens", `
		<div class="sg-token-block">
			<h3 class="sg-token-block__title">Semantic colors</h3>
			<div class="sg-token-grid sg-token-grid--colors" id="sg-color-tokens" aria-live="polite"></div>
		</div>
		<div class="sg-token-block">
			<h3 class="sg-token-block__title">Raw Wikimedia palette</h3>
			<div class="sg-token-grid sg-token-grid--colors" id="sg-wmf-tokens" aria-live="polite"></div>
		</div>
		<div class="sg-token-block">
			<h3 class="sg-token-block__title">Type scale</h3>
			<div class="sg-token-stack" id="sg-type-tokens" aria-live="polite"></div>
		</div>
		<div class="sg-token-split">
			<div class="sg-token-block">
				<h3 class="sg-token-block__title">Radii</h3>
				<div class="sg-token-grid" id="sg-radius-tokens" aria-live="polite"></div>
			</div>
			<div class="sg-token-block">
				<h3 class="sg-token-block__title">Shadows</h3>
				<div class="sg-token-grid" id="sg-shadow-tokens" aria-live="polite"></div>
			</div>
		</div>
		<div class="sg-token-block">
			<h3 class="sg-token-block__title">Spacing</h3>
			<div class="sg-token-stack" id="sg-space-tokens" aria-live="polite"></div>
		</div>`);
}

function atomsSection() {
	return section("Atoms", `
		<div class="sg-examples">
			${example("avatar(title)", "atoms", avatar("Citation Helper"))}
			${example('toolIcon(tool, "lg")', "atoms", toolIcon(FIXTURE_TOOL, "lg"))}
			${example("statusBadge(healthy)", "atoms", statusBadge(FIXTURE_TOOL))}
			${example("statusBadge(deprecated)", "atoms", statusBadge(FIXTURE_TOOL_DEPRECATED))}
			${example("statusBadge(experimental)", "atoms", statusBadge(FIXTURE_TOOL_EXPERIMENTAL))}
			${example("healthBadge(tool)", "atoms", healthBadge(FIXTURE_TOOL))}
			${example("popularityBadge(tool)", "atoms", popularityBadge(FIXTURE_TOOL))}
			${example("reviewsBlock(tool)", "atoms", reviewsBlock(FIXTURE_TOOL))}
			${example("usageBlock(tool)", "atoms", usageBlock(FIXTURE_TOOL))}
			${example("keywordTags(tool)", "atoms", `<div class="sg-inline-list">${keywordTags(FIXTURE_TOOL)}</div>`, { wide: true })}
			${example("glanceChips(tool)", "atoms", `<div class="sg-inline-list">${glanceChips(FIXTURE_TOOL)}</div>`, { wide: true })}
			${example(".btn variants", "atoms", `<div class="sg-inline-list">
				<button class="btn btn--primary" type="button">Primary</button>
				<button class="btn btn--outline" type="button">Outline</button>
				<button class="btn btn--primary btn--lg" type="button">Large</button>
				<button class="btn btn--outline" type="button" disabled>Disabled</button>
			</div>`, { wide: true })}
			${example("fInput / fArea / fCheck / fSelect", "atoms", `<div class="sg-form">
				${fInput("Tool title", "sg-tool-title", FIXTURE_TOOL.title, { req: true })}
				${fArea("Description", "sg-tool-description", FIXTURE_TOOL.description, "Shown in search results and detail pages.")}
				<div class="le__checks">${fCheck("Experimental", "sg-tool-experimental", true)}${fCheck("Deprecated", "sg-tool-deprecated", false)}</div>
				${fSelect("Tool type", "sg-tool-type", FIXTURE_TOOL.toolType, TOOL_TYPES)}
			</div>`, { wide: true })}
			${example("metaItem(key, value)", "atoms", `<div class="detail__meta">${metaItem("License", FIXTURE_TOOL.license)}${metaItem("Wikis", wikiLabel(FIXTURE_TOOL.forWikis))}</div>`, { wide: true })}
			${example("linkOut(label, url)", "atoms", linkOut("Repository", FIXTURE_TOOL.repository))}
		</div>`);
}

function moleculesSection() {
	return section("Molecules", `
		<div class="sg-examples">
			${example("favBtn(name)", "molecules", favBtn(FIXTURE_TOOL.name, { label: true }))}
			${example("favBtn(savedName)", "molecules", favBtn(FIXTURE_TOOL_DEPRECATED.name, { label: true }))}
			${example("saveToListControl(name)", "molecules", saveToListControl(FIXTURE_TOOL.name), { wide: true })}
			${example("renderFacetGroup(group, facets, selected)", "molecules", renderFacetGroup(FIXTURE_FACET_GROUP, FIXTURE_FACETS, FIXTURE_SELECTED_FACETS), { wide: true })}
			${example("renderPager(2, 7)", "molecules", `<nav class="pager" aria-label="Pagination">${renderPager(2, 7)}</nav>`, { wide: true })}
		</div>`);
}

function organismsSection() {
	const gridHtml = grid("grid-tools", [FIXTURE_TOOL, FIXTURE_TOOL_EXPERIMENTAL, FIXTURE_TOOL_DEPRECATED], (tool, i) => toolCard(tool, i === 1 ? { popular: true, rank: 2 } : {}));
	return section("Organisms", `
		<div class="sg-examples sg-examples--organisms">
			${example("toolCard(tool)", "organisms", toolCard(FIXTURE_TOOL))}
			${example("toolCard(tool, { popular: true, rank: 1 })", "organisms", toolCard(FIXTURE_TOOL, { popular: true, rank: 1 }))}
			${example("toolCard(deprecatedTool)", "organisms", toolCard(FIXTURE_TOOL_DEPRECATED))}
			${example("listCard(list)", "organisms", listCard(FIXTURE_LIST))}
			${example("panel (sidebar)", "organisms", `<div class="panel"><h3 class="panel__title">Browse by need</h3><p style="margin:0;color:var(--color-text-secondary);font-size:var(--fs-caption)">Borderless sidebar block: a rule under the title and content flush below, matching the main-content section heads.</p></div>`)}
			${example("grid(className, items, render)", "organisms", gridHtml, { wide: true })}
			${example("quickViewBody(tool)", "organisms", `<div class="sg-quickview">${quickViewBody(FIXTURE_TOOL)}</div>`, { wide: true })}
		</div>`);
}

function collectCustomPropertyNames(prefix, fallback) {
	const names = [];
	const seen = new Set();
	const visitRules = (rules) => {
		Array.from(rules || []).forEach((rule) => {
			if (rule.cssRules) {
				try { visitRules(rule.cssRules); } catch (e) {}
			}
			if (!rule.style) return;
			Array.from(rule.style).forEach((prop) => {
				if (!prop.startsWith(prefix) || seen.has(prop)) return;
				seen.add(prop);
				names.push(prop);
			});
		});
	};
	Array.from(document.styleSheets || []).forEach((sheet) => {
		try { visitRules(sheet.cssRules); } catch (e) {}
	});
	return names.length ? names : fallback;
}

function resolveToken(name, cssProp) {
	const probe = document.createElement("span");
	probe.style.position = "absolute";
	probe.style.display = "block";
	probe.style.visibility = "hidden";
	probe.style.pointerEvents = "none";
	probe.style[cssProp] = `var(${name})`;
	document.body.appendChild(probe);
	const value = getComputedStyle(probe)[cssProp];
	probe.remove();
	return value || getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function renderColorTokens(targetId, names) {
	const target = document.getElementById(targetId);
	if (!target) return;
	target.innerHTML = names.map((name) => {
		const value = resolveToken(name, "backgroundColor");
		return `<div class="sg-token sg-token--color">
			<span class="sg-token__swatch" style="background: var(${esc(name)})"></span>
			<span class="sg-token__meta"><code>${esc(name)}</code><span>${esc(value)}</span></span>
		</div>`;
	}).join("");
}

function renderTypeTokens(names) {
	const target = document.getElementById("sg-type-tokens");
	if (!target) return;
	target.innerHTML = names.map((name) => {
		const value = resolveToken(name, "fontSize");
		return `<div class="sg-type-row">
			<div class="sg-type-row__specimen" style="font-size: var(${esc(name)})">Toolhub Aa 123</div>
			<div class="sg-type-row__meta"><code>${esc(name)}</code><span>${esc(value)}</span></div>
		</div>`;
	}).join("");
}

function renderRadiusTokens(names) {
	const target = document.getElementById("sg-radius-tokens");
	if (!target) return;
	target.innerHTML = names.map((name) => {
		const value = resolveToken(name, "borderRadius");
		return `<div class="sg-token">
			<span class="sg-radius-box" style="border-radius: var(${esc(name)})"></span>
			<span class="sg-token__meta"><code>${esc(name)}</code><span>${esc(value)}</span></span>
		</div>`;
	}).join("");
}

function renderShadowTokens(names) {
	const target = document.getElementById("sg-shadow-tokens");
	if (!target) return;
	target.innerHTML = names.map((name) => {
		const value = resolveToken(name, "boxShadow");
		return `<div class="sg-token">
			<span class="sg-shadow-box" style="box-shadow: var(${esc(name)})"></span>
			<span class="sg-token__meta"><code>${esc(name)}</code><span>${esc(value)}</span></span>
		</div>`;
	}).join("");
}

function renderSpaceTokens(names) {
	const target = document.getElementById("sg-space-tokens");
	if (!target) return;
	target.innerHTML = names.map((name) => {
		const value = resolveToken(name, "width");
		return `<div class="sg-space-row">
			<div class="sg-space-row__bar"><span style="width: var(${esc(name)})"></span></div>
			<div class="sg-space-row__meta"><code>${esc(name)}</code><span>${esc(value)}</span></div>
		</div>`;
	}).join("");
}

function mountStyleguide() {
	seedFixtureIndex();
	const colorTokens = collectCustomPropertyNames("--color-", FALLBACK_TOKENS.colors);
	const wmfTokens = collectCustomPropertyNames("--wmf-", FALLBACK_TOKENS.wmf);
	renderColorTokens("sg-color-tokens", colorTokens);
	renderColorTokens("sg-wmf-tokens", wmfTokens);
	renderTypeTokens(collectCustomPropertyNames("--fs-", FALLBACK_TOKENS.fs));
	renderRadiusTokens(collectCustomPropertyNames("--radius-", FALLBACK_TOKENS.radius));
	renderShadowTokens(collectCustomPropertyNames("--shadow", FALLBACK_TOKENS.shadow));
	renderSpaceTokens(collectCustomPropertyNames("--space-", FALLBACK_TOKENS.space));

	const page = document.querySelector(".sg-page");
	if (!page) return;
	page.addEventListener("click", (e) => {
		if (e.target.closest("[data-tool], [data-fav], [data-listadd], [data-q]")) {
			e.preventDefault();
			e.stopPropagation();
		}
	}, true);
	page.addEventListener("keydown", (e) => {
		if ((e.key === "Enter" || e.key === " ") && e.target.closest("[data-tool]")) {
			e.preventDefault();
			e.stopPropagation();
		}
	}, true);
}

export function viewStyleguide() {
	seedFixtureIndex();
	const html = withStyleguideDemoState(() => `
		<div class="container page sg-page">
			<h1 class="page__title">Design system</h1>
			<p class="page__intro">A living reference for Toolhub tokens and component functions, rendered from the same modules used by the application.</p>
			${tokenSection()}
			${atomsSection()}
			${moleculesSection()}
			${organismsSection()}
		</div>`);
	return { title: "Design system — Toolhub", html, mount: mountStyleguide };
}
