// SPDX-License-Identifier: GPL-3.0-or-later
import { iconFallbackAvatar } from "../atoms/avatar.js";

/** @param {Element} img */
function fallbackTitleForImage(img) {
	return (
		img.getAttribute("data-icon-fallback") ||
		img.closest("[data-tool]")?.querySelector(".tcard__title")?.textContent?.trim() ||
		img.closest(".qv__head")?.querySelector(".qv__title")?.textContent?.trim() ||
		img.closest(".toolpage__head")?.querySelector(".toolpage__title")?.textContent?.trim() ||
		"?"
	);
}

/** @param {Element} img */
function fallbackForImage(img) {
	const title = fallbackTitleForImage(img);
	const variant = img.classList.contains("avatar--lg") ? "lg" : "";
	return iconFallbackAvatar(title, variant, img.getAttribute("src") || "");
}

const ICON_FALLBACK_ROOTS = new WeakSet();

/** @param {Document | HTMLElement} [root] */
export function initIconFallbacks(root = document) {
	if (!root || ICON_FALLBACK_ROOTS.has(root)) return;
	root.addEventListener(
		"error",
		(event) => {
			const target = event.target;
			if (!(target instanceof Element) || target.tagName !== "IMG" || !target.classList.contains("avatar--img")) {
				return;
			}
			const doc = target.ownerDocument || document;
			const container = doc.createElement("template");
			container.innerHTML = fallbackForImage(target);
			target.replaceWith(/** @type {Node} */ (container.content.firstChild));
		},
		true
	);
	ICON_FALLBACK_ROOTS.add(root);
}
