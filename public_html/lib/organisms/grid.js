// SPDX-License-Identifier: GPL-3.0-or-later
export function grid(cls, items, render) {
	// a11y: a grid of cards is a list (1.3.1). role="list" keeps the semantics
	// even though list-style:none is applied (Safari drops it otherwise).
	return `<ul class="card-grid ${cls}" role="list">${items.map((it, i) => `<li>${render(it, i)}</li>`).join("")}</ul>`;
}
