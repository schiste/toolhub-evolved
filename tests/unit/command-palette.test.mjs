// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { beforeEach, test, vi } from "vitest";
import * as routing from "../../public_html/lib/core/routing.js";
import {
	closeCommandPalette,
	commandItems,
	initCommandPalette,
	isEditableTarget,
	isPaletteShortcut,
	openCommandPalette,
	shortcutLabel,
	syncCommandPaletteChrome
} from "../../public_html/lib/organisms/command-palette.js";

vi.mock("../../public_html/lib/core/routing.js", async (importOriginal) => ({
	...(await importOriginal()),
	navigateTo: vi.fn()
}));

const SHELL = `
	<button id="outside" type="button">Outside</button>
	<button id="command-palette-trigger" type="button" aria-controls="command-palette" aria-expanded="false">
		<span class="command-trigger__label">Search</span> <kbd data-command-shortcut></kbd>
	</button>
	<main id="view"><a href="/search">Search</a></main>
	<div class="command-palette hidden" id="command-palette" aria-hidden="true">
		<div class="command-palette__box" role="dialog" aria-modal="true" aria-labelledby="command-title" aria-describedby="command-help">
			<button type="button" data-command-close aria-label="Close command palette">Close</button>
			<h2 id="command-title">Search Toolhub</h2>
			<p id="command-help">Type a tool name or action, then use arrow keys and Enter.</p>
			<label for="command-input">Search tools and actions</label>
			<input id="command-input" role="combobox" aria-controls="command-list" aria-activedescendant="" />
			<div id="command-status" aria-live="polite"></div>
			<ul id="command-list" role="listbox"></ul>
		</div>
	</div>`;

const $ = (selector) => document.querySelector(selector);
const key = (target, keyName, init = {}) => {
	const event = new KeyboardEvent("keydown", { bubbles: true, cancelable: true, key: keyName, ...init });
	target.dispatchEvent(event);
	return event;
};
const click = (target) => {
	const event = new MouseEvent("click", { bubbles: true, cancelable: true });
	target.dispatchEvent(event);
	return event;
};
const visible = (el) => {
	Object.defineProperty(el, "offsetParent", { value: document.body, configurable: true });
	return el;
};

beforeEach(() => {
	document.body.innerHTML = SHELL;
	document.body.style.overflow = "";
	vi.clearAllMocks();
});

test("shortcutLabel uses Mac and Windows/Linux conventions", () => {
	assert.equal(shortcutLabel("MacIntel"), "⌘ K");
	assert.equal(shortcutLabel("iPad"), "⌘ K");
	assert.equal(shortcutLabel("Win32"), "Ctrl K");
	assert.equal(shortcutLabel("Linux x86_64"), "Ctrl K");
});

test("syncCommandPaletteChrome updates the platform shortcut and trigger name", () => {
	syncCommandPaletteChrome();
	assert.equal($(".command-trigger__label").textContent, "Search");
	assert.match($("#command-palette-trigger").getAttribute("aria-label"), /Search tools and actions/);
	assert.ok($("[data-command-shortcut]").textContent.trim().length > 0);
});

test("editable targets are protected from global shortcuts", () => {
	document.body.insertAdjacentHTML(
		"beforeend",
		`<input id="i"><textarea id="ta"></textarea><select id="sel"></select><div id="ce" contenteditable="true"><span id="ce-child">x</span></div><div role="textbox"><span id="role-child">x</span></div>`
	);
	assert.equal(isEditableTarget($("#i")), true);
	assert.equal(isEditableTarget($("#ta")), true);
	assert.equal(isEditableTarget($("#sel")), true);
	assert.equal(isEditableTarget($("#ce-child")), true);
	assert.equal(isEditableTarget($("#role-child")), true);
	assert.equal(isEditableTarget($("#outside")), false);
});

test("shortcut detection accepts cross-OS keys and ignores editable fields", () => {
	const ctrl = new KeyboardEvent("keydown", { key: "k", ctrlKey: true, bubbles: true, cancelable: true });
	Object.defineProperty(ctrl, "target", { value: $("#outside"), configurable: true });
	assert.equal(isPaletteShortcut(ctrl), true);
	const meta = new KeyboardEvent("keydown", { key: "K", metaKey: true, bubbles: true, cancelable: true });
	Object.defineProperty(meta, "target", { value: $("#outside"), configurable: true });
	assert.equal(isPaletteShortcut(meta), true);
	const slash = new KeyboardEvent("keydown", { key: "/", bubbles: true, cancelable: true });
	Object.defineProperty(slash, "target", { value: $("#outside"), configurable: true });
	assert.equal(isPaletteShortcut(slash), true);
	const editable = new KeyboardEvent("keydown", { key: "/", bubbles: true, cancelable: true });
	Object.defineProperty(editable, "target", { value: document.createElement("input"), configurable: true });
	assert.equal(isPaletteShortcut(editable), false);
	const shifted = new KeyboardEvent("keydown", { key: "k", ctrlKey: true, shiftKey: true, bubbles: true });
	Object.defineProperty(shifted, "target", { value: $("#outside"), configurable: true });
	assert.equal(isPaletteShortcut(shifted), false);
});

test("commandItems prepends a search action and filters route actions", () => {
	const search = commandItems("wiki bots");
	assert.equal(search[0].href, "/search?q=wiki%20bots");
	assert.match(search[0].title, /wiki bots/);
	const api = commandItems("api");
	assert.equal(
		api.some((item) => item.href === "/api-docs"),
		true
	);
	assert.ok(api.some((item) => item.title === "API explorer"));
	assert.ok(commandItems("curl").some((item) => item.href === "/api-docs"));
	assert.equal(
		api.some((item) => item.href === "/favorites"),
		false
	);
});

test("initCommandPalette wires the visible trigger and opens with focus", () => {
	initCommandPalette();
	click($("#command-palette-trigger"));
	assert.equal($("#command-palette").classList.contains("hidden"), false);
	assert.equal($("#command-palette").getAttribute("aria-hidden"), "false");
	assert.equal($("#command-palette-trigger").getAttribute("aria-expanded"), "true");
	assert.equal(document.activeElement, $("#command-input"));
	assert.ok($("[data-command-shortcut]").textContent.trim().length > 0);
	assert.ok($("#command-list").textContent.includes("Browse tools"));
});

test("global shortcuts open the palette and do not fire inside editable fields", () => {
	initCommandPalette();
	const event = key(document.body, "k", { ctrlKey: true });
	assert.equal(event.defaultPrevented, true);
	assert.equal($("#command-palette").classList.contains("hidden"), false);

	closeCommandPalette();
	const input = document.createElement("input");
	document.body.append(input);
	input.focus();
	const ignored = key(input, "/");
	assert.equal(ignored.defaultPrevented, false);
	assert.equal($("#command-palette").classList.contains("hidden"), true);
});

test("typing and Enter navigate to full search results", () => {
	initCommandPalette();
	openCommandPalette();
	const input = $("#command-input");
	input.value = "global replace";
	input.dispatchEvent(new InputEvent("input", { bubbles: true }));
	assert.equal(input.getAttribute("aria-activedescendant"), "command-option-0");
	key(input, "Enter");
	assert.deepEqual(routing.navigateTo.mock.calls[0], ["/search?q=global%20replace"]);
	assert.equal($("#command-palette").classList.contains("hidden"), true);
});

test("arrow keys move the active option before activation", () => {
	initCommandPalette();
	openCommandPalette();
	const input = $("#command-input");
	input.value = "api";
	input.dispatchEvent(new InputEvent("input", { bubbles: true }));
	key(input, "ArrowDown");
	assert.equal(input.getAttribute("aria-activedescendant"), "command-option-1");
	key(input, "Enter");
	assert.deepEqual(routing.navigateTo.mock.calls[0], ["/api-docs"]);
});

test("Escape and close button hide the palette and restore focus", () => {
	initCommandPalette();
	const opener = $("#outside");
	opener.focus();
	openCommandPalette();
	key($("#command-input"), "Escape");
	assert.equal($("#command-palette").classList.contains("hidden"), true);
	assert.equal(document.activeElement, opener);

	openCommandPalette();
	click($("[data-command-close]"));
	assert.equal($("#command-palette").classList.contains("hidden"), true);
});

test("Tab stays inside the dialog and ignores non-tab option buttons", () => {
	initCommandPalette();
	openCommandPalette();
	visible($("#command-input"));
	visible($("[data-command-close]"));
	const option = $("[data-command-index]");
	visible(option);
	$("#command-input").focus();
	const event = key($("#command-input"), "Tab");
	assert.equal(event.defaultPrevented, true);
	assert.equal(document.activeElement, $("[data-command-close]"));
});
