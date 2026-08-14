// SPDX-License-Identifier: GPL-3.0-or-later
import { $, $$, esc, wrapTabFocus } from "../core/dom.js";
import { fmt, t } from "../core/i18n.js";
import { navigateTo } from "../core/routing.js";
import { icon } from "../atoms/icon.js";

const PALETTE_ID = "command-palette";
const INPUT_ID = "command-input";
const LIST_ID = "command-list";
const STATUS_ID = "command-status";
const OPTION_PREFIX = "command-option-";

/** @type {HTMLElement | null} */
let lastFocus = null;
let activeIndex = 0;
/** @type {CommandItem[]} */
let currentItems = [];
/** @type {(() => void) | null} */
let beforeOpen = null;

/**
 * @typedef {object} CommandAction
 * @property {string} id
 * @property {string} title
 * @property {string} description
 * @property {string} href
 * @property {string} iconName
 * @property {string[]} keywords
 */
/**
 * @typedef {CommandAction & { search?: boolean }} CommandItem
 */

/** @param {string} platform */
function isApplePlatform(platform) {
	return /mac|iphone|ipad|ipod/i.test(platform);
}

/** @param {string} [platform] */
export function shortcutLabel(platform = "") {
	const raw =
		platform ||
		String(
			("userAgentData" in navigator &&
				/** @type {{ userAgentData?: { platform?: string } }} */ (navigator).userAgentData?.platform) ||
				navigator.platform ||
				""
		);
	return isApplePlatform(raw) ? "⌘ K" : "Ctrl K";
}

/** @param {EventTarget | null} target */
export function isEditableTarget(target) {
	if (!(target instanceof Element)) return false;
	const tag = target.tagName.toLowerCase();
	const editable = target.closest("[contenteditable]");
	const editableValue = editable?.getAttribute("contenteditable");
	return (
		tag === "input" ||
		tag === "textarea" ||
		tag === "select" ||
		(editable !== null && editableValue !== "false") ||
		target.closest('[role="combobox"], [role="searchbox"], [role="textbox"]') !== null
	);
}

/**
 * @param {KeyboardEvent} event
 * @returns {boolean}
 */
export function isPaletteShortcut(event) {
	if (event.defaultPrevented || isEditableTarget(event.target)) return false;
	const key = event.key.toLowerCase();
	if (key === "k" && (event.metaKey || event.ctrlKey) && !event.altKey && !event.shiftKey) return true;
	return event.key === "/" && !event.metaKey && !event.ctrlKey && !event.altKey && !event.shiftKey;
}

function actions() {
	return [
		{
			id: "browse",
			title: t("commandPalette.browseTools", "Browse tools"),
			description: t("commandPalette.browseToolsDesc", "Search and filter the live Toolhub catalog."),
			href: "/search",
			iconName: "search",
			keywords: ["tools", "search", "browse", "catalog"]
		},
		{
			id: "my-tools",
			title: t("commandPalette.myTools", "My tools"),
			description: t(
				"commandPalette.myToolsDesc",
				"Review maintained tools, register toolinfo, analyze source code, and manage local submissions."
			),
			href: "/my-tools",
			iconName: "tools",
			keywords: ["maintainer", "owned", "account", "submit", "create", "register", "toolinfo", "source", "scopes"]
		},
		{
			id: "favorites",
			title: t("commandPalette.favorites", "Favorites"),
			description: t("commandPalette.favoritesDesc", "Open saved tools."),
			href: "/favorites",
			iconName: "star",
			keywords: ["saved", "starred"]
		},
		{
			id: "lists",
			title: t("commandPalette.lists", "Lists"),
			description: t("commandPalette.listsDesc", "Browse and manage curated tool lists."),
			href: "/lists",
			iconName: "list",
			keywords: ["collections", "curated"]
		},
		{
			id: "map",
			title: t("commandPalette.map", "Map"),
			description: t("commandPalette.mapDesc", "Explore related tools as a graph."),
			href: "/graph",
			iconName: "globe",
			keywords: ["graph", "relationships", "network"]
		},
		{
			id: "people",
			title: t("commandPalette.people", "People"),
			description: t("commandPalette.peopleDesc", "Find tool authors and maintainers."),
			href: "/people",
			iconName: "group",
			keywords: ["people", "authors", "maintainers", "profiles", "contributors"]
		},
		{
			id: "recent",
			title: t("commandPalette.recent", "Recent"),
			description: t("commandPalette.recentDesc", "See recent Toolhub catalog changes."),
			href: "/recent",
			iconName: "history",
			keywords: ["changes", "activity"]
		},
		{
			id: "crawler",
			title: t("commandPalette.crawlerHistory", "Crawler history"),
			description: t("commandPalette.crawlerHistoryDesc", "Inspect crawler runs and metadata updates."),
			href: "/crawler-history",
			iconName: "history",
			keywords: ["crawler", "toolinfo", "metadata"]
		},
		{
			id: "audit",
			title: t("commandPalette.auditLogs", "Audit logs"),
			description: t("commandPalette.auditLogsDesc", "Review Toolhub audit activity."),
			href: "/audit-logs",
			iconName: "report",
			keywords: ["audit", "logs", "moderation"]
		},
		{
			id: "api",
			title: t("commandPalette.apiDocs", "API explorer"),
			description: t("commandPalette.apiDocsDesc", "Run read-only endpoints and copy API examples."),
			href: "/api-docs",
			iconName: "code",
			keywords: ["api", "schema", "openapi", "docs", "explorer", "curl", "fetch"]
		},
		{
			id: "mcp",
			title: t("commandPalette.mcp", "MCP server"),
			description: t("commandPalette.mcpDesc", "Connect an AI assistant to catalog discovery."),
			href: "/mcp-server",
			iconName: "code",
			keywords: ["mcp", "llm", "ai", "claude", "prior art", "discovery", "assistant"]
		},
		{
			id: "developer",
			title: t("commandPalette.developerSettings", "Developer settings"),
			description: t("commandPalette.developerSettingsDesc", "Manage Evolved developer features."),
			href: "/developer-settings",
			iconName: "key",
			keywords: ["developer", "toolinfo", "signing", "keys", "settings"]
		},
		{
			id: "preferences",
			title: t("commandPalette.preferences", "Preferences"),
			description: t(
				"commandPalette.preferencesDesc",
				"Manage Evolved-specific settings and local account data."
			),
			href: "/preferences",
			iconName: "system",
			keywords: ["account", "settings", "preferences", "export", "delete", "data"]
		},
		{
			id: "styleguide",
			title: t("commandPalette.styleguide", "Design system"),
			description: t("commandPalette.styleguideDesc", "View tokens, components, and UI examples."),
			href: "/styleguide",
			iconName: "book",
			keywords: ["styleguide", "design", "tokens", "components"]
		}
	];
}

/** @param {string} value */
function norm(value) {
	return value.toLowerCase().trim();
}

/**
 * @param {CommandAction} action
 * @param {string[]} terms
 */
function matches(action, terms) {
	if (terms.length === 0) return true;
	const haystack = norm([action.title, action.description, action.href, ...action.keywords].join(" "));
	return terms.every((term) => haystack.includes(term));
}

/** @param {string} query */
export function commandItems(query) {
	const clean = query.trim();
	const terms = norm(clean).split(/\s+/).filter(Boolean);
	/** @type {CommandItem[]} */
	const items = clean
		? [
				{
					id: "search",
					title: t("commandPalette.searchFor", "Search Toolhub for “$1”", clean),
					description: t("commandPalette.searchForDesc", "Open full search results."),
					href: `/search?q=${encodeURIComponent(clean)}`,
					iconName: "search",
					keywords: [],
					search: true
				}
			]
		: [];
	return [...items, ...actions().filter((action) => matches(action, terms))];
}

/** @param {number} index */
function optionId(index) {
	return `${OPTION_PREFIX}${index}`;
}

function palette() {
	return $(`#${PALETTE_ID}`);
}

function input() {
	return /** @type {HTMLInputElement | null} */ ($(`#${INPUT_ID}`));
}

function list() {
	return $(`#${LIST_ID}`);
}

function status() {
	return $(`#${STATUS_ID}`);
}

export function syncCommandPaletteChrome() {
	const shortcut = shortcutLabel();
	$("[data-command-shortcut]")?.replaceChildren(shortcut);
	$("[aria-controls='command-palette']")?.setAttribute(
		"aria-label",
		t("commandPalette.openWithShortcut", "Search tools and actions ($1)", shortcut)
	);
}

/** @param {boolean} on */
function setPageInert(on) {
	$$("body > *").forEach((el) => {
		if (el.id === PALETTE_ID || el.tagName === "SCRIPT") return;
		if ("inert" in el) el.inert = on;
		if (on) el.setAttribute("aria-hidden", "true");
		else el.removeAttribute("aria-hidden");
	});
}

function render() {
	const field = input();
	const results = list();
	const live = status();
	if (!field || !results) return;
	currentItems = commandItems(field.value);
	activeIndex = currentItems.length === 0 ? -1 : Math.min(Math.max(activeIndex, 0), currentItems.length - 1);
	field.setAttribute("aria-activedescendant", activeIndex >= 0 ? optionId(activeIndex) : "");
	if (currentItems.length === 0) {
		results.innerHTML = `<li class="command-palette__empty" role="option" aria-disabled="true">${t("commandPalette.noResults", "No matching actions")}</li>`;
		if (live) live.textContent = t("commandPalette.noResults", "No matching actions");
		return;
	}
	results.innerHTML = currentItems
		.map(
			(item, index) => `<li role="presentation">
				<button class="command-palette__item${index === activeIndex ? " is-active" : ""}" id="${optionId(index)}" type="button" role="option" aria-selected="${index === activeIndex}" tabindex="-1" data-command-index="${index}">
					<span class="command-palette__item-icon" aria-hidden="true">${icon(item.iconName)}</span>
					<span class="command-palette__item-text">
						<span class="command-palette__item-title">${esc(item.title)}</span>
						<span class="command-palette__item-desc">${esc(item.description)}</span>
					</span>
				</button>
			</li>`
		)
		.join("");
	if (live) {
		live.textContent = t(
			"commandPalette.resultCount",
			"$1 {{PLURAL:$2|result|results}}",
			fmt(currentItems.length),
			currentItems.length
		);
	}
}

/**
 * @param {number} next
 * @returns {void}
 */
function setActiveIndex(next) {
	if (currentItems.length === 0) return;
	activeIndex = (next + currentItems.length) % currentItems.length;
	render();
}

/** @param {CommandItem} item */
function activate(item) {
	closeCommandPalette({ restoreFocus: false });
	navigateTo(item.href);
}

/** @param {{ restoreFocus?: boolean }} [options] */
export function closeCommandPalette(options = {}) {
	const root = palette();
	if (!root || root.classList.contains("hidden")) return;
	root.classList.add("hidden");
	root.setAttribute("aria-hidden", "true");
	$("[aria-controls='command-palette']")?.setAttribute("aria-expanded", "false");
	document.body.style.overflow = "";
	setPageInert(false);
	if (options.restoreFocus === false) return;
	if (lastFocus instanceof HTMLElement) lastFocus.focus();
}

/** @param {string} [seed] */
export function openCommandPalette(seed = "") {
	const root = palette();
	const field = input();
	if (!root || !field) return;
	beforeOpen?.();
	lastFocus = /** @type {HTMLElement | null} */ (document.activeElement);
	root.classList.remove("hidden");
	root.setAttribute("aria-hidden", "false");
	$("[aria-controls='command-palette']")?.setAttribute("aria-expanded", "true");
	document.body.style.overflow = "hidden";
	setPageInert(true);
	field.value = seed;
	activeIndex = 0;
	render();
	field.focus();
	field.select();
}

/** @param {KeyboardEvent} event */
function onPaletteKeydown(event) {
	const root = palette();
	if (!root || root.classList.contains("hidden")) return;
	if (event.key === "Escape") {
		event.preventDefault();
		event.stopPropagation();
		closeCommandPalette();
		return;
	}
	if (event.key === "ArrowDown") {
		event.preventDefault();
		event.stopPropagation();
		setActiveIndex(activeIndex + 1);
		return;
	}
	if (event.key === "ArrowUp") {
		event.preventDefault();
		event.stopPropagation();
		setActiveIndex(activeIndex - 1);
		return;
	}
	if (event.key === "Home") {
		event.preventDefault();
		event.stopPropagation();
		setActiveIndex(0);
		return;
	}
	if (event.key === "End") {
		event.preventDefault();
		event.stopPropagation();
		setActiveIndex(currentItems.length - 1);
		return;
	}
	if (event.key === "Enter" && activeIndex >= 0 && currentItems[activeIndex]) {
		event.preventDefault();
		event.stopPropagation();
		activate(currentItems[activeIndex]);
	}
}

/** @param {KeyboardEvent} event */
function trapTab(event) {
	const root = palette();
	if (!root || root.classList.contains("hidden") || event.key !== "Tab") return;
	const focusable = $$(
		'button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])',
		root
	).filter((el) => el.getAttribute("tabindex") !== "-1" && !el.hidden && el.offsetParent !== null);
	wrapTabFocus(event, focusable);
}

/**
 * @param {{ beforeOpen?: () => void }} [options]
 * @returns {void}
 */
export function initCommandPalette(options = {}) {
	beforeOpen = typeof options.beforeOpen === "function" ? options.beforeOpen : null;
	const trigger = $("[aria-controls='command-palette']");
	const field = input();
	const root = palette();
	if (!root || !field) return;
	syncCommandPaletteChrome();
	trigger?.addEventListener("click", () => openCommandPalette());
	field.addEventListener("input", () => {
		activeIndex = 0;
		render();
	});
	root.addEventListener("keydown", (event) => {
		trapTab(event);
		onPaletteKeydown(event);
	});
	root.addEventListener("click", (event) => {
		if (event.target === root || event.target?.closest("[data-command-close]")) {
			event.preventDefault();
			closeCommandPalette();
			return;
		}
		const item = event.target?.closest("[data-command-index]");
		if (!item) return;
		event.preventDefault();
		const index = Number.parseInt(/** @type {HTMLElement} */ (item).dataset.commandIndex || "", 10);
		if (Number.isInteger(index) && currentItems[index]) activate(currentItems[index]);
	});
	document.addEventListener(
		"keydown",
		(event) => {
			if (!isPaletteShortcut(event)) return;
			event.preventDefault();
			event.stopPropagation();
			openCommandPalette();
		},
		true
	);
	document.addEventListener("toolhub:route-render-start", () => closeCommandPalette({ restoreFocus: false }));
	render();
}
