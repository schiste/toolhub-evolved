// SPDX-License-Identifier: GPL-3.0-or-later
import { esc } from "../core/dom.js";

/** @param {string | null | undefined} value @returns {string[]} */
export function releaseNoteItems(value) {
	return String(value || "")
		.split("\n")
		.map((line) => line.trim().replace(/^[-*]\s+/, ""))
		.filter(Boolean);
}

/** @param {string | null | undefined} value @param {string} [className] */
export function releaseNotesHTML(value, className = "release-notes") {
	const items = releaseNoteItems(value);
	return items.length > 0
		? `<ul class="${esc(className)}">${items.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>`
		: "";
}
