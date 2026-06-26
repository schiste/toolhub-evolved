// SPDX-License-Identifier: GPL-3.0-or-later
import { $, $$, dirAttrs, esc, safeUrl } from "../core/dom.js";
import { updatedTimeTag } from "../core/i18n.js";
import { INDEX, getTool } from "../core/api.js";
import { renderMarkdown } from "../core/markdown.js";
import { signedIn } from "../core/session.js";
import { navigateTo, toolHref } from "../core/routing.js";
import { toolIcon } from "../atoms/avatar.js";
import { endorsementChip, fitChip, healthBadge, popularityBadge } from "../atoms/badges.js";
import { button } from "../atoms/button.js";
import { glanceChips, keywordTags } from "../atoms/labels.js";
import { favBtn } from "../molecules/favbtn.js";

export const QV_TAG_LIMIT = 6;
/* ---- Quick-view modal (peek from any listing) -------------------------- */
/** @type {HTMLElement | null} */
export let qvLastFocus = null;
/** @param {boolean} on */
export function setPageInert(on) {
	$$("body > *").forEach((el) => {
		if (el.id === "qv" || el.tagName === "SCRIPT") return;
		// Stryker disable next-line ConditionalExpression: `"inert" in el` is always true on real HTMLElements (and in happy-dom), so the guard's false branch is unreachable and forcing it true is equivalent. (The `el.inert = on` assignment itself is still asserted.)
		if ("inert" in el) el.inert = on;
		if (on) el.setAttribute("aria-hidden", "true");
		else el.removeAttribute("aria-hidden");
	});
}
/**
 * @param {Tool} t
 * @returns {string}
 */
export function quickViewBody(t) {
	const authors = (t.authors || []).map((author) => esc(author)).join(", ") || esc(t.maintainer);
	const tags = keywordTags(t, { limit: QV_TAG_LIMIT });
	// `endorsement` is attached at runtime by signals.js but isn't on the ambient Tool.
	const endorsement = /** @type {{ endorsement?: { count?: number } }} */ (t).endorsement;
	const realBadge = [
		t.deprecated && '<span class="status status--red"><span class="dot dot--red"></span>Deprecated</span>',
		t.experimental && '<span class="status status--yellow"><span class="dot dot--yellow"></span>Experimental</span>'
	]
		.filter(Boolean)
		.join("");
	const glance = glanceChips(t);
	return `
		<div class="qv__head">${toolIcon(t, "lg")}
			<div class="qv__id"><h2 class="qv__title" id="qv-title"${dirAttrs(t.title)}>${esc(t.title)}</h2>
			<div class="qv__by">by <span dir="auto">${authors}</span></div></div>
		</div>
		<div class="qv__status">
			${realBadge}
			${endorsementChip(endorsement && endorsement.count)}
			${fitChip(t)}
			<!-- EXPERIMENTAL — operational health. Needs: an uptime/health-check service. -->
			${healthBadge(t)}
			<!-- EXPERIMENTAL — popularity. Needs: usage/view tracking. -->
			${popularityBadge(t)}
			${updatedTimeTag(t.modified, "toolpage__when")}
		</div>
		<div class="qv__desc"${dirAttrs(t.description)}>${renderMarkdown(t.description) || "<em>No description provided.</em>"}</div>
		<div class="toolpage__glance">${glance}</div>
		<div class="tcard__tags qv__tags">${tags}</div>
		<div class="qv__actions">
			${t.url ? button("Open tool", { variant: "primary", href: safeUrl(t.url), icon: "external", attrs: 'target="_blank" rel="noopener nofollow"' }) : ""}
			${
				// Stryker disable next-line StringLiteral: button() applies `opts.variant || "outline"`, so emptying this "outline" variant string falls back to the same default — equivalent. (The label/href are still asserted.) Comments/newlines inside ${} do not affect the rendered string.
				button("View full page", { variant: "outline", href: toolHref(t.name) })
			}
			${signedIn() ? favBtn(t.name, { label: true, cls: "favbtn--btn" }) : ""}
		</div>`;
}
/** @param {string} name */
export async function openQuickView(name) {
	/** @type {Tool | undefined} */
	let t = /** @type {Record<string, Tool | undefined>} */ (INDEX)[name];
	if (!t) {
		const fetched = await getTool(name);
		if (!fetched) {
			navigateTo(toolHref(name));
			return;
		}
		t = /** @type {Tool} */ (fetched);
	}
	qvLastFocus = /** @type {HTMLElement | null} */ (document.activeElement);
	const body = $("#qv-body");
	const qv = $("#qv");
	if (body) body.innerHTML = quickViewBody(t);
	if (qv) {
		qv.classList.remove("hidden");
		qv.setAttribute("aria-hidden", "false");
	}
	setPageInert(true);
	document.body.style.overflow = "hidden";
	$(".qv__x")?.focus();
}
export function closeQuickView() {
	const qv = $("#qv");
	if (!qv || qv.classList.contains("hidden")) return;
	qv.classList.add("hidden");
	qv.setAttribute("aria-hidden", "true");
	setPageInert(false);
	document.body.style.overflow = "";
	// Stryker disable next-line ConditionalExpression,LogicalOperator: openQuickView always sets qvLastFocus to document.activeElement (never null) and HTMLElements always expose .focus, so this guard's false branch is unreachable once the modal has been opened — equivalent. (The focus() restoration is asserted by the close test.)
	if (qvLastFocus && qvLastFocus.focus) qvLastFocus.focus();
}
/** @param {KeyboardEvent} e */
export function qvTrap(e) {
	const qv = $("#qv");
	if (!qv) return;
	if (e.key !== "Tab" || qv.classList.contains("hidden")) return;
	const f = $$(
		'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])',
		qv
	).filter((el) => !el.hidden && el.offsetParent !== null);
	// Stryker disable next-line ConditionalExpression: defensive guard — when f is empty the following boundary logic (f[0]/f[f.length-1] are undefined, neither branch matches) is itself a no-op, so removing the early return has no observable effect — equivalent.
	if (f.length === 0) return;
	const first = f[0],
		last = f[f.length - 1];
	if (e.shiftKey && document.activeElement === first) {
		e.preventDefault();
		last.focus();
	} else if (!e.shiftKey && document.activeElement === last) {
		e.preventDefault();
		first.focus();
	}
}
