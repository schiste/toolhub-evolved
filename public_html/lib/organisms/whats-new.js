// SPDX-License-Identifier: GPL-3.0-or-later
import { $, $$, esc, wrapTabFocus } from "../core/dom.js";
import { backendGetJson } from "../core/api.js";
import { t } from "../core/i18n.js";
import { releaseNotesHTML } from "../molecules/release-notes.js";
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

/** @typedef {{ id?: string, releaseId?: string, title?: string, sha?: string, releasedAt?: string, deployedAt?: string, marketing?: { technical?: string, user?: string } }} Deployment */

function root() {
	return $(`#${ROOT_ID}`);
}

function latestDeployment() {
	return releaseData?.deployments?.[0] || null;
}

/** @param {Deployment | null | undefined} deployment @returns {string} */
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
	const title = deployment.title || t("whatsNew.releaseFallback", "Product update");
	const commitLink = deployment.sha
		? `<a href="https://github.com/schiste/toolhub-evolved/commit/${encodeURIComponent(deployment.sha)}" target="_blank" rel="noopener nofollow">${esc(deployment.sha.slice(0, 12))}</a>`
		: esc(id);
	const userNotes = deployment.marketing?.user
		? `<div class="whats-new__summary"><h4>${esc(t("whatsNew.forUsers", "For users"))}</h4>${releaseNotesHTML(deployment.marketing.user, "whats-new__notes")}</div>`
		: "";
	const technicalNotes = deployment.marketing?.technical
		? `<details class="whats-new__technical"><summary class="whats-new__technical-summary">${esc(t("whatsNew.technicalDetails", "Technical details"))}</summary>${releaseNotesHTML(deployment.marketing.technical, "whats-new__notes")}</details>`
		: "";
	return `<section class="whats-new__deploy" aria-labelledby="whats-new-deploy-${esc(id)}">
		<div class="whats-new__deploy-head">
			<div><h3 id="whats-new-deploy-${esc(id)}">${esc(title)}</h3>
			<p>${esc(t("whatsNew.released", "Released $1", dateLabel(deployment.releasedAt || deployment.deployedAt)))}</p>
			<p>${esc(t("whatsNew.build", "Serving build"))} ${commitLink}</p></div>
			<span class="whats-new__badge">${esc(t("whatsNew.release", "Release"))}</span>
		</div>${userNotes}${technicalNotes}
	</section>`;
}

export function renderWhatsNew() {
	const body = $(`#${BODY_ID}`);
	if (!body) return;
	const deployments = Array.isArray(releaseData?.deployments) ? releaseData.deployments.slice(0, 2) : [];
	body.innerHTML =
		deployments.length > 0
			? deployments.map((deployment) => deploymentHTML(deployment)).join("")
			: `<p class="whats-new__empty">${esc(t("whatsNew.noReleases", "No release notes are available yet."))}</p>`;
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
	wrapTabFocus(event, focusable);
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
	// A manifest with no releases is still a truthy object, so the guard above
	// never caught it: a first visit opened a panel whose only content was
	// "no release notes are available yet", and moved focus into it. The
	// manifest ships empty in the repo and is filled in at deploy
	// (tools/record_deployment.py), so that is the state of every checkout and
	// every local run. Announce nothing until there is something to announce;
	// an explicit ?whats-new=1 still opens the panel, empty state included.
	const hasRelease = Boolean(latestDeployment());
	if (whatsNewForced() || (hasRelease && !whatsNewNever() && !whatsNewCollapsed())) openWhatsNew();
	else if (hasRelease && !whatsNewNever()) showCollapsedWhatsNew();
}

export function resetWhatsNewForTests() {
	initialized = false;
	releaseData = null;
	lastFocus = null;
}
