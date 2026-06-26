// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "vitest";
import { installStorage } from "./_storage-setup.mjs";
import { favBtn, syncFavButtons } from "../../public_html/lib/molecules/favbtn.js";
import { icon } from "../../public_html/lib/atoms/icon.js";

let store;
beforeEach(() => {
	store = installStorage();
});
afterEach(() => {
	store.clear();
	document.body.innerHTML = "";
});

const FAV_KEY = "thdemo:favorites";

// Reading innerHTML re-serializes self-closing tags (<path/> => <path></path>),
// so compare the live node's innerHTML against the same string passed through the
// same serializer rather than the raw icon() output.
const norm = (html) => {
	const d = document.createElement("span");
	d.innerHTML = html;
	return d.innerHTML;
};

test("favBtn() off state (not favorited)", () => {
	assert.equal(
		favBtn("mytool"),
		`<button class="favbtn" type="button" data-fav="mytool" aria-pressed="false" aria-label="Save to favorites"><span class="favbtn__ic" aria-hidden="true">${icon("starOutline")}</span></button>`
	);
});

test("favBtn() off state with label", () => {
	assert.equal(
		favBtn("mytool", { label: true }),
		`<button class="favbtn" type="button" data-fav="mytool" aria-pressed="false" aria-label="Save to favorites"><span class="favbtn__ic" aria-hidden="true">${icon("starOutline")}</span><span class="favbtn__t">Save</span></button>`
	);
});

test("favBtn() off state with extra cls", () => {
	assert.equal(
		favBtn("mytool", { cls: "big" }),
		`<button class="favbtn big" type="button" data-fav="mytool" aria-pressed="false" aria-label="Save to favorites"><span class="favbtn__ic" aria-hidden="true">${icon("starOutline")}</span></button>`
	);
});

test("favBtn() on state (favorited)", () => {
	store.setItem(FAV_KEY, JSON.stringify(["mytool"]));
	assert.equal(
		favBtn("mytool"),
		`<button class="favbtn is-on" type="button" data-fav="mytool" aria-pressed="true" aria-label="Remove from favorites"><span class="favbtn__ic" aria-hidden="true">${icon("star")}</span></button>`
	);
});

test("favBtn() on state with label", () => {
	store.setItem(FAV_KEY, JSON.stringify(["mytool"]));
	assert.equal(
		favBtn("mytool", { label: true }),
		`<button class="favbtn is-on" type="button" data-fav="mytool" aria-pressed="true" aria-label="Remove from favorites"><span class="favbtn__ic" aria-hidden="true">${icon("star")}</span><span class="favbtn__t">Saved</span></button>`
	);
});

test("favBtn() escapes the tool name in data-fav", () => {
	assert.match(favBtn('a"b'), /data-fav="a&quot;b"/);
});

// ---- syncFavButtons -----------------------------------------------------------
test("syncFavButtons() turns matching buttons on", () => {
	document.body.innerHTML =
		'<button data-fav="a" aria-pressed="false" aria-label="Save to favorites"><span class="favbtn__ic"></span><span class="favbtn__t"></span></button>' +
		'<button data-fav="b" aria-pressed="false" aria-label="Save to favorites"></button>';
	syncFavButtons("a", true);
	const a = document.querySelector('[data-fav="a"]');
	const b = document.querySelector('[data-fav="b"]');
	assert.equal(a.classList.contains("is-on"), true);
	assert.equal(a.getAttribute("aria-pressed"), "true");
	assert.equal(a.getAttribute("aria-label"), "Remove from favorites");
	assert.equal(a.querySelector(".favbtn__ic").innerHTML, norm(icon("star")));
	assert.equal(a.querySelector(".favbtn__t").textContent, "Saved");
	// non-matching button untouched
	assert.equal(b.classList.contains("is-on"), false);
	assert.equal(b.getAttribute("aria-pressed"), "false");
	assert.equal(b.getAttribute("aria-label"), "Save to favorites");
});

test("syncFavButtons() turns matching buttons off", () => {
	document.body.innerHTML =
		'<button data-fav="a" class="is-on" aria-pressed="true" aria-label="Remove from favorites"><span class="favbtn__ic"></span><span class="favbtn__t"></span></button>';
	syncFavButtons("a", false);
	const a = document.querySelector('[data-fav="a"]');
	assert.equal(a.classList.contains("is-on"), false);
	assert.equal(a.getAttribute("aria-pressed"), "false");
	assert.equal(a.getAttribute("aria-label"), "Save to favorites");
	assert.equal(a.querySelector(".favbtn__ic").innerHTML, norm(icon("starOutline")));
	assert.equal(a.querySelector(".favbtn__t").textContent, "Save");
});

test("syncFavButtons() does not throw when ic/t children are absent", () => {
	document.body.innerHTML = '<button data-fav="a" aria-pressed="false" aria-label="Save to favorites"></button>';
	syncFavButtons("a", true);
	const a = document.querySelector('[data-fav="a"]');
	assert.equal(a.getAttribute("aria-pressed"), "true");
	assert.equal(a.getAttribute("aria-label"), "Remove from favorites");
	assert.equal(a.classList.contains("is-on"), true);
});
