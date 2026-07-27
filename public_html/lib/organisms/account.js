// SPDX-License-Identifier: GPL-3.0-or-later
import { $, esc } from "../core/dom.js";
import { t } from "../core/i18n.js";
import { USER, signedIn } from "../core/session.js";
import { oauthAvailable } from "../core/serversync.js";
import { avatar } from "../atoms/avatar.js";
import { button } from "../atoms/button.js";
import { icon } from "../atoms/icon.js";

export function renderAccount() {
	const el = $("#account");
	if (!el) return;
	if (!signedIn()) {
		// Signed-out production: real Toolhub sign-in when configured.
		el.innerHTML = oauthAvailable()
			? button(t("account.signInWithToolhub", "Sign in with Toolhub"), { href: "/oauth/login" })
			: button(t("account.logIn", "Log in"), { variant: "outline", href: "/login" });
		return;
	}
	el.innerHTML = `
		<button class="acct__btn" id="acct-btn" type="button" aria-haspopup="true" aria-expanded="false" aria-controls="acct-menu">
			${avatar(USER.name, "avatar--sm")}
			<span class="acct__name">${esc(USER.name)}</span>
			${icon("chevronDown", "acct__caret")}
		</button>
		<div class="acct__menu" id="acct-menu" aria-labelledby="acct-btn" hidden>
			<div class="acct__head">${t("account.signedInAs", "Signed in as")} <strong>${esc(USER.name)}</strong></div>
			<a href="/my-lists">${icon("list")} ${t("account.yourLists", "Your lists")}</a>
			<a href="/my-tools">${icon("tools")} ${t("account.myTools", "My tools")}</a>
			<a href="/favorites">${icon("star")} ${t("account.favorites", "Favorites")}</a>
			<a href="/add-or-remove-tools">${icon("tools")} ${t("account.addOrRemoveTools", "Add or remove tools")}</a>
			<a href="/developer-settings">${icon("key")} ${t("account.developerSettings", "Developer settings")}</a>
			<a href="/account">${icon("tools")} ${t("account.dataSettings", "Evolved data settings")}</a>
			<hr />
			<a class="acct__logout" href="/oauth/logout">${icon("logout")} ${t("account.logOut", "Log out")}</a>
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

// Header "Submit a tool": production uses the hybrid in-app create flow.
export function syncSubmitButton() {
	const b = $("#submit-tool");
	if (!b) return;
	b.setAttribute("href", "/tools/create");
	b.removeAttribute("target");
	b.removeAttribute("rel");
}

globalThis.renderAccount = renderAccount;
