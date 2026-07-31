// SPDX-License-Identifier: GPL-3.0-or-later
// Snapshot compatibility for page-level fixtures. The tool-card unit oracle
// asserts the current markup directly; these page snapshots focus on layout
// composition and normalize only the card interaction markup.
const BTN_STYLE =
	"appearance: none; border: 0; background: none; padding: 0; color: inherit; font-family: inherit; text-align: start; cursor: pointer;";

/** @param {string} value */
function decode(value) {
	try {
		return decodeURIComponent(value);
	} catch {
		return value;
	}
}

/** @param {string} html */
export function legacyToolCardSnapshot(html) {
	return html
		.replaceAll(
			/<a class="tcard__title" href="\/tools\/([^"]+)"([^>]*)>([\s\S]*?)<\/a>/g,
			(_match, name, attrs, content) =>
				`<button class="tcard__title" type="button" data-tool="${decode(name)}" aria-label="Quick look: ${content}" style="${BTN_STYLE}"${attrs}>${content}</button>`
		)
		.replaceAll(
			/<a class="tcard__maint-name([^"]*)" href="[^"]+" title="([^"]*)" aria-label="([^"]*)">([\s\S]*?)<\/a>/g,
			(_match, classes, title, label, content) =>
				`<span class="tcard__maint-name${classes}" title="${title}" aria-label="${label}">${content}</span>`
		)
		.replaceAll(
			/<a class="tag" href="\/search\?keywords__term=([^"]+)"([^>]*)>([\s\S]*?)<\/a>/g,
			(_match, keyword, attrs, content) =>
				`<span class="tag" data-q="${decode(keyword)}"${attrs}>${content}</span>`
		);
}
