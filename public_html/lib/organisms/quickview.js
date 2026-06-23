// SPDX-License-Identifier: GPL-3.0-or-later
import { $, $$, dirAttrs, esc, safeUrl } from "../core/dom.js";
import { updatedTimeTag } from "../core/i18n.js";
import { INDEX, getTool } from "../core/api.js";
import { signedIn } from "../core/session.js";
import { toolHref } from "../core/routing.js";
import { toolIcon } from "../atoms/avatar.js";
import { healthBadge, popularityBadge, statusBadge } from "../atoms/badges.js";
import { icon } from "../atoms/icon.js";
import { glanceChips, keywordTags } from "../atoms/labels.js";
import { favBtn } from "../molecules/favbtn.js";

export const QV_TAG_LIMIT = 6;
/* ---- Quick-view modal (peek from any listing) -------------------------- */
export let qvLastFocus = null;
export function setPageInert(on) {
	$$("body > *").forEach((el) => {
		if (el.id === "qv" || el.tagName === "SCRIPT") return;
		if ("inert" in el) el.inert = on;
		if (on) el.setAttribute("aria-hidden", "true");
		else el.removeAttribute("aria-hidden");
	});
}
export function quickViewBody(t) {
	const authors = (t.authors || []).map(esc).join(", ") || esc(t.maintainer);
	const tags = keywordTags(t, { limit: QV_TAG_LIMIT });
	const realBadge = statusBadge(t);
	const glance = glanceChips(t);
	return `
		<div class="qv__head">${toolIcon(t, "lg")}
			<div class="qv__id"><h2 class="qv__title" id="qv-title"${dirAttrs(t.title)}>${esc(t.title)}</h2>
			<div class="qv__by">by <span dir="auto">${authors}</span></div></div>
		</div>
		<div class="qv__status">
			${realBadge}
			<!-- EXPERIMENTAL — operational health. Needs: an uptime/health-check service. -->
			${healthBadge(t)}
			<!-- EXPERIMENTAL — popularity. Needs: usage/view tracking. -->
			${popularityBadge(t)}
			${updatedTimeTag(t.modified, "toolpage__when")}
		</div>
		<p class="qv__desc"${dirAttrs(t.description)}>${esc(t.description) || "<em>No description provided.</em>"}</p>
		<div class="toolpage__glance">${glance}</div>
		<div class="tcard__tags qv__tags">${tags}</div>
		<div class="qv__actions">
			${t.url ? `<a class="btn btn--primary" href="${safeUrl(t.url)}" target="_blank" rel="noopener">Open tool ${icon("external")}</a>` : ""}
			<a class="btn btn--outline" href="${toolHref(t.name)}">View full page <span aria-hidden="true">→</span></a>
			${signedIn() ? favBtn(t.name, { label: true, cls: "favbtn--btn" }) : ""}
		</div>`;
}
export async function openQuickView(name) {
	let t = INDEX[name];
	if (!t) {
		t = await getTool(name);
		if (!t) { location.hash = toolHref(name); return; }
	}
	qvLastFocus = document.activeElement;
	$("#qv-body").innerHTML = quickViewBody(t);
	$("#qv").classList.remove("hidden");
	$("#qv").setAttribute("aria-hidden", "false");
	setPageInert(true);
	document.body.style.overflow = "hidden";
	$(".qv__x").focus();
}
export function closeQuickView() {
	const qv = $("#qv");
	if (!qv || qv.classList.contains("hidden")) return;
	qv.classList.add("hidden");
	qv.setAttribute("aria-hidden", "true");
	setPageInert(false);
	document.body.style.overflow = "";
	if (qvLastFocus && qvLastFocus.focus) qvLastFocus.focus();
}
export function qvTrap(e) {
	const qv = $("#qv");
	if (e.key !== "Tab" || qv.classList.contains("hidden")) return;
	const f = Array.from(qv.querySelectorAll('a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])'))
		.filter((el) => !el.hidden && el.offsetParent !== null);
	if (!f.length) return;
	const first = f[0], last = f[f.length - 1];
	if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
	else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
}
