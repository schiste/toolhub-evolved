// SPDX-License-Identifier: GPL-3.0-or-later
import { $, dirAttrs, esc } from "../core/dom.js";
import { t } from "../core/i18n.js";
import { button } from "../atoms/button.js";

/**
 * @typedef {"text" | "boolean" | "set" | "ordered-list"} ChangeKind
 * @typedef {object} ChangeDescriptor
 * @property {string} key
 * @property {string} label
 * @property {unknown} before
 * @property {unknown} after
 * @property {ChangeKind} [type]
 * @typedef {object} FieldChange
 * @property {string} key
 * @property {string} label
 * @property {ChangeKind} type
 * @property {string | boolean | string[]} before
 * @property {string | boolean | string[]} after
 * @property {string[]} [added]
 * @property {string[]} [removed]
 * @property {boolean} [reordered]
 */

/** @param {unknown} value */
function textValue(value) {
	return String(value ?? "").trim();
}

/** @param {unknown} value */
function listValue(value) {
	const raw = Array.isArray(value) ? value : value === null || value === undefined ? [] : [value];
	return raw.map((item) => textValue(item)).filter(Boolean);
}

/** @param {unknown} value */
function uniqueListValue(value) {
	const seen = new Set();
	return listValue(value).filter((item) => {
		if (seen.has(item)) return false;
		seen.add(item);
		return true;
	});
}

/** @param {string[]} items */
function sortedList(items) {
	return [...items].sort((a, b) => a.localeCompare(b));
}

/**
 * @param {string[]} a
 * @param {string[]} b
 */
function sameList(a, b) {
	return a.length === b.length && a.every((item, index) => item === b[index]);
}

/**
 * @param {unknown} value
 * @param {ChangeKind} type
 * @returns {string | boolean | string[]}
 */
function normalizedValue(value, type) {
	if (type === "boolean") return Boolean(value);
	if (type === "set") return uniqueListValue(value);
	if (type === "ordered-list") return listValue(value);
	return textValue(value);
}

/**
 * @param {string | boolean | string[]} before
 * @param {string | boolean | string[]} after
 * @param {ChangeKind} type
 */
function sameValue(before, after, type) {
	if (type === "set") {
		return sameList(sortedList(/** @type {string[]} */ (before)), sortedList(/** @type {string[]} */ (after)));
	}
	if (Array.isArray(before) && Array.isArray(after)) return sameList(before, after);
	return before === after;
}

/**
 * @param {ChangeDescriptor} descriptor
 * @returns {FieldChange | null}
 */
export function fieldChange(descriptor) {
	const type = descriptor.type || "text";
	const before = normalizedValue(descriptor.before, type);
	const after = normalizedValue(descriptor.after, type);
	if (sameValue(before, after, type)) return null;
	/** @type {FieldChange} */
	const change = { key: descriptor.key, label: descriptor.label, type, before, after };
	if (Array.isArray(before) && Array.isArray(after)) {
		change.added = after.filter((item) => !before.includes(item));
		change.removed = before.filter((item) => !after.includes(item));
		change.reordered = type === "ordered-list" && change.added.length === 0 && change.removed.length === 0;
	}
	return change;
}

/** @param {ChangeDescriptor[]} descriptors */
export function fieldChanges(descriptors) {
	return /** @type {FieldChange[]} */ (descriptors.map((descriptor) => fieldChange(descriptor)).filter(Boolean));
}

/** @param {FieldChange[]} changes */
export function changeSignature(changes) {
	return JSON.stringify(
		changes.map((change) => ({
			key: change.key,
			type: change.type,
			before: change.before,
			after: change.after
		}))
	);
}

/**
 * @param {{ title?: string, intro?: string, confirmLabel?: string, editLabel?: string }} [options]
 * @returns {string}
 */
export function changeReviewRegion(options = {}) {
	const title = options.title || t("changeReview.title", "Review changes before saving");
	const intro =
		options.intro ||
		t(
			"changeReview.intro",
			"Evolved will try to publish these changes to Toolhub first. If Toolhub rejects them, Evolved may keep the same changes as a local fallback."
		);
	return `<section class="change-review" data-change-review hidden aria-live="polite" aria-label="${esc(title)}">
		<h3 class="change-review__title">${esc(title)}</h3>
		<p class="change-review__intro">${esc(intro)}</p>
		<ul class="change-review__list" data-change-review-list></ul>
		<div class="change-review__actions">
			${button(options.confirmLabel || t("changeReview.publishChanges", "Publish changes"), { variant: "primary", attrs: "data-change-review-confirm" })}
			${button(options.editLabel || t("changeReview.keepEditing", "Keep editing"), { attrs: "data-change-review-edit" })}
		</div>
	</section>`;
}

/** @param {string | boolean | string[]} value */
function valueText(value) {
	if (Array.isArray(value)) return value.length > 0 ? value.join(", ") : t("changeReview.empty", "Empty");
	if (typeof value === "boolean") return value ? t("changeReview.yes", "Yes") : t("changeReview.no", "No");
	return value || t("changeReview.empty", "Empty");
}

/**
 * @param {string[]} items
 * @param {string} className
 */
function renderChips(items, className) {
	const classes = ["change-review__chip", className].filter(Boolean).join(" ");
	return items.map((item) => `<span class="${classes}"${dirAttrs(item)}>${esc(item)}</span>`).join("");
}

/** @param {string | boolean | string[]} value */
function renderValue(value) {
	if (Array.isArray(value)) {
		return value.length > 0
			? `<span class="change-review__chips">${renderChips(value, "")}</span>`
			: `<span class="change-review__empty">${esc(t("changeReview.empty", "Empty"))}</span>`;
	}
	const text = valueText(value);
	const isEmpty = text === t("changeReview.empty", "Empty");
	return `<span class="change-review__value${isEmpty ? " change-review__empty" : ""}"${dirAttrs(text)}>${esc(text)}</span>`;
}

/** @param {FieldChange} change */
function renderNotes(change) {
	const notes = [];
	if (change.added && change.added.length > 0) {
		notes.push(
			`<div class="change-review__note"><span>${esc(t("changeReview.added", "Added"))}</span>${renderChips(change.added, "change-review__chip--added")}</div>`
		);
	}
	if (change.removed && change.removed.length > 0) {
		notes.push(
			`<div class="change-review__note"><span>${esc(t("changeReview.removed", "Removed"))}</span>${renderChips(change.removed, "change-review__chip--removed")}</div>`
		);
	}
	if (change.reordered) {
		notes.push(
			`<div class="change-review__note"><span class="change-review__chip change-review__chip--reordered">${esc(t("changeReview.orderChanged", "Order changed"))}</span></div>`
		);
	}
	return notes.join("");
}

/** @param {FieldChange} change */
function renderChange(change) {
	return `<li class="change-review__item">
		<div class="change-review__field">${esc(change.label)}</div>
		<div class="change-review__grid">
			<div class="change-review__slot">
				<span class="change-review__label">${esc(t("changeReview.before", "Before"))}</span>
				${renderValue(change.before)}
			</div>
			<div class="change-review__slot">
				<span class="change-review__label">${esc(t("changeReview.after", "After"))}</span>
				${renderValue(change.after)}
			</div>
		</div>
		${renderNotes(change)}
	</li>`;
}

/**
 * @param {HTMLFormElement | HTMLElement} form
 * @param {{ title?: string, intro?: string, confirmLabel?: string, editLabel?: string }} [options]
 */
export function mountChangeReview(form, options = {}) {
	let region = $("[data-change-review]", form);
	if (!region) {
		const actions = $(".le__actions", form);
		if (!actions) throw new Error("mountChangeReview requires a .le__actions anchor");
		actions.insertAdjacentHTML("beforebegin", changeReviewRegion(options));
		region = /** @type {HTMLElement} */ ($("[data-change-review]", form));
	}
	if (!region) throw new Error("mountChangeReview could not create the review region");
	const mountedRegion = region;
	const list = /** @type {HTMLElement} */ ($("[data-change-review-list]", mountedRegion));
	let pendingSignature = "";
	let confirmedSignature = "";

	/** @param {FieldChange[]} changes */
	function render(changes) {
		pendingSignature = changeSignature(changes);
		list.innerHTML = changes.map((change) => renderChange(change)).join("");
		mountedRegion.hidden = false;
		if (typeof mountedRegion.scrollIntoView === "function") mountedRegion.scrollIntoView({ block: "nearest" });
		const confirm = $("[data-change-review-confirm]", mountedRegion);
		if (confirm) confirm.focus();
	}

	function hide() {
		mountedRegion.hidden = true;
		pendingSignature = "";
		list.innerHTML = "";
	}

	mountedRegion.addEventListener("click", (event) => {
		const target = /** @type {EventTarget} */ (event.target);
		if (target.closest("[data-change-review-confirm]")) {
			confirmedSignature = pendingSignature;
			mountedRegion.hidden = true;
			form.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));
			return;
		}
		if (target.closest("[data-change-review-edit]")) hide();
	});

	return {
		hide,
		reset() {
			confirmedSignature = "";
			hide();
		},
		/** @param {FieldChange[]} changes */
		shouldProceed(changes) {
			const signature = changeSignature(changes);
			if (confirmedSignature === signature) {
				confirmedSignature = "";
				hide();
				return true;
			}
			render(changes);
			return false;
		}
	};
}
