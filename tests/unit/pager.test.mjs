// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test } from "vitest";
import { renderPager } from "../../public_html/lib/molecules/pager.js";

test("renderPager() returns empty for a single page or fewer", () => {
	assert.equal(renderPager(1, 1), "");
	assert.equal(renderPager(1, 0), "");
});

test("renderPager() first page of 3 disables Prev, marks page 1 current", () => {
	assert.equal(
		renderPager(1, 3),
		'<button class="pager__btn" type="button" disabled data-page="0">‹ Prev</button><button class="pager__btn is-current" type="button"  data-page="1" aria-current="page">1</button><button class="pager__btn" type="button"  data-page="2">2</button><button class="pager__btn" type="button"  data-page="3">3</button><button class="pager__btn" type="button"  data-page="2">Next ›</button>'
	);
});

test("renderPager() middle page of 3", () => {
	assert.equal(
		renderPager(2, 3),
		'<button class="pager__btn" type="button"  data-page="1">‹ Prev</button><button class="pager__btn" type="button"  data-page="1">1</button><button class="pager__btn is-current" type="button"  data-page="2" aria-current="page">2</button><button class="pager__btn" type="button"  data-page="3">3</button><button class="pager__btn" type="button"  data-page="3">Next ›</button>'
	);
});

test("renderPager() last page of 3 disables Next", () => {
	assert.equal(
		renderPager(3, 3),
		'<button class="pager__btn" type="button"  data-page="2">‹ Prev</button><button class="pager__btn" type="button"  data-page="1">1</button><button class="pager__btn" type="button"  data-page="2">2</button><button class="pager__btn is-current" type="button"  data-page="3" aria-current="page">3</button><button class="pager__btn" type="button" disabled data-page="4">Next ›</button>'
	);
});

test("renderPager() windowed with gaps on both sides (5 of 10)", () => {
	assert.equal(
		renderPager(5, 10),
		'<button class="pager__btn" type="button"  data-page="4">‹ Prev</button><button class="pager__btn" type="button"  data-page="1">1</button><span class="pager__gap">…</span><button class="pager__btn" type="button"  data-page="3">3</button><button class="pager__btn" type="button"  data-page="4">4</button><button class="pager__btn is-current" type="button"  data-page="5" aria-current="page">5</button><button class="pager__btn" type="button"  data-page="6">6</button><button class="pager__btn" type="button"  data-page="7">7</button><span class="pager__gap">…</span><button class="pager__btn" type="button"  data-page="10">10</button><button class="pager__btn" type="button"  data-page="6">Next ›</button>'
	);
});

test("renderPager() trailing gap only (1 of 10)", () => {
	assert.equal(
		renderPager(1, 10),
		'<button class="pager__btn" type="button" disabled data-page="0">‹ Prev</button><button class="pager__btn is-current" type="button"  data-page="1" aria-current="page">1</button><button class="pager__btn" type="button"  data-page="2">2</button><button class="pager__btn" type="button"  data-page="3">3</button><span class="pager__gap">…</span><button class="pager__btn" type="button"  data-page="10">10</button><button class="pager__btn" type="button"  data-page="2">Next ›</button>'
	);
});

test("renderPager() leading gap only (10 of 10)", () => {
	assert.equal(
		renderPager(10, 10),
		'<button class="pager__btn" type="button"  data-page="9">‹ Prev</button><button class="pager__btn" type="button"  data-page="1">1</button><span class="pager__gap">…</span><button class="pager__btn" type="button"  data-page="8">8</button><button class="pager__btn" type="button"  data-page="9">9</button><button class="pager__btn is-current" type="button"  data-page="10" aria-current="page">10</button><button class="pager__btn" type="button" disabled data-page="11">Next ›</button>'
	);
});
