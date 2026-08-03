// SPDX-License-Identifier: GPL-3.0-or-later
import { $, $$, esc } from "../core/dom.js";
import { backendGetJson } from "../core/api.js";
import { t } from "../core/i18n.js";
import {
	clearWhatsNewCollapsed,
	disableWhatsNewAutoOpen,
	markWhatsNewCollapsed,
	markWhatsNewSeen,
	whatsNewForced,
	whatsNewCollapsed,
	whatsNewNever
} from "../core/release-notices.js";

const ROOT_ID = "whats-new";
const BODY_ID = "whats-new-body";

/** @type {{ deployments?: Deployment[] } | null} */
let releaseData = null;
/** @type {HTMLElement | null} */
let lastFocus = null;
let initialized = false;

/** @typedef {{ id?: string, sha?: string, deployedAt?: string, changes?: Change[], marketing?: { technical?: string, user?: string } }} Deployment */
/** @typedef {{ sha?: string, shortSha?: string, authoredAt?: string, subject?: string }} Change */

function root() {
	return $(`#${ROOT_ID}`);
}

function latestDeployment() {
	return releaseData?.deployments?.[0] || null;
}

function deploymentId(deployment) {
	return String(deployment?.id || deployment?.sha || "");
}

/** @param {string | undefined} value */
function dateLabel(value) {
	if (!value) return t("whatsNew.unknownDate", "Date unavailable");
	const date = new Date(value);
	if (Number.isNaN(date.getTime())) return t("whatsNew.unknownDate", "Date unavailable");
	return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

/** @param {Deployment} deployment */
function deploymentHTML(deployment) {
	const id = deploymentId(deployment);
	const changes = Array.isArray(deployment.changes) ? deployment.changes : [];
	const commitLink = deployment.sha
		? `<a href="https://github.com/schiste/toolhub-evolved/commit/${encodeURIComponent(deployment.sha)}" target="_blank" rel="noopener nofollow">${esc(id)}</a>`
		: esc(id);
	const changeHTML =
		changes.length > 0
			? `<ul class="whats-new__changes">${changes
					.slice(0, 12)
					.map(
						(change) =>
							`<li><span>${esc(change.subject || t("whatsNew.unnamedChange", "Unlabelled change"))}</span> <a href="https://github.com/schiste/toolhub-evolved/commit/${encodeURIComponent(change.sha || "")}" target="_blank" rel="noopener nofollow">${esc(change.shortSha || "commit")}</a></li>`
					)
					.join("")}</ul>`
			: `<p class="whats-new__empty">${esc(t("whatsNew.noChanges", "No individual changes were recorded for this deploy."))}</p>`;
	const userNotes = deployment.marketing?.user
		? `<div class="whats-new__summary"><h4>${esc(t("whatsNew.forUsers", "For users"))}</h4><div class="whats-new__markdown">${esc(deployment.marketing.user)}</div></div>`
		: "";
	const technicalNotes = deployment.marketing?.technical
		? `<details class="whats-new__technical"><summary class="whats-new__technical-summary">${esc(t("whatsNew.technicalDetails", "Technical details"))}</summary><div class="whats-new__markdown">${esc(deployment.marketing.technical)}</div></details>`
		: "";
	return `<section class="whats-new__deploy" aria-labelledby="whats-new-deploy-${esc(id)}">
		<div class="whats-new__deploy-head">
			<div><h3 id="whats-new-deploy-${esc(id)}">${esc(t("whatsNew.deployed", "Deployed {date}", { date: dateLabel(deployment.deployedAt) }))}</h3>
			<p>${esc(t("whatsNew.commit", "Serving commit"))} ${commitLink}</p></div>
			<span class="whats-new__badge">${esc(t("whatsNew.deploy", "Deploy"))}</span>
		</div>${userNotes}${technicalNotes}${changeHTML}
	</section>`;
}

export function renderWhatsNew() {
	const body = $(`#${BODY_ID}`);
	if (!body) return;
	const deployments = Array.isArray(releaseData?.deployments) ? releaseData.deployments.slice(0, 2) : [];
	body.innerHTML =
		deployments.length > 0
			? deployments.map((deployment) => deploymentHTML(deployment)).join("")
			: `<p class="whats-new__empty">${esc(t("whatsNew.noDeployments", "No deployment notes are available yet."))}</p>`;
}

/** @param {boolean} [remember] */
export function closeWhatsNew(remember = true) {
	const element = root();
	if (!element || element.classList.contains("hidden")) return;
	if (remember) {
		const latest = latestDeployment();
		if (latest) markWhatsNewSeen(deploymentId(latest));
	}
	markWhatsNewCollapsed();
	element.classList.add("is-collapsed");
	element.setAttribute("aria-hidden", "false");
	$("[data-whats-new-open]", element)?.setAttribute("aria-expanded", "false");
	if (lastFocus instanceof HTMLElement) lastFocus.focus();
}

function hideWhatsNew() {
	const element = root();
	if (!element) return;
	element.classList.add("hidden");
	element.classList.remove("is-collapsed");
	element.setAttribute("aria-hidden", "true");
	$("[data-whats-new-open]", element)?.setAttribute("aria-expanded", "false");
	if (lastFocus instanceof HTMLElement) lastFocus.focus();
}

function showCollapsedWhatsNew() {
	const element = root();
	if (!element) return;
	renderWhatsNew();
	element.classList.remove("hidden");
	element.classList.add("is-collapsed");
	element.setAttribute("aria-hidden", "false");
	$("[data-whats-new-open]", element)?.setAttribute("aria-expanded", "false");
}

export function openWhatsNew() {
	const element = root();
	if (!element) return;
	lastFocus = /** @type {HTMLElement | null} */ (document.activeElement);
	clearWhatsNewCollapsed();
	renderWhatsNew();
	element.classList.remove("hidden");
	element.classList.remove("is-collapsed");
	element.setAttribute("aria-hidden", "false");
	$("[data-whats-new-open]", element)?.setAttribute("aria-expanded", "true");
	$("[data-whats-new-close]")?.focus();
}

/** @param {KeyboardEvent} event */
function trapTab(event) {
	const element = root();
	if (
		!element ||
		element.classList.contains("hidden") ||
		element.classList.contains("is-collapsed") ||
		event.key !== "Tab"
	) {
		return;
	}
	const focusable = $$('button:not([disabled]),a[href],[tabindex]:not([tabindex="-1"])', element).filter(
		(node) => !node.hidden && node.offsetParent !== null
	);
	if (focusable.length === 0) return;
	const first = focusable[0];
	const last = focusable[focusable.length - 1];
	if (event.shiftKey && document.activeElement === first) {
		event.preventDefault();
		last.focus();
	} else if (!event.shiftKey && document.activeElement === last) {
		event.preventDefault();
		first.focus();
	}
}

export async function initWhatsNew() {
	if (initialized) return;
	initialized = true;
	const element = root();
	if (!element) return;
	element.addEventListener("click", (event) => {
		if (event.target?.closest("[data-whats-new-close]")) closeWhatsNew();
		if (event.target?.closest("[data-whats-new-never]")) {
			disableWhatsNewAutoOpen();
			hideWhatsNew();
		}
	});
	document.addEventListener("click", (event) => {
		if (event.target?.closest("[data-whats-new-open]")) {
			event.preventDefault();
			openWhatsNew();
		}
	});
	document.addEventListener("keydown", (event) => {
		if (event.key === "Escape") closeWhatsNew();
		else trapTab(event);
	});
	releaseData = await backendGetJson("/data/deployments.json");
	if (!releaseData) return;
	if (whatsNewForced() || (!whatsNewNever() && !whatsNewCollapsed())) openWhatsNew();
	else if (!whatsNewNever()) showCollapsedWhatsNew();
}

export function resetWhatsNewForTests() {
	initialized = false;
	releaseData = null;
	lastFocus = null;
}
