// SPDX-License-Identifier: GPL-3.0-or-later
import { $, esc } from "../core/dom.js";
import { USER, expOn, signedIn } from "../core/session.js";
import { avatar } from "../atoms/avatar.js";
import { button } from "../atoms/button.js";
import { icon } from "../atoms/icon.js";

export function renderAccount() {
	const el = $("#account");
	if (!el) return;
	if (!expOn()) {
		// honest read-only: real sign-in needs OAuth we don't have
		el.innerHTML = button("Log in", { variant: "outline", href: "/login" });
		return;
	}
	if (!signedIn()) {
		// experiments on but logged out → offer the demo sign-in
		el.innerHTML = button("Sign in demo", { variant: "outline", attrs: "data-login" });
		return;
	}
	el.innerHTML = `
		<button class="acct__btn" id="acct-btn" type="button" aria-haspopup="true" aria-expanded="false" aria-controls="acct-menu">
			${avatar(USER.name, "avatar--sm")}
			<span class="acct__name">${esc(USER.name)}</span>
			${icon("chevronDown", "acct__caret")}
		</button>
		<div class="acct__menu" id="acct-menu" aria-labelledby="acct-btn" hidden>
			<div class="acct__head">Signed in as <strong>${esc(USER.name)}</strong> <span class="mock-tag">demo</span></div>
			<a href="/my-lists">${icon("list")} Your lists</a>
			<a href="/favorites">${icon("star")} Favorites</a>
			<a href="/add-or-remove-tools">${icon("tools")} Add or remove tools</a>
			<hr />
			<button class="acct__reset" type="button" data-reset>${icon("reset")} Reset demo data</button>
			<button class="acct__logout" type="button" data-logout>${icon("logout")} Log out</button>
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
	b.setAttribute("aria-expanded", String(willOpen));
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
