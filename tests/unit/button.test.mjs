// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test } from "vitest";
import { button, iconButton } from "../../public_html/lib/atoms/button.js";
import { icon } from "../../public_html/lib/atoms/icon.js";

// ---- button() -----------------------------------------------------------------
test("button() default: outline variant, md size, button tag", () => {
	assert.equal(button("Hi"), '<button class="btn btn--outline btn--md" type="button">Hi</button>');
});

test("button() primary variant + lg size", () => {
	assert.equal(
		button("Go", { variant: "primary", size: "lg" }),
		'<button class="btn btn--primary btn--lg" type="button">Go</button>'
	);
});

test("button() danger variant + sm size + extra cls", () => {
	assert.equal(
		button("X", { variant: "danger", size: "sm", cls: "my" }),
		'<button class="btn btn--danger btn--sm my" type="button">X</button>'
	);
});

test("button() subtle variant", () => {
	assert.equal(
		button("S", { variant: "subtle" }),
		'<button class="btn btn--subtle btn--md" type="button">S</button>'
	);
});

test("button() explicit outline equals default", () => {
	assert.equal(
		button("O", { variant: "outline" }),
		'<button class="btn btn--outline btn--md" type="button">O</button>'
	);
});

test("button() unknown variant falls back to outline", () => {
	assert.equal(
		button("U", { variant: "weird" }),
		'<button class="btn btn--outline btn--md" type="button">U</button>'
	);
});

test("button() unknown size falls back to md", () => {
	assert.equal(button("U", { size: "weird" }), '<button class="btn btn--outline btn--md" type="button">U</button>');
});

test("button() with leading icon", () => {
	assert.equal(
		button("Save", { icon: "star" }),
		`<button class="btn btn--outline btn--md" type="button">${icon("star")} Save</button>`
	);
});

test("button() disabled adds the disabled attribute (button tag)", () => {
	assert.equal(
		button("D", { disabled: true }),
		'<button class="btn btn--outline btn--md" type="button" disabled>D</button>'
	);
});

test("button() honours an explicit type", () => {
	assert.equal(button("D", { type: "submit" }), '<button class="btn btn--outline btn--md" type="submit">D</button>');
});

test("button() with internal href renders an <a> with no rel", () => {
	assert.equal(button("Link", { href: "/x" }), '<a class="btn btn--outline btn--md" href="/x">Link</a>');
});

test("button() with external href appends rel=nofollow", () => {
	assert.equal(
		button("Ext", { href: "https://e.org" }),
		'<a class="btn btn--outline btn--md" href="https://e.org" rel="nofollow">Ext</a>'
	);
});

test("button() external + disabled renders aria-disabled/tabindex on the <a>", () => {
	assert.equal(
		button("Ext", { href: "https://e.org", disabled: true }),
		'<a class="btn btn--outline btn--md" href="https://e.org" aria-disabled="true" tabindex="-1" rel="nofollow">Ext</a>'
	);
});

test("button() external merges nofollow into an existing rel token", () => {
	assert.equal(
		button("Ext", { href: "https://e.org", attrs: 'rel="noopener"' }),
		'<a class="btn btn--outline btn--md" href="https://e.org" rel="noopener nofollow">Ext</a>'
	);
});

test("button() external appends rel after other attrs when rel is absent", () => {
	assert.equal(
		button("Ext", { href: "https://e.org", attrs: 'target="_blank"' }),
		'<a class="btn btn--outline btn--md" href="https://e.org" target="_blank" rel="nofollow">Ext</a>'
	);
});

test("button() href with 'http' only in the query string stays internal (^-anchored)", () => {
	assert.equal(
		button("L", { href: "/x?u=https://y" }),
		'<a class="btn btn--outline btn--md" href="/x?u=https://y">L</a>'
	);
});

test("button() plain http:// (not https) href is treated as outbound", () => {
	assert.equal(
		button("E", { href: "http://e.org" }),
		'<a class="btn btn--outline btn--md" href="http://e.org" rel="nofollow">E</a>'
	);
});

test("button() collapses empty rel tokens from multi-space rel values", () => {
	// Without .filter(Boolean) the double space would yield 'noopener  nofollow'.
	assert.equal(
		button("E", { href: "https://e.org", attrs: 'rel="noopener  "' }),
		'<a class="btn btn--outline btn--md" href="https://e.org" rel="noopener nofollow">E</a>'
	);
});

test("button() internal href keeps custom attrs verbatim (no rel injected)", () => {
	assert.equal(
		button("L", { href: "/x", attrs: 'data-a="1"' }),
		'<a class="btn btn--outline btn--md" href="/x" data-a="1">L</a>'
	);
});

test("button() does not duplicate an existing nofollow rel token", () => {
	assert.equal(
		button("E", { href: "https://e.org", attrs: 'rel="nofollow noopener"' }),
		'<a class="btn btn--outline btn--md" href="https://e.org" rel="nofollow noopener">E</a>'
	);
});

test("button() escapes the label", () => {
	assert.equal(
		button("<a>&\"'"),
		'<button class="btn btn--outline btn--md" type="button">&lt;a&gt;&amp;&quot;&#39;</button>'
	);
});

// ---- iconButton() -------------------------------------------------------------
test("iconButton() basic: icon class, aria-label, button tag", () => {
	assert.equal(
		iconButton("star", "Favorite"),
		`<button class="btn btn--icon btn--md" aria-label="Favorite" type="button">${icon("star")}</button>`
	);
});

test("iconButton() ghost variant yields no variant class", () => {
	assert.equal(
		iconButton("star", "Fav", { variant: "ghost" }),
		`<button class="btn btn--icon btn--md" aria-label="Fav" type="button">${icon("star")}</button>`
	);
});

test("iconButton() danger variant + lg size + cls", () => {
	assert.equal(
		iconButton("close", "Close", { variant: "danger", size: "lg", cls: "c" }),
		`<button class="btn btn--icon btn--danger btn--lg c" aria-label="Close" type="button">${icon("close")}</button>`
	);
});

test("iconButton() with external href is an <a> with rel=nofollow", () => {
	assert.equal(
		iconButton("external", "Open", { href: "https://e.org" }),
		`<a class="btn btn--icon btn--md" aria-label="Open" href="https://e.org" rel="nofollow">${icon("external")}</a>`
	);
});

test("iconButton() disabled adds disabled attribute", () => {
	assert.equal(
		iconButton("close", "Close", { disabled: true }),
		`<button class="btn btn--icon btn--md" aria-label="Close" type="button" disabled>${icon("close")}</button>`
	);
});

test("iconButton() escapes the aria-label", () => {
	assert.equal(
		iconButton("star", '<"x"'),
		`<button class="btn btn--icon btn--md" aria-label="&lt;&quot;x&quot;" type="button">${icon("star")}</button>`
	);
});

test("iconButton() throws without an ariaLabel", () => {
	assert.throws(() => iconButton("star", ""), /iconButton requires an ariaLabel/);
	assert.throws(() => iconButton("star"), /iconButton requires an ariaLabel/);
});
