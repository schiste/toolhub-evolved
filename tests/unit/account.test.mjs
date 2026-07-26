// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { beforeEach, test, vi } from "vitest";
import {
	closeAcctMenu,
	renderAccount,
	syncSubmitButton,
	toggleAcctMenu
} from "../../public_html/lib/organisms/account.js";
import { esc } from "../../public_html/lib/core/dom.js";
import { USER, applyExp, setAuth, setServerUser } from "../../public_html/lib/core/session.js";
import { avatar } from "../../public_html/lib/atoms/avatar.js";
import { button } from "../../public_html/lib/atoms/button.js";
import { icon } from "../../public_html/lib/atoms/icon.js";

// The account UI asks serversync whether real (OAuth) sign-in is configured;
// stub it with a switchable flag so both renders are testable.
let oauthOn = false;
vi.mock("../../public_html/lib/core/serversync.js", () => ({ oauthAvailable: () => oauthOn }));

function htmlEqual(actual, expected, msg) {
	const a = document.createElement("div");
	const b = document.createElement("div");
	a.innerHTML = actual;
	b.innerHTML = expected;
	assert.equal(a.innerHTML, b.innerHTML, msg);
}

function menuOracle(real = false) {
	const tag = real ? "" : '<span class="mock-tag">demo</span>';
	const actions = real
		? `<a class="acct__logout" href="/oauth/logout">${icon("logout")} Log out</a>`
		: `<button class="acct__reset" type="button" data-reset>${icon("reset")} Reset demo data</button><button class="acct__logout" type="button" data-logout>${icon("logout")} Log out</button>`;
	return `\n\t\t<button class="acct__btn" id="acct-btn" type="button" aria-haspopup="true" aria-expanded="false" aria-controls="acct-menu">\n\t\t\t${avatar(USER.name, "avatar--sm")}\n\t\t\t<span class="acct__name">${esc(USER.name)}</span>\n\t\t\t${icon("chevronDown", "acct__caret")}\n\t\t</button>\n\t\t<div class="acct__menu" id="acct-menu" aria-labelledby="acct-btn" hidden>\n\t\t\t<div class="acct__head">Signed in as <strong>${esc(USER.name)}</strong> ${tag}</div>\n\t\t\t<a href="/my-lists">${icon("list")} Your lists</a>\n\t\t\t<a href="/favorites">${icon("star")} Favorites</a>\n\t\t\t<a href="/add-or-remove-tools">${icon("tools")} Add or remove tools</a>\n\t\t\t<hr />\n\t\t\t${actions}\n\t\t</div>`;
}

beforeEach(() => {
	document.body.innerHTML = "";
	oauthOn = false;
	setServerUser(null);
	USER.name = "Ada Lovelace";
	applyExp(true);
	setAuth(true);
});

test("renderAccount no-ops when #account is absent", () => {
	applyExp(true);
	setAuth(true);
	renderAccount();
	assert.equal(document.body.innerHTML, "");
});

test("renderAccount shows Log in when experiments are off", () => {
	applyExp(false);
	document.body.innerHTML = `<div id="account"></div>`;
	renderAccount();
	const el = /** @type {HTMLElement} */ (document.querySelector("#account"));
	htmlEqual(el.innerHTML, button("Log in", { variant: "outline", href: "/login" }));
});

test("renderAccount shows Sign in demo when exp on but signed out", () => {
	applyExp(true);
	setAuth(false);
	document.body.innerHTML = `<div id="account"></div>`;
	renderAccount();
	const el = /** @type {HTMLElement} */ (document.querySelector("#account"));
	htmlEqual(el.innerHTML, button("Sign in demo", { variant: "outline", attrs: "data-login" }));
});

test("renderAccount shows the account menu when signed in", () => {
	applyExp(true);
	setAuth(true);
	document.body.innerHTML = `<div id="account"></div>`;
	renderAccount();
	const el = /** @type {HTMLElement} */ (document.querySelector("#account"));
	htmlEqual(el.innerHTML, menuOracle());
	assert.ok(el.querySelector("#acct-btn"));
	assert.equal(/** @type {HTMLElement} */ (el.querySelector("#acct-menu")).hidden, true);
});

test("renderAccount offers the real sign-in when OAuth is configured (exp off)", () => {
	oauthOn = true;
	applyExp(false);
	document.body.innerHTML = `<div id="account"></div>`;
	renderAccount();
	const el = /** @type {HTMLElement} */ (document.querySelector("#account"));
	htmlEqual(el.innerHTML, button("Log in", { variant: "outline", href: "/oauth/login" }));
});

test("renderAccount offers Toolhub sign-in ahead of the demo one when configured", () => {
	oauthOn = true;
	applyExp(true);
	setAuth(false);
	document.body.innerHTML = `<div id="account"></div>`;
	renderAccount();
	const el = /** @type {HTMLElement} */ (document.querySelector("#account"));
	htmlEqual(
		el.innerHTML,
		`${button("Sign in with Toolhub", { href: "/oauth/login" })}${button("Sign in demo", { variant: "outline", attrs: "data-login" })}`
	);
});

test("renderAccount renders a real session: no demo tag, no reset, server logout", () => {
	setServerUser("Grace Hopper");
	document.body.innerHTML = `<div id="account"></div>`;
	renderAccount();
	const el = /** @type {HTMLElement} */ (document.querySelector("#account"));
	htmlEqual(el.innerHTML, menuOracle(true));
	assert.equal(el.querySelector(".mock-tag"), null);
	assert.equal(el.querySelector("[data-reset]"), null);
	assert.ok(el.querySelector('a[href="/oauth/logout"]'));
	assert.ok(el.textContent.includes("Grace Hopper"));
});

function acctFixture() {
	document.body.innerHTML = `
		<button id="acct-btn" aria-expanded="false"></button>
		<div id="acct-menu" hidden>
			<a id="firstlink" href="/my-lists">Your lists</a>
			<button>Log out</button>
		</div>`;
}

test("closeAcctMenu hides menu and resets aria-expanded", () => {
	acctFixture();
	const m = /** @type {HTMLElement} */ (document.querySelector("#acct-menu"));
	const b = /** @type {HTMLElement} */ (document.querySelector("#acct-btn"));
	m.hidden = false;
	b.setAttribute("aria-expanded", "true");
	closeAcctMenu();
	assert.equal(m.hidden, true);
	assert.equal(b.getAttribute("aria-expanded"), "false");
});

test("closeAcctMenu tolerates missing elements", () => {
	document.body.innerHTML = "";
	assert.doesNotThrow(() => closeAcctMenu());
});

test("toggleAcctMenu opens a hidden menu and focuses the first item", () => {
	acctFixture();
	const m = /** @type {HTMLElement} */ (document.querySelector("#acct-menu"));
	const b = /** @type {HTMLElement} */ (document.querySelector("#acct-btn"));
	const first = /** @type {HTMLElement} */ (document.querySelector("#firstlink"));
	toggleAcctMenu();
	assert.equal(m.hidden, false);
	assert.equal(b.getAttribute("aria-expanded"), "true");
	assert.equal(document.activeElement, first);
});

test("toggleAcctMenu closes an open menu without moving focus", () => {
	acctFixture();
	const m = /** @type {HTMLElement} */ (document.querySelector("#acct-menu"));
	const b = /** @type {HTMLElement} */ (document.querySelector("#acct-btn"));
	m.hidden = false;
	b.setAttribute("aria-expanded", "true");
	document.body.focus();
	const before = document.activeElement;
	toggleAcctMenu();
	assert.equal(m.hidden, true);
	assert.equal(b.getAttribute("aria-expanded"), "false");
	assert.equal(document.activeElement, before);
});

test("toggleAcctMenu no-ops without a menu", () => {
	document.body.innerHTML = `<button id="acct-btn"></button>`;
	assert.doesNotThrow(() => toggleAcctMenu());
});

test("toggleAcctMenu opens even when the button is missing", () => {
	// Exercises the `if (b)` guard with b absent: a mutant forcing it true would
	// call setAttribute on null and throw.
	document.body.innerHTML = `<div id="acct-menu" hidden><a href="/x">x</a></div>`;
	const m = /** @type {HTMLElement} */ (document.querySelector("#acct-menu"));
	const first = /** @type {HTMLElement} */ (document.querySelector("a"));
	assert.doesNotThrow(() => toggleAcctMenu());
	assert.equal(m.hidden, false);
	assert.equal(document.activeElement, first);
});

test("toggleAcctMenu opens an empty menu without focusing anything", () => {
	// Exercises the `if (first)` guard with no focusable child: a mutant forcing
	// it true would call focus on null and throw.
	document.body.innerHTML = `
		<button id="acct-btn" aria-expanded="false"></button>
		<div id="acct-menu" hidden><span>nothing focusable</span></div>`;
	const m = /** @type {HTMLElement} */ (document.querySelector("#acct-menu"));
	const b = /** @type {HTMLElement} */ (document.querySelector("#acct-btn"));
	document.body.focus();
	const before = document.activeElement;
	assert.doesNotThrow(() => toggleAcctMenu());
	assert.equal(m.hidden, false);
	assert.equal(b.getAttribute("aria-expanded"), "true");
	assert.equal(document.activeElement, before);
});

test("syncSubmitButton uses the in-app create form when experimenting", () => {
	applyExp(true);
	document.body.innerHTML = `<a id="submit-tool" href="#" target="_blank" rel="noopener nofollow"></a>`;
	const b = /** @type {HTMLElement} */ (document.querySelector("#submit-tool"));
	syncSubmitButton();
	assert.equal(b.getAttribute("href"), "/tools/create");
	assert.equal(b.hasAttribute("target"), false);
	assert.equal(b.hasAttribute("rel"), false);
});

test("syncSubmitButton uses the production link when not experimenting", () => {
	applyExp(false);
	document.body.innerHTML = `<a id="submit-tool" href="#"></a>`;
	const b = /** @type {HTMLElement} */ (document.querySelector("#submit-tool"));
	syncSubmitButton();
	assert.equal(b.getAttribute("href"), "https://toolhub.wikimedia.org/add-or-remove-tools?tab=tool-create");
	assert.equal(b.getAttribute("target"), "_blank");
	assert.equal(b.getAttribute("rel"), "noopener nofollow");
});

test("syncSubmitButton no-ops when the button is absent", () => {
	document.body.innerHTML = "";
	assert.doesNotThrow(() => syncSubmitButton());
});
