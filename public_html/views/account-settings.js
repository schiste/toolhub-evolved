// SPDX-License-Identifier: GPL-3.0-or-later
import { $, esc, safeUrl } from "../lib/core/dom.js";
import { backendErrorExplanation, backendGetJson } from "../lib/core/api.js";
import { claimMethodLabel, claimStatusLabel, relationshipLabel } from "../lib/core/claims.js";
import { t } from "../lib/core/i18n.js";
import { personHref, toolHref } from "../lib/core/routing.js";
import { serverWrite } from "../lib/core/serversync.js";
import { demoStore } from "../lib/core/store.js";
import { button } from "../lib/atoms/button.js";
import { logoutForm } from "../lib/organisms/account.js";
import { accountSection, accountWorkbenchPage } from "../lib/organisms/account-workbench.js";

function exportTextarea(value = "") {
	return `<textarea class="le__input account-data__export" data-export-json rows="12" aria-label="${t("accountData.exportJson", "Evolved data export JSON")}" readonly>${esc(value)}</textarea>`;
}

function profileForm() {
	return `<form class="account-profile" data-profile-form>
		<div class="account-profile__identity">
			<img class="account-profile__avatar" data-profile-avatar alt="" width="72" height="72" hidden />
			<div><strong data-profile-name>${t("accountData.profileLoading", "Loading profile…")}</strong><p class="signin-note" data-profile-link></p></div>
		</div>
		<label class="le__label">${t("accountData.bio", "Bio")}
			<textarea class="le__input" name="bio" rows="5" maxlength="2000" placeholder="${esc(t("accountData.bioPlaceholder", "What you work on and how people can reach you."))}"></textarea>
		</label>
		<div class="account-profile__fields">
			<label class="le__label">${t("accountData.location", "Location")}<input class="le__input" name="location" maxlength="255" /></label>
			<label class="le__label">${t("accountData.website", "Website")}<input class="le__input" name="websiteUrl" type="url" inputmode="url" placeholder="https://" /></label>
		</div>
		<label class="le__label">${t("accountData.avatar", "Avatar image URL")}
			<input class="le__input" name="avatarUrl" type="url" inputmode="url" placeholder="https://" />
		</label>
		<label class="le__label">${t("accountData.links", "Other links")}
			<textarea class="le__input" name="links" rows="4" placeholder="${esc(t("accountData.linksHint", "One HTTPS URL per line, up to 10."))}"></textarea>
		</label>
		<label class="le__check"><input type="checkbox" name="private" /> ${t("accountData.privateProfile", "Keep this profile content private")}</label>
		<div>${button(t("accountData.saveProfile", "Save profile"), { variant: "primary", type: "submit" })}</div>
	</form>`;
}

/** @param {any[]} claims */
function claimHistory(claims) {
	if (claims.length === 0) {
		return `<p class="empty">${t("accountData.noClaims", "You have not claimed a tool relationship yet.")}</p>`;
	}
	return `<div class="account-claims">${claims
		.map(
			(/** @type {any} */ claim) => `<article class="account-claim">
				<div><a href="${toolHref(claim.toolName)}"><strong>${esc(claim.toolName)}</strong></a><p>${esc(relationshipLabel(claim.requestedRelationship || ""))} · ${esc(claimMethodLabel(claim.verificationMethod || ""))}</p></div>
				<span class="claim-status claim-status--${esc(claim.verificationStatus || "unverified")}">${esc(claimStatusLabel(claim.verificationStatus || "unverified"))}</span>
			</article>`
		)
		.join("")}</div>`;
}

/** @param {any} profile */
function populateProfile(profile) {
	const form = /** @type {HTMLFormElement | null} */ ($("[data-profile-form]"));
	if (!form || !profile) return;
	for (const name of ["bio", "location", "websiteUrl", "avatarUrl"]) {
		const input = /** @type {HTMLInputElement | HTMLTextAreaElement | null} */ (form.elements.namedItem(name));
		if (input) input.value = profile[name] || "";
	}
	const links = /** @type {HTMLTextAreaElement | null} */ (form.elements.namedItem("links"));
	if (links) links.value = Array.isArray(profile.links) ? profile.links.join("\n") : "";
	const privateInput = /** @type {HTMLInputElement | null} */ (form.elements.namedItem("private"));
	if (privateInput) privateInput.checked = profile.visibility === "private";
	const name = $("[data-profile-name]");
	if (name) name.textContent = profile.displayName || t("authors.unknownPerson", "Unknown person");
	const link = $("[data-profile-link]");
	if (link && profile.personId) {
		link.innerHTML = `<a href="${personHref(profile.personId)}">${t("accountData.viewProfile", "View public profile")}</a> · <code>${esc(profile.personId)}</code>`;
	}
	updateAvatarPreview(profile.avatarUrl);
}

/** @param {any} value */
function updateAvatarPreview(value) {
	const image = /** @type {HTMLImageElement | null} */ ($("[data-profile-avatar]"));
	if (!image) return;
	const url = safeUrl(value);
	image.hidden = !url;
	if (url) image.src = url;
	else image.removeAttribute("src");
}

export function viewAccountSettings() {
	const html = accountWorkbenchPage({
		active: "preferences",
		title: t("accountData.title", "Preferences"),
		intro: t(
			"accountData.intro",
			"Manage Evolved-specific preferences and local account data attached to this Toolhub sign-in."
		),
		body: `
			${accountSection({
				id: "account-profile-title",
				title: t("accountData.profileTitle", "Public profile"),
				intro: t(
					"accountData.profileIntro",
					"This Evolved-owned profile is attached to your immutable person identity. Toolhub account and catalog data are unchanged."
				),
				body: profileForm()
			})}
			${accountSection({
				id: "account-claims-title",
				title: t("accountData.claimsTitle", "Relationship claims"),
				intro: t(
					"accountData.claimsIntro",
					"A history of the evidence you submitted for author, maintainer, and Toolhub record-authority relationships."
				),
				body: `<div data-claim-history><p class="signin-note">${t("accountData.claimsLoading", "Loading claims…")}</p></div>`
			})}
			${accountSection({
				id: "account-export-title",
				title: t("accountData.exportTitle", "Export Evolved data"),
				actions: button(t("accountData.exportButton", "Generate export"), {
					variant: "outline",
					attrs: "data-export"
				}),
				body: `<div data-export-box>${exportTextarea()}</div>`
			})}
			${accountSection({
				id: "account-delete-title",
				title: t("accountData.deleteTitle", "Delete Evolved-local data"),
				intro: t(
					"accountData.deleteNote",
					"This removes local drafts, fallbacks, overlays, local favorites cache, crawler URLs, and local activity rows stored by Toolhub Evolved."
				),
				actions: button(t("accountData.deleteButton", "Delete Evolved-local data"), {
					variant: "danger",
					attrs: "data-delete-evolved"
				}),
				body: ""
			})}
			${accountSection({
				id: "account-oauth-title",
				title: t("accountData.oauthTitle", "Toolhub connection"),
				body: `<div class="toolpage__actions">
					${button(t("accountData.reconnect", "Reconnect Toolhub OAuth"), {
						variant: "outline",
						href: "/oauth/login"
					})}
					${logoutForm(button(t("accountData.logout", "Log out"), { variant: "outline", type: "submit" }))}
				</div>`
			})}
			<p class="at__result" data-account-result aria-live="polite"></p>`
	});
	function mount() {
		const out = /** @type {HTMLElement} */ ($("[data-account-result]"));
		window.setTimeout(() => {
			Promise.all([backendGetJson("/v1/me/profile/"), backendGetJson("/v1/me/claims/")])
				.then(([profileData, claimData]) => {
					populateProfile(profileData?.profile);
					const target = $("[data-claim-history]");
					if (target) {
						target.innerHTML = claimHistory(Array.isArray(claimData?.claims) ? claimData.claims : []);
					}
				})
				.catch((error) => {
					const target = $("[data-claim-history]");
					if (target) {
						target.innerHTML = `<p class="at__result at__result--err">${esc(backendErrorExplanation(error))}</p>`;
					}
				});
		}, 0);
		const profileFormNode = /** @type {HTMLFormElement | null} */ ($("[data-profile-form]"));
		const avatarInput = /** @type {HTMLInputElement | null} */ (profileFormNode?.elements.namedItem("avatarUrl"));
		avatarInput?.addEventListener("input", (event) => {
			updateAvatarPreview(/** @type {HTMLInputElement} */ (event.target).value);
		});
		profileFormNode?.addEventListener("submit", async (event) => {
			event.preventDefault();
			const values = new FormData(profileFormNode);
			out.className = "at__result";
			out.textContent = t("accountData.savingProfile", "Saving profile…");
			try {
				const data = await serverWrite("PUT", "/v1/me/profile/", {
					bio: String(values.get("bio") || ""),
					location: String(values.get("location") || ""),
					websiteUrl: String(values.get("websiteUrl") || ""),
					avatarUrl: String(values.get("avatarUrl") || ""),
					links: String(values.get("links") || "")
						.split(/\r?\n/)
						.map((value) => value.trim())
						.filter(Boolean),
					visibility: values.get("private") ? "private" : "public"
				});
				populateProfile(data?.profile);
				out.className = "at__result at__result--ok";
				out.textContent = t("accountData.profileSaved", "Profile saved.");
			} catch (error) {
				out.className = "at__result at__result--err";
				out.textContent = t("accountData.profileSaveFailed", "Profile could not be saved: {msg}", {
					msg: backendErrorExplanation(error)
				});
			}
		});
		$("[data-export]")?.addEventListener("click", async () => {
			out.className = "at__result";
			out.textContent = t("accountData.exporting", "Generating export...");
			try {
				const data = await backendGetJson("/v1/user/export/");
				/** @type {HTMLElement} */ ($("[data-export-box]")).innerHTML = exportTextarea(
					JSON.stringify(data, null, 2)
				);
				out.className = "at__result at__result--ok";
				out.textContent = t("accountData.exportReady", "Export generated.");
			} catch (error) {
				out.className = "at__result at__result--err";
				out.textContent = t("accountData.exportFailed", "Export failed: {msg}", {
					msg: backendErrorExplanation(error)
				});
			}
		});
		$("[data-delete-evolved]")?.addEventListener("click", async () => {
			// eslint-disable-next-line no-alert -- destructive local-data deletion requires explicit user confirmation.
			if (!window.confirm(t("accountData.confirmDelete", "Delete Evolved-local data for this account?"))) return;
			out.className = "at__result";
			out.textContent = t("accountData.deleting", "Deleting Evolved-local data...");
			try {
				const data = await serverWrite("DELETE", "/v1/user/evolved-data/");
				demoStore.clearAll();
				out.className = "at__result at__result--ok";
				out.textContent = t("accountData.deleted", "Deleted Evolved-local data: {count} rows.", {
					count: String(Object.values(data?.deleted || {}).reduce((sum, n) => sum + Number(n || 0), 0))
				});
			} catch (error) {
				out.className = "at__result at__result--err";
				out.textContent = t("accountData.deleteFailed", "Delete failed: {msg}", {
					msg: backendErrorExplanation(error)
				});
			}
		});
	}
	return { title: t("accountData.docTitle", "Preferences - Toolhub"), html, mount };
}
