// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { beforeEach, expect, test, vi } from "vitest";

// Partial-mock the api layer: keep the real INDEX (and every other export the
// badge/markdown helpers rely on) but make getTool controllable so we can drive
// openQuickView's INDEX-miss / fetched / not-found branches deterministically.
vi.mock("../../public_html/lib/core/api.js", async (importActual) => {
	const actual = /** @type {Record<string, unknown>} */ (await importActual());
	return { ...actual, getTool: vi.fn() };
});

import {
	QV_TAG_LIMIT,
	closeQuickView,
	openQuickView,
	qvLastFocus,
	qvTrap,
	quickViewBody,
	setPageInert
} from "../../public_html/lib/organisms/quickview.js";
import { INDEX, getTool } from "../../public_html/lib/core/api.js";
import { dirAttrs, esc, safeUrl } from "../../public_html/lib/core/dom.js";
import { updatedTimeTag } from "../../public_html/lib/core/i18n.js";
import { renderMarkdown } from "../../public_html/lib/core/markdown.js";
import { applyExp, setAuth, signedIn } from "../../public_html/lib/core/session.js";
import { toolHref } from "../../public_html/lib/core/routing.js";
import { toolIcon } from "../../public_html/lib/atoms/avatar.js";
import { endorsementChip, fitChip, healthBadge, popularityBadge } from "../../public_html/lib/atoms/badges.js";
import { button } from "../../public_html/lib/atoms/button.js";
import { glanceChips, keywordTags } from "../../public_html/lib/atoms/labels.js";
import { favBtn } from "../../public_html/lib/molecules/favbtn.js";

const TAG_LIMIT = 6; // hardcoded copy of QV_TAG_LIMIT

/** @param {any} t */
function qvOracle(t) {
	const authors = (t.authors || []).map((author) => esc(author)).join(", ") || esc(t.maintainer);
	const tags = keywordTags(t, { limit: TAG_LIMIT });
	const endorsement = t.endorsement;
	const realBadge = [
		t.deprecated && '<span class="status status--red"><span class="dot dot--red"></span>Deprecated</span>',
		t.experimental && '<span class="status status--yellow"><span class="dot dot--yellow"></span>Experimental</span>'
	]
		.filter(Boolean)
		.join("");
	const glance = glanceChips(t);
	return `\n\t\t<div class="qv__head">${toolIcon(t, "lg")}\n\t\t\t<div class="qv__id"><h2 class="qv__title" id="qv-title"${dirAttrs(t.title)}>${esc(t.title)}</h2>\n\t\t\t<div class="qv__by">by <span dir="auto">${authors}</span></div></div>\n\t\t</div>\n\t\t<div class="qv__status">\n\t\t\t${realBadge}\n\t\t\t${endorsementChip(endorsement && endorsement.count)}\n\t\t\t${fitChip(t)}\n\t\t\t<!-- EXPERIMENTAL — operational health. Needs: an uptime/health-check service. -->\n\t\t\t${healthBadge(t)}\n\t\t\t<!-- EXPERIMENTAL — popularity. Needs: usage/view tracking. -->\n\t\t\t${popularityBadge(t)}\n\t\t\t${updatedTimeTag(t.modified, "toolpage__when")}\n\t\t</div>\n\t\t<div class="qv__desc"${dirAttrs(t.description)}>${renderMarkdown(t.description) || "<em>No description provided.</em>"}</div>\n\t\t<div class="toolpage__glance">${glance}</div>\n\t\t<div class="tcard__tags qv__tags">${tags}</div>\n\t\t<div class="qv__actions">\n\t\t\t${t.url ? button("Open tool", { variant: "primary", href: safeUrl(t.url), icon: "external", attrs: 'target="_blank" rel="noopener nofollow"' }) : ""}\n\t\t\t${button("View full page", { variant: "outline", href: toolHref(t.name) })}\n\t\t\t${signedIn() ? favBtn(t.name, { label: true, cls: "favbtn--btn" }) : ""}\n\t\t</div>`;
}

const base = {
	name: "my tool",
	title: "My <Tool>",
	maintainer: "Jane & Co",
	description: "A long enough description to render as markdown body.",
	keywords: ["a", "b"],
	toolType: "web app",
	forWikis: "*",
	modified: "2026-06-01T00:00:00Z",
	authors: ["Ann", "Bob"],
	url: "https://example.org/tool"
};

function qvCheck(label, t) {
	assert.equal(quickViewBody(t), qvOracle(t), label);
}

beforeEach(() => {
	document.body.innerHTML = "";
	applyExp(true);
	setAuth(true);
	for (const k of Object.keys(INDEX)) delete INDEX[k];
	getTool.mockReset();
});

test("quickViewBody exact HTML across content branches", () => {
	qvCheck("authors + url + signed in", base);
	qvCheck("no authors -> maintainer fallback", { ...base, authors: [] });
	qvCheck("missing authors (|| [])", { ...base, authors: undefined });
	qvCheck("deprecated badge", { ...base, deprecated: true });
	qvCheck("experimental badge", { ...base, experimental: true });
	qvCheck("both badges", { ...base, deprecated: true, experimental: true });
	qvCheck("endorsement attached", { ...base, endorsement: { count: 7 } });
	qvCheck("empty description -> fallback em", { ...base, description: "" });
	qvCheck("no url -> no Open tool button", { ...base, url: "" });
	// >6 keywords pins the { limit: QV_TAG_LIMIT } object (dropping it shows all keywords).
	qvCheck("many keywords are capped at the tag limit", {
		...base,
		keywords: ["k1", "k2", "k3", "k4", "k5", "k6", "k7", "k8"]
	});
	// Explicit false flags pin the .filter(Boolean) (its removal would join "falsefalse").
	qvCheck("explicitly non-flagged tool", { ...base, deprecated: false, experimental: false });
});

test("quickViewBody omits favBtn when signed out", () => {
	setAuth(false);
	qvCheck("signed out", base);
});

test("QV_TAG_LIMIT export value", () => {
	assert.equal(QV_TAG_LIMIT, 6);
});

/* ---- setPageInert ------------------------------------------------------- */
test("setPageInert toggles aria-hidden on siblings, skipping #qv and scripts", () => {
	document.body.innerHTML = `<div id="qv"></div><script id="s"></script><div class="other"></div><section class="o2"></section>`;
	const qv = /** @type {HTMLElement} */ (document.querySelector("#qv"));
	const script = /** @type {HTMLElement} */ (document.querySelector("#s"));
	const other = /** @type {HTMLElement} */ (document.querySelector(".other"));
	const o2 = /** @type {HTMLElement} */ (document.querySelector(".o2"));
	setPageInert(true);
	assert.equal(other.getAttribute("aria-hidden"), "true");
	assert.equal(o2.getAttribute("aria-hidden"), "true");
	assert.equal(qv.hasAttribute("aria-hidden"), false);
	assert.equal(script.hasAttribute("aria-hidden"), false);
	if ("inert" in other) assert.equal(other.inert, true);
	setPageInert(false);
	assert.equal(other.hasAttribute("aria-hidden"), false);
	assert.equal(o2.hasAttribute("aria-hidden"), false);
	if ("inert" in other) assert.equal(other.inert, false);
});

/* ---- openQuickView ------------------------------------------------------ */
function qvFixture() {
	document.body.innerHTML = `
		<main class="page"><button id="opener">x</button></main>
		<div id="qv" class="hidden" aria-hidden="true"><button class="qv__x">close</button><div id="qv-body"></div></div>`;
}

test("openQuickView renders an INDEX-cached tool and opens the modal", async () => {
	qvFixture();
	const opener = /** @type {HTMLElement} */ (document.querySelector("#opener"));
	opener.focus();
	INDEX[base.name] = base;
	await openQuickView(base.name);
	const qv = /** @type {HTMLElement} */ (document.querySelector("#qv"));
	const body = /** @type {HTMLElement} */ (document.querySelector("#qv-body"));
	assert.equal(qv.classList.contains("hidden"), false);
	assert.equal(qv.getAttribute("aria-hidden"), "false");
	assert.equal(document.body.style.overflow, "hidden");
	const ref = document.createElement("div");
	ref.innerHTML = quickViewBody(base);
	assert.equal(body.innerHTML, ref.innerHTML);
	// Focus moved to the close button; last focus remembered.
	assert.equal(document.activeElement, document.querySelector(".qv__x"));
	assert.equal(qvLastFocus, opener);
	// Page behind the modal was made inert.
	assert.equal(/** @type {HTMLElement} */ (document.querySelector(".page")).getAttribute("aria-hidden"), "true");
	// getTool not consulted because the tool was cached.
	expect(getTool).not.toHaveBeenCalled();
});

test("openQuickView fetches when the tool is not cached", async () => {
	qvFixture();
	getTool.mockResolvedValue(base);
	await openQuickView(base.name);
	const body = /** @type {HTMLElement} */ (document.querySelector("#qv-body"));
	const ref = document.createElement("div");
	ref.innerHTML = quickViewBody(base);
	assert.equal(body.innerHTML, ref.innerHTML);
	expect(getTool).toHaveBeenCalledWith(base.name);
});

test("openQuickView navigates to the full page when the tool is not found", async () => {
	history.pushState({}, "", "/");
	qvFixture();
	getTool.mockResolvedValue(null);
	await openQuickView("ghost");
	const qv = /** @type {HTMLElement} */ (document.querySelector("#qv"));
	// Modal stays closed; we navigated instead.
	assert.equal(qv.classList.contains("hidden"), true);
	assert.equal(location.pathname, toolHref("ghost"));
	const body = /** @type {HTMLElement} */ (document.querySelector("#qv-body"));
	assert.equal(body.innerHTML, "");
});

test("openQuickView tolerates a missing modal/body", async () => {
	document.body.innerHTML = `<main></main>`;
	INDEX[base.name] = base;
	await assert.doesNotThrow(async () => openQuickView(base.name));
	assert.equal(document.body.style.overflow, "hidden");
});

/* ---- closeQuickView ----------------------------------------------------- */
test("closeQuickView hides the modal, restores scroll and focus", async () => {
	qvFixture();
	const opener = /** @type {HTMLElement} */ (document.querySelector("#opener"));
	opener.focus();
	INDEX[base.name] = base;
	await openQuickView(base.name);
	closeQuickView();
	const qv = /** @type {HTMLElement} */ (document.querySelector("#qv"));
	assert.equal(qv.classList.contains("hidden"), true);
	assert.equal(qv.getAttribute("aria-hidden"), "true");
	assert.equal(document.body.style.overflow, "");
	assert.equal(document.activeElement, opener);
	assert.equal(/** @type {HTMLElement} */ (document.querySelector(".page")).hasAttribute("aria-hidden"), false);
});

test("closeQuickView is a no-op when already hidden", () => {
	document.body.innerHTML = `<div id="qv" class="hidden"></div>`;
	document.body.style.overflow = "sentinel";
	closeQuickView();
	assert.equal(document.body.style.overflow, "sentinel");
});

test("closeQuickView is a no-op when the modal is absent", () => {
	document.body.innerHTML = "";
	document.body.style.overflow = "sentinel";
	assert.doesNotThrow(() => closeQuickView());
	assert.equal(document.body.style.overflow, "sentinel");
});

/* ---- qvTrap (focus trap) ------------------------------------------------ */
// happy-dom's real offsetParent getter is unusable here (it can hang), so we
// stub offsetParent on every element the filter inspects: non-null where the
// element should count as visible, null where it should be filtered out.
function offsetParent(el, value) {
	Object.defineProperty(el, "offsetParent", { configurable: true, get: () => value });
	return /** @type {HTMLElement} */ (el);
}
function visible(el) {
	return offsetParent(el, document.body);
}
function laidOut(el) {
	return offsetParent(el, null);
}

function trapFixture() {
	document.body.innerHTML = `
		<div id="qv">
			<button id="hiddenTop" hidden>h</button>
			<button id="f1">a</button>
			<button id="f2">b</button>
			<button id="fLast">c</button>
			<button id="nullBottom">n</button>
		</div>
		<button id="outside">out</button>`;
	const get = (id) => /** @type {HTMLElement} */ (document.querySelector(`#${id}`));
	visible(get("hiddenTop")); // visible-but-hidden -> excluded by !el.hidden
	const f1 = visible(get("f1"));
	const f2 = visible(get("f2"));
	const fLast = visible(get("fLast"));
	laidOut(get("nullBottom")); // offsetParent null -> excluded by offsetParent !== null
	const outside = visible(get("outside")); // outside #qv -> only seen if the root arg is dropped
	return { f1, f2, fLast, outside };
}

test("qvTrap wraps focus from last to first on Tab", () => {
	const { f1, fLast } = trapFixture();
	fLast.focus();
	const e = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true });
	qvTrap(e);
	assert.equal(document.activeElement, f1);
	assert.equal(e.defaultPrevented, true);
});

test("qvTrap wraps focus from first to last on Shift+Tab", () => {
	const { f1, fLast } = trapFixture();
	f1.focus();
	const e = new KeyboardEvent("keydown", { key: "Tab", shiftKey: true, bubbles: true, cancelable: true });
	qvTrap(e);
	assert.equal(document.activeElement, fLast);
	assert.equal(e.defaultPrevented, true);
});

test("qvTrap scopes focusables to the modal (ignores elements outside #qv)", () => {
	// If the qv root arg were dropped, #outside would become the last focusable
	// and Tab on fLast would no longer wrap.
	const { f1, fLast, outside } = trapFixture();
	fLast.focus();
	const e = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true });
	qvTrap(e);
	assert.equal(document.activeElement, f1);
	assert.notEqual(document.activeElement, outside);
});

test("qvTrap ignores hidden and zero-layout elements at the boundaries", () => {
	// hiddenTop (hidden) and nullBottom (offsetParent null) must not become the
	// first/last focusable, otherwise these wraps would break.
	const { f1, fLast } = trapFixture();
	f1.focus();
	const shift = new KeyboardEvent("keydown", { key: "Tab", shiftKey: true, cancelable: true });
	qvTrap(shift);
	assert.equal(document.activeElement, fLast, "first is f1, not hiddenTop");
	fLast.focus();
	const tab = new KeyboardEvent("keydown", { key: "Tab", cancelable: true });
	qvTrap(tab);
	assert.equal(document.activeElement, f1, "last is fLast, not nullBottom");
});

test("qvTrap does nothing mid-list (Tab or Shift+Tab)", () => {
	const { f1, f2, fLast } = trapFixture();
	f2.focus();
	const tab = new KeyboardEvent("keydown", { key: "Tab", cancelable: true });
	qvTrap(tab);
	assert.equal(document.activeElement, f2);
	assert.equal(tab.defaultPrevented, false);
	// Shift+Tab mid-list must also be inert (pins the && and the === first check).
	const shift = new KeyboardEvent("keydown", { key: "Tab", shiftKey: true, cancelable: true });
	qvTrap(shift);
	assert.equal(document.activeElement, f2);
	assert.equal(shift.defaultPrevented, false);
	assert.notEqual(document.activeElement, f1);
	assert.notEqual(document.activeElement, fLast);
});

test("qvTrap ignores non-Tab keys", () => {
	const { fLast } = trapFixture();
	fLast.focus();
	const e = new KeyboardEvent("keydown", { key: "Enter", cancelable: true });
	qvTrap(e);
	assert.equal(document.activeElement, fLast);
	assert.equal(e.defaultPrevented, false);
});

test("qvTrap ignores Tab when the modal is hidden", () => {
	const { fLast } = trapFixture();
	/** @type {HTMLElement} */ (document.querySelector("#qv")).classList.add("hidden");
	fLast.focus();
	const e = new KeyboardEvent("keydown", { key: "Tab", cancelable: true });
	qvTrap(e);
	assert.equal(e.defaultPrevented, false);
});

test("qvTrap no-ops when there is no modal", () => {
	document.body.innerHTML = "";
	const e = new KeyboardEvent("keydown", { key: "Tab", cancelable: true });
	assert.doesNotThrow(() => qvTrap(e));
});

test("qvTrap no-ops when the modal has no focusable elements", () => {
	document.body.innerHTML = `<div id="qv"><span>no focusables</span></div>`;
	const e = new KeyboardEvent("keydown", { key: "Tab", cancelable: true });
	qvTrap(e);
	assert.equal(e.defaultPrevented, false);
});
