// SPDX-License-Identifier: GPL-3.0-or-later
import { backendGetJson, backendWriteJson } from "../lib/core/api.js";
import { esc } from "../lib/core/dom.js";
import { t } from "../lib/core/i18n.js";
import { serverWrite } from "../lib/core/serversync.js";
import { signedIn } from "../lib/core/session.js";

/** @typedef {"daily" | "weekly" | "monthly"} Cadence */
/** @type {Cadence[]} */
const CADENCES = ["daily", "weekly", "monthly"];
/** @param {Cadence} cadence */
const label = (cadence) =>
	({
		daily: t("digests.cadence.daily", "Daily"),
		weekly: t("digests.cadence.weekly", "Weekly"),
		monthly: t("digests.cadence.monthly", "Monthly")
	})[cadence];

/** @param {string | undefined} value */
function dateLabel(value) {
	const date = new Date(value || "");
	return Number.isNaN(date.getTime())
		? t("digests.dateUnavailable", "Date unavailable")
		: new Intl.DateTimeFormat(undefined, { dateStyle: "long", timeZone: "UTC" }).format(date);
}

/** @param {unknown} error */
function errorMessage(error) {
	return error && typeof error === "object" && "message" in error ? String(error.message) : String(error);
}

/** @param {any} edition */
function editionRow(edition) {
	const href = `/digests/${encodeURIComponent(edition.cadence)}/${encodeURIComponent(edition.editionKey)}`;
	const count = Array.isArray(edition.tools) ? edition.tools.length : 0;
	return `<article class="digest-list__entry">
		<time class="digest-list__date" datetime="${esc(edition.periodStart || "")}">${esc(dateLabel(edition.periodStart))}</time>
		<div class="digest-list__story"><p class="digest-kicker">${esc(label(edition.cadence))} · ${esc(t("digests.toolsAdded", "$1 {{PLURAL:$1|tool|tools}} added", count))}</p>
		<h2><a href="${href}">${esc(edition.title)}</a></h2><p>${esc(edition.introduction)}</p>
		<a class="digest-list__read" href="${href}">${esc(t("digests.readEdition", "Read edition"))} <span aria-hidden="true">→</span></a></div>
	</article>`;
}

/** @param {any} subscription */
function subscriptionRow(subscription) {
	const destination =
		subscription.channel === "email"
			? t("digests.subscription.wikimediaEmail", "Wikimedia email")
			: t("digests.subscription.talkDestination", "Talk page on $1", subscription.wikiDomain);
	const state = subscription.active
		? t("digests.subscription.active", "Active")
		: subscription.confirmed
			? t("digests.subscription.paused", "Paused")
			: t("digests.subscription.awaitingConfirmation", "Awaiting confirmation");
	return `<li class="digest-subscriptions__item" data-subscription-row="${subscription.id}"><div>
		<strong>${esc(label(subscription.cadence))} · ${esc(destination)}</strong><span>${esc(state)}</span></div>
		<button class="digest-text-button" type="button" data-delete-subscription="${subscription.id}">${esc(t("digests.subscription.stop", "Stop"))}</button></li>`;
}

/** @param {any[]} subscriptions @param {Cadence} cadence */
function subscriptionSection(subscriptions, cadence) {
	if (!signedIn()) {
		return `<section class="digest-subscribe digest-subscribe--signed-out"><div><p class="digest-kicker">${esc(t("digests.subscribe.kicker", "Get the digest"))}</p>
		<h2>${esc(t("digests.subscribe.signInTitle", "Send updates to your Wikimedia account"))}</h2></div>
		<p>${esc(t("digests.subscribe.signInBody", "Sign in to receive an edition by Wikimedia email or on a wiki talk page."))}</p>
		<a class="btn btn--primary btn--md" href="/login">${esc(t("digests.subscribe.signIn", "Sign in to subscribe"))}</a></section>`;
	}
	const rows = subscriptions.map((subscription) => subscriptionRow(subscription)).join("");
	return `<section class="digest-subscribe" aria-labelledby="digest-subscribe-title"><div class="digest-subscribe__intro">
		<p class="digest-kicker">${esc(t("digests.subscribe.kicker", "Get the digest"))}</p>
		<h2 id="digest-subscribe-title">${esc(t("digests.subscribe.title", "Choose how it reaches you"))}</h2>
		<p>${esc(t("digests.subscribe.body", "Email uses your private Wikimedia email settings. Talk-page delivery posts from the configured service account."))}</p></div>
		<form class="digest-subscribe__form" data-digest-subscribe>
		<label>${esc(t("digests.subscribe.cadence", "Cadence"))}<select name="cadence">${CADENCES.map((item) => `<option value="${item}"${item === cadence ? " selected" : ""}>${esc(label(item))}</option>`).join("")}</select></label>
		<fieldset><legend>${esc(t("digests.subscribe.delivery", "Delivery"))}</legend>
		<label class="digest-choice"><input type="radio" name="channel" value="email" checked /><span><strong>${esc(t("digests.subscribe.email", "Wikimedia email"))}</strong><small>${esc(t("digests.subscribe.emailHint", "We never see or store your email address."))}</small></span></label>
		<label class="digest-choice"><input type="radio" name="channel" value="talk" /><span><strong>${esc(t("digests.subscribe.talk", "Wiki talk page"))}</strong><small>${esc(t("digests.subscribe.talkHint", "Choose any public Wikimedia wiki where your account exists."))}</small></span></label></fieldset>
		<label data-wiki-domain hidden>${esc(t("digests.subscribe.wiki", "Wiki domain"))}<input name="wikiDomain" value="meta.wikimedia.org" /></label>
		<button class="btn btn--primary btn--md" type="submit">${esc(t("digests.subscribe.submit", "Subscribe"))}</button>
		<p class="digest-subscribe__status" data-subscribe-status role="status" aria-live="polite"></p></form>
		${rows ? `<div class="digest-subscriptions"><h3>${esc(t("digests.subscription.current", "Current subscriptions"))}</h3><ul>${rows}</ul></div>` : ""}</section>`;
}

/** @param {Cadence} cadence */
async function archiveView(cadence) {
	const [archive, subscriptionData] = await Promise.all([
		backendGetJson(`/v1/digests/?cadence=${encodeURIComponent(cadence)}`),
		signedIn() ? backendGetJson("/v1/digests/subscriptions/") : null
	]);
	const editions = Array.isArray(archive?.editions) ? archive.editions : [];
	const hasMore = archive?.pagination?.hasMore === true;
	const subscriptions = Array.isArray(subscriptionData?.subscriptions) ? subscriptionData.subscriptions : [];
	return {
		title: `${label(cadence)} ${t("digests.title", "Toolhub Digest")}`,
		styles: ["/styles/digests.css"],
		html: `<div class="digest-page"><header class="digest-masthead"><div class="digest-masthead__inner">
		<p class="digest-kicker">${esc(t("digests.masthead.kicker", "From the Toolhub catalog"))}</p><h1>${esc(t("digests.title", "Toolhub Digest"))}</h1>
		<p>${esc(t("digests.masthead.body", "A short editorial briefing on the tools newly added to Wikimedia's Toolhub."))}</p>
		<nav class="digest-cadences" aria-label="${esc(t("digests.cadence.label", "Digest cadence"))}">${CADENCES.map((item) => `<a href="/digests/${item}" class="digest-cadences__link${item === cadence ? " is-active" : ""}"${item === cadence ? ' aria-current="page"' : ""}>${esc(label(item))}</a>`).join("")}</nav>
		</div></header><main class="digest-layout"><div class="digest-layout__heading"><div><p class="digest-kicker">${esc(t("digests.archive.kicker", "Latest editions"))}</p><h2>${esc(label(cadence))}</h2></div>
		<a class="digest-rss" href="/feeds/digests/${cadence}.xml" target="_blank" rel="noopener">RSS <span aria-hidden="true">↗</span></a></div>
		<div class="digest-list" data-digest-list>${editions.map((/** @type {any} */ edition) => editionRow(edition)).join("") || `<p class="digest-empty">${esc(t("digests.archive.empty", "No edition has been published for this cadence yet."))}</p>`}</div>
		${hasMore ? `<button class="btn btn--outline btn--md digest-load-more" type="button" data-digest-load-more>${esc(t("digests.archive.more", "Load older editions"))}</button>` : ""}
		${subscriptionSection(subscriptions, cadence)}</main></div>`,
		mount: () => mountArchive(cadence)
	};
}

/** @param {Cadence} cadence @param {string} editionKey */
async function detailView(cadence, editionKey) {
	const edition = await backendGetJson(
		`/v1/digests/${encodeURIComponent(cadence)}/${encodeURIComponent(editionKey)}/`
	);
	if (!edition) throw new Error(t("digests.notFound", "Digest edition not found"));
	return {
		title: edition.title,
		styles: ["/styles/digests.css"],
		html: `<div class="digest-page digest-page--edition"><nav class="digest-edition-nav" aria-label="${esc(t("digests.editionNavigation", "Digest edition"))}">
		<a href="/digests/${esc(cadence)}"><span aria-hidden="true">←</span> ${esc(t("digests.backToArchive", "All $1 editions", label(cadence).toLowerCase()))}</a>
		<a href="/feeds/digests/${esc(cadence)}.xml" target="_blank" rel="noopener">RSS <span aria-hidden="true">↗</span></a></nav>
		<div class="digest-edition-body">${edition.html}</div><footer class="digest-edition-canonical"><p>${esc(t("digests.canonical", "This edition is permanently published on Meta-Wiki."))}</p>
		<a class="btn btn--outline btn--md" href="${esc(edition.metaPageUrl)}" target="_blank" rel="noopener">${esc(t("digests.readOnMeta", "Read on Meta-Wiki"))} ↗</a></footer></div>`
	};
}

/** @param {"confirm" | "unsubscribe"} action */
async function actionView(action) {
	const token = new URLSearchParams(location.search).get("token") || "";
	try {
		await backendWriteJson("POST", `/v1/digests/subscriptions/${action}/`, { token }, "");
		return actionResult(
			true,
			action === "confirm"
				? t("digests.action.confirmed", "Your digest subscription is confirmed.")
				: t("digests.action.unsubscribed", "That digest subscription has been stopped.")
		);
	} catch (error) {
		return actionResult(false, errorMessage(error));
	}
}

/** @param {boolean} ok @param {string} message */
function actionResult(ok, message) {
	return {
		title: t("digests.title", "Toolhub Digest"),
		styles: ["/styles/digests.css"],
		html: `<div class="digest-action"><p class="digest-kicker">${esc(t("digests.title", "Toolhub Digest"))}</p>
		<h1>${esc(ok ? t("digests.action.done", "You're all set") : t("digests.action.problem", "We couldn't update that subscription"))}</h1>
		<p>${esc(message)}</p><a class="btn btn--primary btn--md" href="/digests">${esc(t("digests.action.return", "Return to the digest"))}</a></div>`
	};
}

function mountSubscriptions() {
	const form = document.querySelector("[data-digest-subscribe]");
	if (!(form instanceof HTMLFormElement)) return;
	const domain = form.querySelector("[data-wiki-domain]");
	form.addEventListener("change", () => {
		if (domain instanceof HTMLElement) domain.hidden = new FormData(form).get("channel") !== "talk";
	});
	form.addEventListener("submit", async (event) => {
		event.preventDefault();
		const status = form.querySelector("[data-subscribe-status]");
		const submit = form.querySelector('button[type="submit"]');
		const data = new FormData(form);
		if (submit instanceof HTMLButtonElement) submit.disabled = true;
		try {
			const result = await serverWrite("POST", "/v1/digests/subscriptions/", {
				channel: data.get("channel"),
				cadence: data.get("cadence"),
				language: "en",
				wikiDomain: data.get("wikiDomain")
			});
			if (status) {
				status.textContent = result.subscription.confirmed
					? t("digests.subscribe.active", "Subscription active.")
					: t("digests.subscribe.checkEmail", "Check your Wikimedia email to confirm.");
			}
		} catch (error) {
			if (status) status.textContent = errorMessage(error);
		} finally {
			if (submit instanceof HTMLButtonElement) submit.disabled = false;
		}
	});
	document.querySelectorAll("[data-delete-subscription]").forEach((button) => {
		button.addEventListener("click", async () => {
			const id = button.getAttribute("data-delete-subscription");
			if (!id) {
				return;
			}
			button.setAttribute("disabled", "");
			try {
				await serverWrite("DELETE", `/v1/digests/subscriptions/${encodeURIComponent(id)}/`);
				document.querySelector(`[data-subscription-row="${CSS.escape(id)}"]`)?.remove();
			} catch {
				button.removeAttribute("disabled");
			}
		});
	});
}

/** @param {Cadence} cadence */
function mountArchive(cadence) {
	mountSubscriptions();
	const button = document.querySelector("[data-digest-load-more]");
	const list = document.querySelector("[data-digest-list]");
	if (!(button instanceof HTMLButtonElement) || !(list instanceof HTMLElement)) return;
	let page = 2;
	button.addEventListener("click", async () => {
		button.disabled = true;
		button.textContent = t("digests.archive.loading", "Loading…");
		try {
			const archive = await backendGetJson(`/v1/digests/?cadence=${encodeURIComponent(cadence)}&page=${page}`);
			const editions = Array.isArray(archive?.editions) ? archive.editions : [];
			list.insertAdjacentHTML(
				"beforeend",
				editions.map((/** @type {any} */ edition) => editionRow(edition)).join("")
			);
			page += 1;
			if (archive?.pagination?.hasMore !== true) {
				button.remove();
				return;
			}
			button.textContent = t("digests.archive.more", "Load older editions");
		} catch {
			button.textContent = t("digests.archive.loadError", "Try loading older editions again");
		} finally {
			button.disabled = false;
		}
	});
}

/** @param {string | undefined} cadence @param {string | undefined} editionKey @param {string | undefined} action */
export function viewDigests(cadence, editionKey, action) {
	if (action === "confirm" || action === "unsubscribe") return actionView(action);
	const selected = /** @type {Cadence} */ (CADENCES.includes(/** @type {Cadence} */ (cadence)) ? cadence : "weekly");
	return editionKey ? detailView(selected, editionKey) : archiveView(selected);
}
