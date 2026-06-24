// SPDX-License-Identifier: GPL-3.0-or-later
// Color theme: "system" (default) | "light" | "dark". The choice is persisted in
// localStorage; "system" follows the OS preference live. The resolved value is
// reflected as <html data-theme="light|dark"> (see styles/tokens.css). An inline
// script in index.html applies it before first paint to avoid a flash.
const THEME_KEY = "toolhub-theme";
const darkMQ = typeof window !== "undefined" && window.matchMedia
	? window.matchMedia("(prefers-color-scheme: dark)") : null;

export function getThemeChoice() {
	let v = null;
	try { v = localStorage.getItem(THEME_KEY); } catch (e) { /* ignore */ }
	return v === "light" || v === "dark" ? v : "system";
}

function resolve(choice) {
	if (choice === "light" || choice === "dark") return choice;
	return darkMQ && darkMQ.matches ? "dark" : "light";
}

export function applyTheme(choice = getThemeChoice()) {
	document.documentElement.setAttribute("data-theme", resolve(choice));
}

export function setThemeChoice(choice) {
	try {
		if (choice === "light" || choice === "dark") localStorage.setItem(THEME_KEY, choice);
		else localStorage.removeItem(THEME_KEY); // "system" is the default — store nothing
	} catch (e) { /* ignore */ }
	applyTheme(choice);
}

// Apply now + keep following the OS preference while the choice is "system".
export function initTheme() {
	applyTheme();
	if (!darkMQ) return;
	const onChange = () => { if (getThemeChoice() === "system") applyTheme("system"); };
	if (darkMQ.addEventListener) darkMQ.addEventListener("change", onChange);
	else if (darkMQ.addListener) darkMQ.addListener(onChange);
}
