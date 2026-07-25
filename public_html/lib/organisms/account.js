// SPDX-License-Identifier: GPL-3.0-or-later
import { $, esc } from "../core/dom.js";
import { t } from "../core/i18n.js";
import { USER, expOn, serverUserName, signedIn } from "../core/session.js";
import { oauthAvailable } from "../core/serversync.js";
import { avatar } from "../atoms/avatar.js";
import { button } from "../atoms/button.js";
import { icon } from "../atoms/icon.js";

export function renderAccount() {
	const el = $("#account");
	if (!el) return;
	if (!expOn()) {
		// Feature mode off: real Wikimedia sign-in when the server offers it
		// (signing in turns feature mode on), else the explainer page.
		// Stryker disable next-line StringLiteral: button() applies `opts.variant || "outline"`, so emptying the "outline" variant string falls back to the same default — equivalent. (The label/href strings are still asserted by the renderAccount tests.)
		el.innerHTML = button(t("account.logIn", "Log in"), {
			variant: "outline",
			href: oauthAvailable() ? "/oauth/login" : "/login"
		});
		return;
	}
	if (!signedIn()) {
		// Feature mode on but logged out → real sign-in first (when configured),
		// with the browser-local demo identity as the fallback preview.
		// Stryker disable next-line StringLiteral: button() applies `opts.variant || "outline"`, so emptying the "outline" variant string falls back to the same default — equivalent. (The label/attrs strings are still asserted by the renderAccount tests.)
		const wm = oauthAvailable()
			? button(t("account.signInWithWikimedia", "Sign in with Wikimedia"), { href: "/oauth/login" })
			: "";
		// Stryker disable next-line StringLiteral: button() applies `opts.variant || "outline"`, so emptying the "outline" variant string falls back to the same default — equivalent. (The label/attrs strings are still asserted by the renderAccount tests.)
		el.innerHTML = `${wm}${button(t("account.signInDemo", "Sign in demo"), { variant: "outline", attrs: "data-login" })}`;
		return;
	}
	const real = serverUserName() !== null;
	el.innerHTML = `
		<button class="acct__btn" id="acct-btn" type="button" aria-haspopup="true" aria-expanded="false" aria-controls="acct-menu">
			${avatar(USER.name, "avatar--sm")}
			<span class="acct__name">${esc(USER.name)}</span>
			${icon("chevronDown", "acct__caret")}
		</button>
		<div class="acct__menu" id="acct-menu" aria-labelledby="acct-btn" hidden>
			<div class="acct__head">${t("account.signedInAs", "Signed in as")} <strong>${esc(USER.name)}</strong> ${real ? "" : `<span class="mock-tag">${t("account.demo", "demo")}</span>`}</div>
			<a href="/my-lists">${icon("list")} ${t("account.yourLists", "Your lists")}</a>
			<a href="/favorites">${icon("star")} ${t("account.favorites", "Favorites")}</a>
			<a href="/add-or-remove-tools">${icon("tools")} ${t("account.addOrRemoveTools", "Add or remove tools")}</a>
			<hr />
			${real ? `<a class="acct__logout" href="/oauth/logout">${icon("logout")} ${t("account.logOut", "Log out")}</a>` : `<button class="acct__reset" type="button" data-reset>${icon("reset")} ${t("account.resetDemoData", "Reset demo data")}</button><button class="acct__logout" type="button" data-logout>${icon("logout")} ${t("account.logOut", "Log out")}</button>`}
		</div>`;
}
export function closeAcctMenu() {
	const m = $("#acct-menu"),
		b = $("#acct-btn");
	if (m) m.hidden = true;
	if (b) b.setAttribute("aria-expanded", "false");
}
export function toggleAcctMenu() {
	const m = $("#acct-menu"),
		b = $("#acct-btn");
	if (!m) return;
	const willOpen = m.hidden;
	m.hidden = !willOpen;
	if (b) b.setAttribute("aria-expanded", String(willOpen));
	if (willOpen) {
		const first = $("a, button", m);
		if (first) first.focus();
	}
}

// Header "Submit a tool": in-app create form when experimenting (decision §8.3),
// else the real production link.
export function syncSubmitButton() {
	const b = $("#submit-tool");
	if (!b) return;
	if (expOn()) {
		b.setAttribute("href", "/tools/create");
		b.removeAttribute("target");
		b.removeAttribute("rel");
	} else {
		b.setAttribute("href", "https://toolhub.wikimedia.org/add-or-remove-tools?tab=tool-create");
		b.setAttribute("target", "_blank");
		b.setAttribute("rel", "noopener nofollow");
	}
}

globalThis.renderAccount = renderAccount;
