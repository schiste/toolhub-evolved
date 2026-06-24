// SPDX-License-Identifier: GPL-3.0-or-later
import { dirAttrs, esc } from "../lib/core/dom.js";
import { INDEX } from "../lib/core/api.js";
import { DEMO_KEYS, DEMO_NS } from "../lib/core/store.js";
import { completeness, getUserContext, setUserContext } from "../lib/core/signals.js";
import { avatar, toolIcon } from "../lib/atoms/avatar.js";
import { completenessMeter, endorsementChip, fitChip, healthBadge, popularityBadge, statusBadge } from "../lib/atoms/badges.js";
import { button, iconButton } from "../lib/atoms/button.js";
import { TOOL_TYPES, fArea, fCheck, fInput, fSelect } from "../lib/atoms/form-fields.js";
import { ICON_NAMES, icon } from "../lib/atoms/icon.js";
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
const STYLEGUIDE_ACCOUNT_NAME = "Amina Hassan";

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

function fitChipExample() {
	const prev = getUserContext();
	const fittingTool = { ...FIXTURE_TOOL, audiences: ["editor"], forWikis: ["wikidata.org"] };
	setUserContext({ wiki: "wikidata.org", role: "editor" });
	try {
		return fitChip(fittingTool) || `<span class="signal signal--fit">${icon("check")} Fits you</span>`;
	} finally {
		setUserContext(prev);
	}
}

function listingCompletenessExample() {
	const complete = completeness(FIXTURE_TOOL);
	const rows = complete.items.map((item) => `
		<li><span class="complete-list__icon${item.ok ? "" : " complete-list__icon--empty"}">${item.ok ? icon("check") : "○"}</span><span>${esc(item.label)}</span></li>`).join("");
	return `<div class="panel">
		<h3 class="panel__title">Listing completeness</h3>
		${completenessMeter(complete)}
		<ul class="complete-list">${rows}</ul>
	</div>`;
}

function fitControlExample() {
	return `<div class="hero__context">
		<label class="hero__context-field">I work on
			<select class="hero__context-select" data-ctx-wiki>
				<option value="">Any wiki</option>
				<option value="wikidata.org" selected>Wikidata</option>
				<option value="commons.wikimedia.org">Commons</option>
			</select>
		</label>
		<label class="hero__context-field">as
			<select class="hero__context-select" data-ctx-role>
				<option value="">Anyone</option>
				<option value="editor" selected>Editor</option>
				<option value="developer">Developer</option>
			</select>
		</label>
	</div>`;
}

function accountButtonExample() {
	return `<div class="acct">
		<button class="acct__btn" id="sg-acct-btn" type="button" aria-haspopup="true" aria-expanded="false" aria-controls="sg-acct-menu">
			${avatar(STYLEGUIDE_ACCOUNT_NAME, "avatar--sm")}
			<span class="acct__name">${esc(STYLEGUIDE_ACCOUNT_NAME)}</span>
			${icon("chevronDown", "acct__caret")}
		</button>
	</div>`;
}

function experimentsToggleExample() {
	return `<div class="sg-inline-list">
		<button class="exp-toggle" type="button" role="switch" aria-checked="true">
			<span class="exp-toggle__track"><span class="exp-toggle__thumb"></span></span>
			<span class="exp-toggle__label">Prospective features on</span>
		</button>
		<button class="exp-toggle" type="button" role="switch" aria-checked="false">
			<span class="exp-toggle__track"><span class="exp-toggle__thumb"></span></span>
			<span class="exp-toggle__label">Prospective features off</span>
		</button>
	</div>`;
}

function quickViewCloseExample() {
	return `<div class="sg-qv-close-frame">
		<button class="qv__x" type="button" aria-label="Close quick view">${icon("close")}</button>
	</div>`;
}

function listEditorControlsExample() {
	return `<div class="sg-control-stack">
		<div class="le__results">
			<button class="le__result" type="button">${icon("add")} <span>Wiki Loves Monuments map</span></button>
			<button class="le__result is-in" type="button" disabled>${icon("check")} <span>Commons Pattypan</span></button>
		</div>
		<ol class="le__tools">
			<li data-tn="citation-helper"><span class="le__tn"${dirAttrs("citation-helper")}>citation-helper</span>
				<span class="le__rowact">
					${iconButton("chevronUp", "Move up", { size: "sm", attrs: 'data-move="up"' })}
					${iconButton("chevronDown", "Move down", { size: "sm", attrs: 'data-move="down"' })}
					${iconButton("close", "Remove from list", { size: "sm", variant: "danger", attrs: "data-rm" })}
				</span>
			</li>
		</ol>
	</div>`;
}

function navIconButtonExample() {
	return `<a class="icon-btn" href="#/search">${icon("search")} Search</a>`;
}

function relatedToolsExample() {
	const t = {
		name: "osm-commons-map",
		title: "OpenStreetMap Commons Map",
		maintainer: "Maps team",
	};
	const chips = ["maps", "OpenStreetMap", "Commons"].map((label) => `<span class="tag">${esc(label)}</span>`).join("");
	return `<div class="sg-related-frame">
		<section class="related" aria-labelledby="sg-related-title">
			<div class="section-head"><h2 id="sg-related-title">Related tools</h2></div>
			<p class="related__subtitle">Overlapping function and scope, by shared metadata.</p>
			<div class="related__list">
				<article class="related__item" data-tool="${esc(t.name)}" role="button" tabindex="0" aria-label="Quick look: ${esc(t.title)}">
					${avatar(t.title)}
					<div class="related__body">
						<div class="related__title"${dirAttrs(t.title)}>${esc(t.title)}</div>
						<div class="related__maint">by <span${dirAttrs(t.maintainer)}>${esc(t.maintainer)}</span></div>
						<div class="related__chips">${chips}</div>
					</div>
				</article>
			</div>
		</section>
	</div>`;
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

function buttonsSection() {
	return section("Buttons", `
		<div class="sg-examples sg-examples--buttons">
			${example("button('Primary', { variant: 'primary' })", "atoms", button("Primary", { variant: "primary" }))}
			${example("button('Outline', { variant: 'outline' })", "atoms", button("Outline", { variant: "outline" }))}
			${example("button('Subtle', { variant: 'subtle' })", "atoms", button("Subtle", { variant: "subtle" }))}
			${example("button('Danger', { variant: 'danger' })", "atoms", button("Danger", { variant: "danger" }))}
			${example("button('Small', { variant: 'primary', size: 'sm' })", "atoms", button("Small", { variant: "primary", size: "sm" }))}
			${example("button('Medium', { variant: 'primary', size: 'md' })", "atoms", button("Medium", { variant: "primary", size: "md" }))}
			${example("button('Large', { variant: 'primary', size: 'lg' })", "atoms", button("Large", { variant: "primary", size: "lg" }))}
			${example("button('Add tool', { variant: 'primary', icon: 'add' })", "atoms", button("Add tool", { variant: "primary", icon: "add" }))}
			${example("button('Edit', { variant: 'outline', icon: 'edit' })", "atoms", button("Edit", { variant: "outline", icon: "edit" }))}
			${example("button('Browse', { variant: 'outline', href: '#/search' })", "atoms", button("Browse", { variant: "outline", href: "#/search" }))}
			${example("button('Disabled', { variant: 'primary', disabled: true })", "atoms", button("Disabled", { variant: "primary", disabled: true }))}
			${example("iconButton('chevronUp', 'Move up', { size: 'sm' })", "atoms", iconButton("chevronUp", "Move up", { size: "sm" }))}
			${example("iconButton('chevronDown', 'Move down', { size: 'sm' })", "atoms", iconButton("chevronDown", "Move down", { size: "sm" }))}
			${example("iconButton('close', 'Close', { size: 'sm' })", "atoms", iconButton("close", "Close", { size: "sm" }))}
			${example("iconButton('close', 'Remove', { size: 'sm', variant: 'danger' })", "atoms", iconButton("close", "Remove", { size: "sm", variant: "danger" }))}
			${example("iconButton('search', 'Search')", "atoms", iconButton("search", "Search"))}
		</div>`);
}

function iconsSection() {
	return section("Icons", `
		<div class="sg-token-grid">
			${ICON_NAMES.map((name) => `<div class="sg-token">
				${icon(name, "icon--lg")}
				<span class="sg-token__meta"><code>${esc(name)}</code></span>
			</div>`).join("")}
		</div>`);
}

function formControlsGroup() {
	return `<div class="sg-group">
		<h3 class="sg-group__title">Form controls</h3>
		<p class="sg-group__note">Standalone search, facet, list-editor, and fit-context controls now share one control foundation.</p>
		<div class="sg-examples sg-examples--controls">
			${example("input.search__input", "atoms / shared control foundation", '<input class="search__input" id="sg-search-input" type="search" placeholder="Search tools..." autocomplete="off" />')}
			${example("input.facets__search", "atoms / shared control foundation", '<input class="facets__search" id="sg-facet-search" type="search" placeholder="Search tools..." autocomplete="off" />')}
			${example("input.le__input", "atoms / shared control foundation", '<input class="le__input" id="sg-list-editor-input" type="text" placeholder="List title" />')}
			${example("select.hero__context-select", "atoms / shared control foundation", `<select class="hero__context-select" id="sg-context-select">
				<option>Any wiki</option>
				<option selected>Wikidata</option>
				<option>Commons</option>
			</select>`)}
		</div>
	</div>`;
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
			${example("endorsementChip(5)", "atoms", endorsementChip(5))}
			${example("completenessMeter({ filled: 7, total: 9 })", "atoms", completenessMeter({ filled: 7, total: 9 }))}
			${example("fitChip(tool)", "atoms", fitChipExample())}
			${example("reviewsBlock(tool)", "atoms", reviewsBlock(FIXTURE_TOOL))}
			${example("usageBlock(tool)", "atoms", usageBlock(FIXTURE_TOOL))}
			${example("keywordTags(tool)", "atoms", `<div class="sg-inline-list">${keywordTags(FIXTURE_TOOL)}</div>`, { wide: true })}
			${example("glanceChips(tool)", "atoms", `<div class="sg-inline-list">${glanceChips(FIXTURE_TOOL)}</div>`, { wide: true })}
			${example("fInput / fArea / fCheck / fSelect", "atoms", `<div class="sg-form">
				${fInput("Tool title", "sg-tool-title", FIXTURE_TOOL.title, { req: true })}
				${fArea("Description", "sg-tool-description", FIXTURE_TOOL.description, "Shown in search results and detail pages.")}
				<div class="le__checks">${fCheck("Experimental", "sg-tool-experimental", true)}${fCheck("Deprecated", "sg-tool-deprecated", false)}</div>
				${fSelect("Tool type", "sg-tool-type", FIXTURE_TOOL.toolType, TOOL_TYPES)}
			</div>`, { wide: true })}
			${formControlsGroup()}
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
			${example(".acct__btn", "molecules", accountButtonExample())}
			${example(".exp-toggle", "organisms", experimentsToggleExample(), { wide: true })}
			${example(".qv__x", "organisms", quickViewCloseExample())}
			${example(".le__result / .le__rowact", "molecules", listEditorControlsExample(), { wide: true })}
			${example(".icon-btn", "organisms", navIconButtonExample())}
			${example(".persona navigation chip", "molecules", `<div class="sg-inline-list"><a class="persona" href="#">${icon("edit")} Editors</a><a class="persona" href="#">${icon("code")} Developers</a><a class="persona" href="#">${icon("book")} Readers</a></div>`, { wide: true })}
			${example("hero browse-axis toggle (.hero__modes)", "molecules", `<span class="hero__modes"><button class="hero__mode is-active" type="button">made for</button><button class="hero__mode" type="button">to</button></span>`)}
			${example(".hero__context fit control", "molecules", fitControlExample(), { wide: true })}
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
			${example("Listing completeness", "organisms", listingCompletenessExample())}
			${example("grid(className, items, render)", "organisms", gridHtml, { wide: true })}
			${example("quickViewBody(tool)", "organisms", `<div class="sg-quickview">${quickViewBody(FIXTURE_TOOL)}</div>`, { wide: true })}
			${example("Related tools (similarity)", "organisms", relatedToolsExample(), { wide: true })}
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
			${buttonsSection()}
			${iconsSection()}
			${atomsSection()}
			${moleculesSection()}
			${organismsSection()}
		</div>`);
	return { title: "Design system — Toolhub", html, mount: mountStyleguide };
}
