// SPDX-License-Identifier: GPL-3.0-or-later
import { esc } from "../core/dom.js";
import { t } from "../core/i18n.js";
import { backendErrorExplanation } from "../core/api.js";
import { SYNC_STATUS, syncStatusLabel } from "../core/store.js";
import { button } from "../atoms/button.js";

const STATUS_CLASS = {
	[SYNC_STATUS.official]: "official",
	[SYNC_STATUS.localDraft]: "local-draft",
	[SYNC_STATUS.localFallback]: "local-fallback",
	[SYNC_STATUS.evolvedReal]: "evolved-real",
	[SYNC_STATUS.syncError]: "sync-error"
};

const REVIEW_CLASS = {
	pending: "review-pending",
	approved: "review-approved",
	rejected: "review-rejected"
};

/**
 * @param {unknown} status
 * @returns {string}
 */
function normalizeSyncStatus(status) {
	const value = String(status || "");
	return Object.values(SYNC_STATUS).includes(value) ? value : SYNC_STATUS.localDraft;
}

/**
 * @param {unknown} status
 * @returns {string}
 */
function normalizeReviewStatus(status) {
	const value = String(status || "").toLowerCase();
	return Object.hasOwn(REVIEW_CLASS, value) ? value : "";
}

/**
 * @param {unknown} status
 * @returns {string}
 */
function statusLabel(status) {
	const normalized = normalizeSyncStatus(status);
	return (
		{
			[SYNC_STATUS.official]: t("syncStatus.publishedToolhub", "Published to Toolhub"),
			[SYNC_STATUS.localDraft]: t("syncStatus.savedLocally", "Saved locally"),
			[SYNC_STATUS.localFallback]: t("syncStatus.savedFallback", "Saved locally after Toolhub rejected it"),
			[SYNC_STATUS.evolvedReal]: t("syncStatus.evolvedData", "Evolved data"),
			[SYNC_STATUS.syncError]: t("syncStatus.syncIssue", "Sync issue")
		}[normalized] || syncStatusLabel(normalized)
	);
}

/**
 * @param {unknown} status
 * @returns {string}
 */
function reviewLabel(status) {
	return (
		{
			pending: t("syncStatus.pendingReview", "Pending review"),
			approved: t("syncStatus.reviewApproved", "Reviewed"),
			rejected: t("syncStatus.reviewRejected", "Review rejected")
		}[normalizeReviewStatus(status)] || ""
	);
}

/**
 * @param {unknown} error
 * @returns {string[]}
 */
export function validationErrorMessages(error) {
	if (!error) return [];
	if (Array.isArray(error)) return error.flatMap((item) => validationErrorMessages(item));
	if (typeof error === "string") return [error];
	if (typeof error !== "object") return [String(error)];
	const record = /** @type {Record<string, any>} */ (error);
	if (record.message || record.detail) {
		const field = record.field || record.name;
		const msg = record.message || record.detail;
		return [field ? `${field}: ${msg}` : String(msg)];
	}
	return Object.entries(record).flatMap(([field, value]) => {
		if (Array.isArray(value)) return value.map((item) => `${field}: ${String(item)}`);
		if (value && typeof value === "object") {
			return validationErrorMessages(value).map((item) => `${field}: ${item}`);
		}
		return [`${field}: ${String(value)}`];
	});
}

/**
 * @param {Record<string, any> | null | undefined} meta
 * @returns {{ status: string, label: string, className: string, reviewStatus: string, reviewLabel: string, retryAvailable: boolean, lastError: string, validationErrors: string[] }}
 */
export function syncState(meta = {}) {
	const status = normalizeSyncStatus(meta?.syncStatus);
	const reviewStatus = normalizeReviewStatus(meta?.reviewStatus);
	return {
		status,
		label: statusLabel(status),
		className: STATUS_CLASS[status] || "unknown",
		reviewStatus,
		reviewLabel: reviewLabel(reviewStatus),
		retryAvailable:
			(status === SYNC_STATUS.localFallback || status === SYNC_STATUS.syncError) &&
			(!meta?.origin || meta.origin === "api"),
		lastError: meta?.lastError ? String(meta.lastError) : "",
		validationErrors: validationErrorMessages(meta?.validationErrors)
	};
}

/**
 * @param {Record<string, any> | null | undefined} meta
 * @param {{ label?: string }} [opts]
 * @returns {string}
 */
export function syncBadge(meta = {}, opts = {}) {
	const state = syncState(meta);
	const label = opts.label || state.label;
	return `<span class="sync-badge sync-badge--${esc(state.className)}">${esc(label)}</span>`;
}

/**
 * @param {unknown} status
 * @returns {string}
 */
export function reviewBadge(status) {
	const normalized = normalizeReviewStatus(status);
	if (!normalized) return "";
	return `<span class="sync-badge sync-badge--${esc(REVIEW_CLASS[/** @type {keyof typeof REVIEW_CLASS} */ (normalized)])}">${esc(reviewLabel(normalized))}</span>`;
}

/**
 * @param {string} fieldLabel
 * @param {Record<string, any> | null | undefined} meta
 * @returns {string}
 */
export function fieldProvenance(fieldLabel, meta = {}) {
	const state = syncState(meta);
	const aria = esc(t("syncStatus.fieldProvenanceAria", "{field} provenance", { field: fieldLabel }));
	const retry = state.retryAvailable
		? ` <span class="sync-badge sync-badge--retry">${t("syncStatus.retryAvailable", "Retry available")}</span>`
		: "";
	return `<span class="sync-field" aria-label="${aria}"><span class="sync-field__name">${esc(fieldLabel)}</span>${syncBadge(meta)}${reviewBadge(meta?.reviewStatus)}${retry}</span>`;
}

/**
 * @param {unknown} errors
 * @returns {string}
 */
export function validationErrorList(errors) {
	const rows = validationErrorMessages(errors);
	if (rows.length === 0) return "";
	return `<ul class="sync-errors">${rows.map((msg) => `<li>${esc(msg)}</li>`).join("")}</ul>`;
}

/**
 * @param {Record<string, any> | null | undefined} meta
 * @param {{ title?: string, retryAttrs?: string, discardAttrs?: string, retryLabel?: string, discardLabel?: string, showIfOfficial?: boolean, guidance?: string }} [opts]
 * @returns {string}
 */
export function syncStatusPanel(meta = {}, opts = {}) {
	const state = syncState(meta);
	if (state.status === SYNC_STATUS.official && !opts.showIfOfficial && !meta?.reviewStatus) return "";
	const upstreamResponse =
		meta?.toolhubResponse && typeof meta.toolhubResponse === "object" ? meta.toolhubResponse : {};
	const upstreamStatus = meta?.toolhubStatus ?? upstreamResponse.status_code ?? upstreamResponse.status;
	const upstreamCode = meta?.toolhubCode ?? upstreamResponse.code;
	const explanation = state.lastError
		? backendErrorExplanation({
				...meta,
				status: upstreamStatus ?? meta?.status
			})
		: "";
	const guidance = opts.guidance || explanation;
	const details = [
		upstreamStatus || upstreamCode
			? `<p class="sync-panel__diagnostic">${esc(t("syncStatus.upstreamDiagnostic", "Upstream result:"))} ${esc([upstreamStatus ? `HTTP ${upstreamStatus}` : "", upstreamCode ? `Toolhub code ${upstreamCode}` : ""].filter(Boolean).join(" · "))}</p>`
			: "",
		state.lastError
			? `<p class="sync-panel__detail">${t("syncStatus.lastError", "Toolhub response:")} ${esc(state.lastError)}</p>`
			: "",
		guidance
			? `<p class="sync-panel__guidance"><strong>${t("syncStatus.nextStep", "What this means:")}</strong> ${esc(guidance)}</p>`
			: "",
		validationErrorList(meta?.validationErrors)
	]
		.filter(Boolean)
		.join("");
	const actions = [
		state.retryAvailable && opts.retryAttrs
			? button(opts.retryLabel || t("syncStatus.retryPublish", "Retry Toolhub publish"), {
					variant: "outline",
					size: "sm",
					icon: "upload",
					attrs: opts.retryAttrs
				})
			: "",
		opts.discardAttrs
			? button(opts.discardLabel || t("syncStatus.discardLocal", "Discard local copy"), {
					variant: "danger",
					size: "sm",
					icon: "reset",
					attrs: opts.discardAttrs
				})
			: ""
	]
		.filter(Boolean)
		.join("");
	return `<div class="sync-panel sync-panel--${esc(state.className)}">
		<div class="sync-panel__head"><strong>${esc(opts.title || t("syncStatus.lifecycle", "Write status"))}</strong> ${syncBadge(meta)}${reviewBadge(meta?.reviewStatus)}${state.retryAvailable ? ` <span class="sync-badge sync-badge--retry">${t("syncStatus.retryAvailable", "Retry available")}</span>` : ""}</div>
		${details ? `<div class="sync-panel__body">${details}</div>` : ""}
		${actions ? `<div class="sync-panel__actions">${actions}</div>` : ""}
	</div>`;
}
