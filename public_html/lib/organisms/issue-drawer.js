// SPDX-License-Identifier: GPL-3.0-or-later
import { $, esc } from "../core/dom.js";
import { backendErrorExplanation } from "../core/api.js";
import { pageDiagnostics } from "../core/diagnostics.js";
import { t } from "../core/i18n.js";
import { signedIn } from "../core/session.js";
import { oauthAvailable, serverWrite } from "../core/serversync.js";
import { icon } from "../atoms/icon.js";

/** @type {(() => Record<string, any>) | null} */
let contextProvider = null;
/** @type {HTMLElement | null} */
let lastFocus = null;
/** @type {{ title: string, description: string, context: Record<string, any>, clientId: string } | null} */
let draft = null;

/** @param {() => Record<string, any>} provider */
export function setIssueContext(provider) {
	contextProvider = typeof provider === "function" ? provider : null;
}

export function clearIssueContext() {
	contextProvider = null;
}

function newClientId() {
	if (typeof crypto === "object" && typeof crypto.randomUUID === "function") {
		return crypto.randomUUID().replaceAll("-", "");
	}
	return `${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`.padEnd(16, "0").slice(0, 64);
}

function drawer() {
	return $("#issue-drawer");
}

function body() {
	return $("#issue-drawer-body");
}

function focusFirst() {
	window.setTimeout(() => body()?.querySelector("input, textarea, button")?.focus(), 0);
}

function contextSnapshot(includeConsole = true) {
	const diagnostics = pageDiagnostics();
	if (!includeConsole) {
		diagnostics.console = [];
		diagnostics.errors = [];
	}
	const custom = contextProvider?.();
	return custom && typeof custom === "object" ? { ...diagnostics, custom } : diagnostics;
}

function contextSummary(context) {
	const logCount = Array.isArray(context.console) ? context.console.length : 0;
	const errorCount = Array.isArray(context.errors) ? context.errors.length : 0;
	return `<dl class="issue-drawer__context-summary">
		<div><dt>${t("issueReport.pageLabel", "Page")}</dt><dd>${esc(context.path || "/")}</dd></div>
		<div><dt>${t("issueReport.logsLabel", "Console entries")}</dt><dd>${logCount}</dd></div>
		<div><dt>${t("issueReport.errorsLabel", "Browser errors")}</dt><dd>${errorCount}</dd></div>
	</dl>`;
}

function formHTML(
	values = { title: `Report from Toolhub Evolved: ${document.title}`, description: "", includeConsole: true }
) {
	return `<form class="issue-drawer__form" data-issue-form>
		<div class="issue-drawer__intro">
			<p>${t("issueReport.formIntro", "Describe what went wrong or what could be improved. The page context below will be attached for review.")}</p>
			<p class="issue-drawer__privacy">${t("issueReport.publicNote", "The approved report will be published publicly on GitHub. Review the attached context before publishing.")}</p>
		</div>
		<label class="le__label" for="issue-report-title">${t("issueReport.titleLabel", "Issue title")}
			<input class="le__input" id="issue-report-title" name="title" maxlength="200" required value="${esc(values.title)}" />
		</label>
		<label class="le__label" for="issue-report-description">${t("issueReport.descriptionLabel", "What happened?")}
			<textarea class="le__input" id="issue-report-description" name="description" rows="7" maxlength="12000" required placeholder="${esc(t("issueReport.descriptionPlaceholder", "Tell us what you expected and what happened instead."))}">${esc(values.description)}</textarea>
		</label>
		<label class="le__check issue-drawer__check"><input type="checkbox" name="includeConsole"${values.includeConsole ? " checked" : ""} /> ${t("issueReport.includeConsole", "Include console logs and browser errors for this page")}</label>
		<details class="issue-drawer__context" open>
			<summary class="issue-drawer__context-toggle">${t("issueReport.contextTitle", "Attached page context")}</summary>
			${contextSummary(contextSnapshot(values.includeConsole))}
			<p class="le__hint">${t("issueReport.contextHint", "This includes the current URL, browser, viewport, page timings, and recent diagnostics for this route.")}</p>
		</details>
		<div class="issue-drawer__actions">
			<button class="btn btn--outline" type="button" data-issue-close>${icon("close")} ${t("issueReport.cancel", "Cancel")}</button>
			<button class="btn btn--primary" type="submit">${icon("chevronRight")} ${t("issueReport.review", "Review issue")}</button>
		</div>
	</form>`;
}

function loginHTML() {
	const loginHref = oauthAvailable() ? "/oauth/login" : "/login";
	return `<div class="issue-drawer__login">
		<div class="issue-drawer__login-icon" aria-hidden="true">${icon("lifeBuoy")}</div>
		<h3>${t("issueReport.loginTitle", "Sign in to report an issue")}</h3>
		<p>${t("issueReport.loginBody", "Sign in with Wikimedia OAuth so we can associate your report with a verified account and publish it after your review.")}</p>
		<a class="btn btn--primary" href="${loginHref}">${icon("language")} ${t("issueReport.loginAction", "Sign in with Wikimedia OAuth")}</a>
	</div>`;
}

function reviewHTML(report) {
	return `<div class="issue-drawer__review">
		<p class="issue-drawer__intro">${t("issueReport.reviewIntro", "Check the public issue before it is sent to GitHub.")}</p>
		<div class="issue-drawer__review-block"><div class="issue-drawer__review-label">${t("issueReport.titleLabel", "Issue title")}</div><h3>${esc(report.title)}</h3></div>
		<div class="issue-drawer__review-block"><div class="issue-drawer__review-label">${t("issueReport.descriptionLabel", "What happened?")}</div><p>${esc(report.description)}</p></div>
		<details class="issue-drawer__context">
			<summary class="issue-drawer__context-toggle">${t("issueReport.contextTitle", "Attached page context")}</summary>
			${contextSummary(report.context)}
			<pre class="issue-drawer__context-json">${esc(JSON.stringify(report.context, null, 2))}</pre>
		</details>
		<p class="issue-drawer__privacy">${t("issueReport.publishWarning", "Publishing creates a public GitHub issue in the Toolhub Evolved repository.")}</p>
		<div class="issue-drawer__actions">
			<button class="btn btn--outline" type="button" data-issue-back>${icon("chevronLeft")}${t("issueReport.back", "Back to edit")}</button>
			<button class="btn btn--primary" type="button" data-issue-publish>${icon("report")}${t("issueReport.publish", "Publish issue")}</button>
		</div>
		<p class="issue-drawer__error" data-issue-error role="alert" hidden></p>
	</div>`;
}

function successHTML(result) {
	return `<div class="issue-drawer__success" role="status">
		<div class="issue-drawer__success-icon">${icon("check")}</div>
		<h3>${t("issueReport.successTitle", "Issue published")}</h3>
		<p>${t("issueReport.successBody", "Your report is now available on GitHub.")}</p>
		<a class="btn btn--primary" href="${esc(result.url)}" target="_blank" rel="noopener nofollow">${icon("external")} ${t("issueReport.openIssue", "Open issue #$1", result.number)}</a>
		<button class="btn btn--outline" type="button" data-issue-close>${t("issueReport.close", "Close")}</button>
	</div>`;
}

function showForm() {
	const target = body();
	if (!target) return;
	target.innerHTML = formHTML(draft || undefined);
	focusFirst();
}

function showContent() {
	if (signedIn()) {
		showForm();
		return;
	}
	const target = body();
	if (target) target.innerHTML = loginHTML();
	focusFirst();
}

function open() {
	const root = drawer();
	if (!root) return;
	lastFocus = /** @type {HTMLElement | null} */ (document.activeElement);
	draft = null;
	root.classList.remove("hidden");
	root.setAttribute("aria-hidden", "false");
	document.body.classList.add("issue-drawer-open");
	showContent();
}

function close() {
	const root = drawer();
	if (!root) return;
	root.classList.add("hidden");
	root.setAttribute("aria-hidden", "true");
	document.body.classList.remove("issue-drawer-open");
	draft = null;
	lastFocus?.focus?.();
	lastFocus = null;
}

function setError(message) {
	const node = body()?.querySelector("[data-issue-error]");
	if (!node) return;
	node.textContent = message;
	node.hidden = !message;
}

async function publish() {
	if (!draft) {
		return;
	}
	const button = body()?.querySelector("[data-issue-publish]");
	if (button?.disabled) return;
	if (button) button.disabled = true;
	setError("");
	try {
		const result = await serverWrite("POST", "/v1/issue-reports/", { ...draft, approved: true });
		if (!result?.number || !result?.url) {
			throw new Error(t("issueReport.invalidResponse", "GitHub returned no issue number."));
		}
		const target = body();
		if (target) target.innerHTML = successHTML(result);
	} catch (error) {
		setError(backendErrorExplanation(error));
		if (button) button.disabled = false;
	}
}

export function syncIssueReportTrigger() {
	const triggers = document.querySelectorAll("[data-issue-trigger]");
	const external = $("[data-issue-external]");
	for (const trigger of triggers) {
		trigger.hidden = !trigger.hasAttribute("data-issue-trigger-public") && !signedIn();
	}
	if (external) external.hidden = signedIn();
}

export function initIssueDrawer() {
	const root = drawer();
	if (!root || root.dataset.ready === "1") return;
	root.dataset.ready = "1";
	const fabIcon = $(".issue-report-fab__icon", root.parentElement || document);
	if (fabIcon) fabIcon.innerHTML = icon("lifeBuoy");
	document.addEventListener("click", (event) => {
		const target = /** @type {HTMLElement | null} */ (event.target);
		if (target?.closest("[data-issue-trigger]")) {
			event.preventDefault();
			open();
			return;
		}
		if (target?.closest("[data-issue-close]")) {
			event.preventDefault();
			close();
			return;
		}
		if (target?.closest("[data-issue-back]")) {
			draft = draft ? { ...draft, ...readForm() } : null;
			showForm();
			return;
		}
		if (target?.closest("[data-issue-publish]")) {
			publish();
		}
	});
	root.addEventListener("submit", (event) => {
		if (!event.target?.matches("[data-issue-form]")) return;
		event.preventDefault();
		const values = readForm();
		if (!values.title || !values.description) return;
		draft = {
			...values,
			context: contextSnapshot(values.includeConsole),
			clientId: draft?.clientId || newClientId()
		};
		const target = body();
		if (target) target.innerHTML = reviewHTML(draft);
		focusFirst();
	});
	document.addEventListener("keydown", (event) => {
		if (event.key === "Escape" && !root.classList.contains("hidden")) close();
	});
	document.addEventListener("toolhub:route-render-start", () => {
		clearIssueContext();
		if (!root.classList.contains("hidden")) close();
	});
	syncIssueReportTrigger();
}

function readForm() {
	const root = body();
	return {
		title: String(root?.querySelector("[name=title]")?.value || "").trim(),
		description: String(root?.querySelector("[name=description]")?.value || "").trim(),
		includeConsole: Boolean(root?.querySelector("[name=includeConsole]")?.checked)
	};
}
