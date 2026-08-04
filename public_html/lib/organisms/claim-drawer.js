// SPDX-License-Identifier: GPL-3.0-or-later
import { esc, safeUrl } from "../core/dom.js";
import { backendErrorExplanation, backendGetJson } from "../core/api.js";
import { claimStatusLabel, relationshipLabel } from "../core/claims.js";
import { t } from "../core/i18n.js";
import { serverWrite } from "../core/serversync.js";
import { icon } from "../atoms/icon.js";

const METHODS = {
	author_display_name: {
		title: () => t("claim.authorTitle", "I am a listed author"),
		body: () =>
			t(
				"claim.authorBody",
				"Associate your account with a name already present in the canonical Toolhub author field. This is identity evidence, not verified ownership."
			)
	},
	toolforge_maintainer: {
		title: () => t("claim.toolforgeTitle", "Verify Toolforge maintenance"),
		body: () =>
			t(
				"claim.toolforgeBody",
				"Check your Wikimedia identity against Toolforge membership and the public Toolsadmin maintainer list."
			)
	},
	toolinfo_url_control: {
		title: () => t("claim.urlTitle", "Prove control of a toolinfo URL"),
		body: () =>
			t(
				"claim.urlBody",
				"Publish a short challenge token in the matching toolinfo record, then ask Evolved to verify it."
			)
	},
	signed_toolinfo: {
		title: () => t("claim.signedTitle", "Verify signed toolinfo"),
		body: () =>
			t(
				"claim.signedBody",
				"Verify a matching toolinfo record signed with one of the public keys registered in Developer settings."
			)
	},
	toolhub_write_access: {
		title: () => t("claim.recordOwnerTitle", "Toolhub record authority"),
		body: () =>
			t(
				"claim.recordOwnerBody",
				"This relationship is recorded automatically after your account successfully writes the official Toolhub record. It cannot be self-asserted here."
			)
	}
};

/** @type {HTMLElement | null} */
let lastFocus = null;
/** @type {string} */
let currentTool = "";
/** Every open/close transition invalidates work started by an older drawer. */
let drawerGeneration = 0;

function root() {
	return /** @type {HTMLElement | null} */ (document.querySelector("[data-claim-drawer]"));
}

function body() {
	return /** @type {HTMLElement | null} */ (document.querySelector("[data-claim-drawer-body]"));
}

function ensureDrawer() {
	if (root()) return;
	document.body.insertAdjacentHTML(
		"beforeend",
		`<div class="claim-drawer hidden" data-claim-drawer aria-hidden="true">
			<button class="claim-drawer__backdrop" type="button" tabindex="-1" data-claim-close aria-label="${esc(t("claim.close", "Close"))}"></button>
			<aside class="claim-drawer__panel" role="dialog" aria-modal="true" aria-labelledby="claim-drawer-title">
				<header class="claim-drawer__head">
					<div><p class="claim-drawer__eyebrow">${t("claim.eyebrow", "Tool relationship")}</p><h2 id="claim-drawer-title">${t("claim.title", "Claim a relationship")}</h2></div>
					<button class="claim-drawer__close" type="button" data-claim-close aria-label="${esc(t("claim.close", "Close"))}">${icon("close")}</button>
				</header>
				<div class="claim-drawer__body" data-claim-drawer-body></div>
			</aside>
		</div>`
	);
	const drawer = root();
	drawer?.addEventListener("click", handleClick);
	drawer?.addEventListener("submit", handleSubmit);
}

/** @param {string} method */
function methodAction(method) {
	const labels = /** @type {Record<string, string>} */ ({
		author_display_name: t("claim.associateName", "Associate this name"),
		toolforge_maintainer: t("claim.verifyMembership", "Verify membership"),
		toolinfo_url_control: t("claim.createChallenge", "Create challenge"),
		signed_toolinfo: t("claim.verifySignature", "Verify signature")
	});
	return labels[method] || t("claim.start", "Start verification");
}

/** @param {any} claim */
function claimRow(claim) {
	const meta =
		METHODS[/** @type {keyof typeof METHODS} */ (claim?.verificationMethod)] || METHODS.author_display_name;
	const evidenceUrl = safeUrl(claim?.evidenceUrl);
	const active = claim?.verificationStatus !== "revoked";
	const canVerify = active && !["author_display_name", "toolhub_write_access"].includes(claim?.verificationMethod);
	return `<article class="claim-record">
		<div class="claim-record__head"><strong>${esc(meta.title())}</strong><span class="claim-status claim-status--${esc(claim?.verificationStatus || "unverified")}">${esc(claimStatusLabel(String(claim?.verificationStatus || "unverified")))}</span></div>
		<p>${esc(relationshipLabel(claim?.requestedRelationship))} · ${esc(claim?.authorName || "")}</p>
		${claim?.lastError ? `<p class="claim-record__error">${esc(claim.lastError)}</p>` : ""}
		<div class="claim-record__actions">
			${evidenceUrl ? `<a class="claim-record__evidence" href="${esc(evidenceUrl)}" target="_blank" rel="noopener nofollow">${t("claim.viewEvidence", "View evidence")} ${icon("external")}</a>` : ""}
			${canVerify ? `<button class="btn btn--outline btn--sm" type="button" data-claim-verify="${esc(String(claim.id))}">${t("claim.verifyAgain", "Verify")}</button>` : ""}
			${active ? `<button class="btn btn--subtle btn--sm" type="button" data-claim-revoke="${esc(String(claim.id))}">${t("claim.revoke", "Revoke")}</button>` : ""}
		</div>
	</article>`;
}

/** @param {any} option */
function optionForm(option) {
	const meta = METHODS[/** @type {keyof typeof METHODS} */ (option.method)];
	if (!meta) return "";
	const unavailable = !option.available;
	let controls = "";
	if (option.method === "author_display_name") {
		controls = `<label class="le__label">${t("claim.authorName", "Name on the Toolhub record")}
			<select class="le__input" name="authorName" required>${(option.authorNames || []).map((/** @type {string} */ name) => `<option value="${esc(name)}">${esc(name)}</option>`).join("")}</select>
		</label>`;
	} else if (["toolinfo_url_control", "signed_toolinfo"].includes(option.method)) {
		controls = `<label class="le__label">${t("claim.toolinfoUrl", "Toolinfo URL")}
			<input class="le__input" type="url" name="toolinfoUrl" inputmode="url" placeholder="https://…/toolinfo.json" required />
		</label>`;
	}
	const action = option.automatic
		? `<p class="claim-option__automatic">${icon("check")} ${t("claim.automatic", "Recorded automatically after a successful official write")}</p>`
		: `<button class="btn btn--primary" type="submit"${unavailable ? " disabled" : ""}>${icon("chevronRight")} ${esc(methodAction(option.method))}</button>`;
	return `<form class="claim-option" data-claim-method="${esc(option.method)}">
		<div class="claim-option__copy"><h3>${esc(meta.title())}</h3><p>${esc(meta.body())}</p></div>
		${controls}
		${unavailable && !option.automatic ? `<p class="claim-option__unavailable">${t("claim.unavailable", "This proof method is not available for this tool or account.")}</p>` : ""}
		${action}
	</form>`;
}

/** @param {any} challenge */
function challengeNotice(challenge) {
	if (!challenge) return "";
	return `<section class="claim-challenge" role="status">
		<h3>${t("claim.challengeTitle", "Publish this challenge")}</h3>
		<p>${t("claim.challengeBody", "Add this field and token to the matching toolinfo record, publish it at the same URL, then choose Verify on the pending claim.")}</p>
		<dl><dt>${esc(challenge.field || "x_toolhub_evolved_verification")}</dt><dd><code>${esc(challenge.challengeToken || "")}</code></dd></dl>
	</section>`;
}

/** @param {any} data @param {any} [challenge] */
function render(data, challenge = null) {
	const target = body();
	if (!target) return;
	const claims = Array.isArray(data?.claims) ? data.claims : [];
	const options = Array.isArray(data?.options) ? data.options : [];
	target.innerHTML = `${challengeNotice(challenge)}
		<p class="claim-drawer__intro">${t("claim.intro", "Choose evidence that describes your real relationship to this canonical Toolhub record. Evolved verifies and records the evidence; it does not change Toolhub permissions or metadata.")}</p>
		${claims.length > 0 ? `<section class="claim-records"><h3>${t("claim.existing", "Your claims for this tool")}</h3>${claims.map((/** @type {any} */ claim) => claimRow(claim)).join("")}</section>` : ""}
		<section class="claim-options"><h3>${t("claim.proofMethods", "Proof methods")}</h3>${options.map((/** @type {any} */ option) => optionForm(option)).join("")}</section>
		<p class="claim-drawer__error" data-claim-error role="alert" hidden></p>`;
}

/** @param {any} error */
function showError(error) {
	const node = /** @type {HTMLElement | null} */ (body()?.querySelector("[data-claim-error]"));
	if (!node) return;
	node.textContent = typeof error === "string" ? error : backendErrorExplanation(error);
	node.hidden = false;
}

/** @param {string} tool @param {number} generation */
function isCurrent(tool, generation) {
	return currentTool === tool && drawerGeneration === generation && !root()?.classList.contains("hidden");
}

/** @param {string} tool @param {number} generation @param {any} [challenge] */
async function reload(tool, generation, challenge = null) {
	const data = await backendGetJson(`/v1/tools/${encodeURIComponent(tool)}/claim-options/`);
	if (!data) throw new Error(t("claim.loadFailed", "Could not load relationship options."));
	if (!isCurrent(tool, generation)) return false;
	render(data, challenge);
	return true;
}

/** @param {SubmitEvent} event */
async function handleSubmit(event) {
	const form = /** @type {HTMLFormElement | null} */ (event.target?.closest?.("[data-claim-method]"));
	if (!form) return;
	event.preventDefault();
	const submit = /** @type {HTMLButtonElement | null} */ (form.querySelector('button[type="submit"]'));
	if (submit?.disabled) return;
	if (submit) submit.disabled = true;
	const tool = currentTool;
	const generation = drawerGeneration;
	const values = new FormData(form);
	const payload = /** @type {Record<string, string | undefined>} */ ({ method: form.dataset.claimMethod });
	for (const key of ["authorName", "toolinfoUrl"]) {
		const value = String(values.get(key) || "").trim();
		if (value) payload[key] = value;
	}
	try {
		const result = await serverWrite("POST", `/v1/tools/${encodeURIComponent(tool)}/claims/`, payload);
		await reload(tool, generation, result?.challenge || null);
	} catch (error) {
		if (isCurrent(tool, generation)) {
			showError(error);
			if (submit) submit.disabled = false;
		}
	}
}

/** @param {Event} event */
async function handleClick(event) {
	const target = /** @type {HTMLElement | null} */ (event.target);
	if (target?.closest("[data-claim-close]")) {
		closeClaimDrawer();
		return;
	}
	const verify = target?.closest("[data-claim-verify]");
	const revoke = target?.closest("[data-claim-revoke]");
	if (!verify && !revoke) return;
	const id = verify?.getAttribute("data-claim-verify") || revoke?.getAttribute("data-claim-revoke");
	const tool = currentTool;
	const generation = drawerGeneration;
	const action = /** @type {HTMLButtonElement | null} */ (verify || revoke);
	if (action?.disabled) return;
	if (action) action.disabled = true;
	try {
		await serverWrite(verify ? "POST" : "DELETE", verify ? `/v1/claims/${id}/verify/` : `/v1/claims/${id}/`);
		await reload(tool, generation);
	} catch (error) {
		if (isCurrent(tool, generation)) {
			showError(error);
			if (action) action.disabled = false;
		}
	}
}

/** @param {string} toolName */
export async function openClaimDrawer(toolName) {
	ensureDrawer();
	currentTool = String(toolName || "").trim();
	const generation = ++drawerGeneration;
	const tool = currentTool;
	lastFocus = /** @type {HTMLElement | null} */ (document.activeElement);
	const drawer = root();
	if (!drawer || !currentTool) return;
	drawer.classList.remove("hidden");
	drawer.setAttribute("aria-hidden", "false");
	document.body.classList.add("claim-drawer-open");
	const target = body();
	if (target) {
		target.innerHTML = `<p class="claim-drawer__loading">${t("claim.loading", "Loading proof methods…")}</p>`;
	}
	try {
		if (!(await reload(tool, generation))) return;
		window.setTimeout(
			() => /** @type {HTMLElement | null} */ (body()?.querySelector("button, input, select"))?.focus(),
			0
		);
	} catch (error) {
		if (target && isCurrent(tool, generation)) {
			target.innerHTML = `<p class="claim-drawer__error" role="alert">${esc(backendErrorExplanation(error))}</p>`;
		}
	}
}

export function closeClaimDrawer() {
	const drawer = root();
	if (!drawer) return;
	drawer.classList.add("hidden");
	drawer.setAttribute("aria-hidden", "true");
	document.body.classList.remove("claim-drawer-open");
	drawerGeneration += 1;
	currentTool = "";
	lastFocus?.focus?.();
	lastFocus = null;
}

if (typeof document !== "undefined") {
	document.addEventListener("keydown", (event) => {
		const drawer = root();
		if (!drawer || drawer.classList.contains("hidden")) return;
		if (event.key === "Escape") {
			closeClaimDrawer();
			return;
		}
		if (event.key !== "Tab") return;
		const focusable = /** @type {HTMLElement[]} */ ([
			...drawer.querySelectorAll(
				'a[href], button:not([disabled]):not([tabindex="-1"]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
			)
		]);
		if (focusable.length === 0) return;
		const first = focusable[0];
		const last = focusable.at(-1);
		if (event.shiftKey && document.activeElement === first) {
			event.preventDefault();
			last?.focus();
		} else if (!event.shiftKey && document.activeElement === last) {
			event.preventDefault();
			first.focus();
		}
	});
}
