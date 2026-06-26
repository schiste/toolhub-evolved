// SPDX-License-Identifier: GPL-3.0-or-later
// Color theme: "system" (default) | "light" | "dark". The choice is persisted in
// localStorage; "system" follows the OS preference live. The resolved value is
// reflected as <html data-theme="light|dark"> (see styles/tokens.css). An inline
// script in index.html applies it before first paint to avoid a flash.
const THEME_KEY = "toolhub-theme";
const darkMQ =
	// Stryker disable next-line ConditionalExpression,LogicalOperator,StringLiteral — the no-DOM/no-matchMedia guard is always true under the (always-present) test DOM, so darkMQ === matchMedia(...) for every variant: equivalent.
	typeof window !== "undefined" && window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;

export function getThemeChoice() {
	let v = null;
	try {
		v = localStorage.getItem(THEME_KEY);
	} catch {
		/* ignore */
	}
	return v === "light" || v === "dark" ? v : "system";
}

/** @param {string} choice */
function resolve(choice) {
	if (choice === "light" || choice === "dark") return choice;
	return darkMQ && darkMQ.matches ? "dark" : "light";
}

/** @param {string} [choice] */
export function applyTheme(choice = getThemeChoice()) {
	document.documentElement.setAttribute("data-theme", resolve(choice));
}

/** @param {string} choice */
export function setThemeChoice(choice) {
	try {
		if (choice === "light" || choice === "dark") localStorage.setItem(THEME_KEY, choice);
		else localStorage.removeItem(THEME_KEY); // "system" is the default — store nothing
	} catch {
		/* ignore */
	}
	applyTheme(choice);
}

// Apply now + keep following the OS preference while the choice is "system".
export function initTheme() {
	applyTheme();
	// Stryker disable next-line ConditionalExpression — darkMQ is always truthy under the test DOM, so `if (false)` never returns early either: equivalent (the `if (true)` variant IS killed).
	if (!darkMQ) return;
	const onChange = () => {
		// Stryker disable next-line StringLiteral — resolve() treats "system" and "" identically (both fall through to the OS-preference branch), so applyTheme("") behaves exactly like applyTheme("system"): equivalent.
		if (getThemeChoice() === "system") applyTheme("system");
	};
	if (darkMQ.addEventListener) darkMQ.addEventListener("change", onChange);
	else if (darkMQ.addListener) darkMQ.addListener(onChange);
}
