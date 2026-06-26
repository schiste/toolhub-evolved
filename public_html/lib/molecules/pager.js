// SPDX-License-Identifier: GPL-3.0-or-later
/**
 * @param {number} page
 * @param {number} pages
 * @returns {string}
 */
export function renderPager(page, pages) {
	if (pages <= 1) return "";
	/**
	 * @param {number} p
	 * @param {string | number} label
	 * @param {boolean} dis
	 * @param {boolean} [cur]
	 */
	const btn = (p, label, dis, cur) =>
		`<button class="pager__btn${cur ? " is-current" : ""}" type="button" ${dis ? "disabled" : ""} data-page="${p}"${cur ? ' aria-current="page"' : ""}>${label}</button>`;
	let out = btn(page - 1, "‹ Prev", page <= 1),
		last = 0;
	const win = [];
	for (let p = 1; p <= pages; p++) if (p === 1 || p === pages || Math.abs(p - page) <= 2) win.push(p);
	win.forEach((p) => {
		if (p - last > 1) out += '<span class="pager__gap">…</span>';
		out += btn(p, p, false, p === page);
		last = p;
	});
	return out + btn(page + 1, "Next ›", page >= pages);
}
