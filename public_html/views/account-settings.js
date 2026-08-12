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

/** @param {string} provider */
function accountProviderLabel(provider) {
	return (
		{
			toolhub: t("accountData.providerToolhub", "Toolhub account"),
			wikimedia: t("accountData.providerWikimedia", "Wikimedia account"),
			toolforge: t("accountData.providerToolforge", "Toolforge developer account")
		}[provider] || provider
	);
}

/** @param {any} state */
function accountLinksHTML(state) {
	const verified = /** @type {any[]} */ (Array.isArray(state?.bindings) ? state.bindings : []).filter(
		(/** @type {any} */ binding) => binding.status === "verified"
	);
	const candidates = /** @type {any[]} */ (Array.isArray(state?.candidates) ? state.candidates : []);
	const connected =
		verified.length > 0
			? `<ul class="account-links__list">${verified
					.map((/** @type {any} */ binding) => {
						const name = binding.username || binding.externalId;
						const tools =
							binding.provider === "toolforge"
								? ` · ${t("accountData.linkedToolCount", "$1 Toolforge tools", String(binding.toolCount || 0))}`
								: "";
						return `<li><strong>${esc(accountProviderLabel(binding.provider))}</strong><span><span dir="auto">${esc(name)}</span>${esc(tools)}</span></li>`;
					})
					.join("")}</ul>`
			: `<p class="empty">${t("accountData.noLinkedAccounts", "No external accounts are linked yet.")}</p>`;
	const candidateOptions = candidates
		.map((/** @type {any} */ candidate) => `<option value="${esc(candidate.username || "")}"></option>`)
		.join("");
	const profileUrl = safeUrl(state?.upstreamRepair?.profileUrl);
	const sshKeysUrl = safeUrl(state?.upstreamRepair?.sshKeysUrl);
	const unavailable = state?.proofMethods?.toolforgeSshSignature === false;
	return `${connected}
		<div class="account-links__connect">
			<h3>${t("accountData.connectToolforge", "Connect another Toolforge account")}</h3>
			<p class="signin-note">${t(
				"accountData.connectToolforgeIntro",
				"Enter each developer username you control. One proof reconnects all of that account's current and future Toolforge tool memberships."
			)}</p>
			${
				candidates.length > 0
					? `<p class="signin-note">${t("accountData.suggestedAccounts", "Suggested from an exact cross-system username match: $1", candidates.map((/** @type {any} */ candidate) => candidate.username).join(", "))}</p>`
					: ""
			}
			<form class="account-links__start" data-account-link-start>
				<label class="le__label" for="toolforge-account-username">${t("accountData.toolforgeUsername", "Toolforge developer username")}</label>
				<div class="account-links__start-row">
					<input class="le__input" id="toolforge-account-username" name="username" list="toolforge-account-candidates" required autocomplete="username" />
					<datalist id="toolforge-account-candidates">${candidateOptions}</datalist>
					${button(t("accountData.startProof", "Start secure proof"), { variant: "primary", type: "submit", attrs: unavailable ? "disabled" : "" })}
				</div>
			</form>
			${
				unavailable
					? `<p class="at__result at__result--err">${t("accountData.proofUnavailable", "SSH account proof is temporarily unavailable.")}</p>`
					: ""
			}
			<p class="signin-note">${t("accountData.privateKeySafety", "Evolved never receives your private key. You sign a one-time challenge locally with OpenSSH.")}</p>
			${
				profileUrl || sshKeysUrl
					? `<p class="signin-note">${t("accountData.upstreamRepair", "Need to reconnect Wikimedia identity or add an SSH key upstream?")} ${profileUrl ? `<a href="${profileUrl}" target="_blank" rel="noopener">${t("accountData.toolsadminProfile", "Toolsadmin profile")}</a>` : ""}${profileUrl && sshKeysUrl ? " · " : ""}${sshKeysUrl ? `<a href="${sshKeysUrl}" target="_blank" rel="noopener">${t("accountData.toolsadminKeys", "SSH keys")}</a>` : ""}</p>`
					: ""
			}
			<div data-account-link-challenge hidden></div>
			<p class="at__result" data-account-link-result aria-live="polite"></p>
		</div>`;
}

/** @param {any} challenge */
function accountChallengeHTML(challenge) {
	return `<div class="account-links__challenge">
		<h3>${t("accountData.proveControl", "Prove control of $1", challenge.username || "")}</h3>
		<ol>
			<li>${t("accountData.runCommand", "Run this command in a terminal on a computer that has your Toolforge SSH private key:")}
				<textarea class="le__input account-links__command" rows="7" readonly aria-label="${esc(t("accountData.signingCommand", "OpenSSH signing command"))}" data-account-link-command>${esc(challenge.command || "")}</textarea>
				${button(t("accountData.copyCommand", "Copy command"), { variant: "outline", attrs: "data-account-link-copy" })}
			</li>
			<li>${t("accountData.pasteSignature", "Paste the complete SSH signature printed by the command:")}</li>
		</ol>
		<form data-account-link-verify>
			<label class="le__label" for="toolforge-account-signature">${t("accountData.sshSignature", "SSH signature")}</label>
			<textarea class="le__input" id="toolforge-account-signature" name="signature" rows="8" required spellcheck="false" placeholder="-----BEGIN SSH SIGNATURE-----"></textarea>
			${button(t("accountData.verifyAccount", "Verify and connect account"), { variant: "primary", type: "submit" })}
		</form>
	</div>`;
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
				id: "account-links-title",
				title: t("accountData.accountLinksTitle", "Connected identities"),
				intro: t(
					"accountData.accountLinksIntro",
					"Stable account links let Evolved reconcile public identities and Toolforge maintainer relationships without requiring every person to sign in."
				),
				body: `<div data-account-links><p class="signin-note">${t("accountData.accountLinksLoading", "Loading connected identities…")}</p></div>`
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
		async function loadAccountLinks() {
			try {
				const state = await backendGetJson("/v1/me/account-links/");
				const target = $("[data-account-links]");
				if (!target) return;
				target.innerHTML = accountLinksHTML(state);
				const result = /** @type {HTMLElement | null} */ (target.querySelector("[data-account-link-result]"));
				const startForm = /** @type {HTMLFormElement | null} */ (
					target.querySelector("[data-account-link-start]")
				);
				startForm?.addEventListener("submit", async (event) => {
					event.preventDefault();
					const username = String(new FormData(startForm).get("username") || "").trim();
					if (result) {
						result.className = "at__result";
						result.textContent = t("accountData.startingProof", "Preparing secure proof…");
					}
					try {
						const challenge = await serverWrite("POST", "/v1/me/account-links/toolforge/challenges/", {
							username
						});
						const challengeNode = /** @type {HTMLElement | null} */ (
							target.querySelector("[data-account-link-challenge]")
						);
						if (!challengeNode) return;
						challengeNode.hidden = false;
						challengeNode.innerHTML = accountChallengeHTML(challenge);
						challengeNode.querySelector("[data-account-link-copy]")?.addEventListener("click", async () => {
							const command = /** @type {HTMLTextAreaElement | null} */ (
								challengeNode.querySelector("[data-account-link-command]")
							)?.value;
							if (command && navigator.clipboard) await navigator.clipboard.writeText(command);
						});
						const verifyForm = /** @type {HTMLFormElement | null} */ (
							challengeNode.querySelector("[data-account-link-verify]")
						);
						verifyForm?.addEventListener("submit", async (verifyEvent) => {
							verifyEvent.preventDefault();
							const signature = String(new FormData(verifyForm).get("signature") || "");
							if (result) result.textContent = t("accountData.verifyingAccount", "Verifying account…");
							try {
								await serverWrite("POST", "/v1/me/account-links/toolforge/verify/", {
									challengeId: challenge.challengeId,
									challenge: challenge.challenge,
									signature
								});
								await loadAccountLinks();
								out.className = "at__result at__result--ok";
								out.textContent = t(
									"accountData.accountConnected",
									"Toolforge account connected. Its maintainer relationships are now reconciled."
								);
							} catch (error) {
								if (result) {
									result.className = "at__result at__result--err";
									result.textContent = backendErrorExplanation(error);
								}
							}
						});
						if (result) {
							result.textContent = t(
								"accountData.challengeReady",
								"Challenge ready. It expires in 10 minutes."
							);
						}
					} catch (error) {
						if (result) {
							result.className = "at__result at__result--err";
							result.textContent = backendErrorExplanation(error);
						}
					}
				});
			} catch (error) {
				const currentTarget = $("[data-account-links]");
				if (currentTarget) {
					currentTarget.innerHTML = `<p class="at__result at__result--err">${esc(backendErrorExplanation(error))}</p>`;
				}
			}
		}
		window.setTimeout(() => {
			loadAccountLinks();
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
				out.textContent = t(
					"accountData.profileSaveFailed",
					"Profile could not be saved: $1",
					backendErrorExplanation(error)
				);
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
				out.textContent = t("accountData.exportFailed", "Export failed: $1", backendErrorExplanation(error));
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
				out.textContent = t(
					"accountData.deleted",
					"Deleted Evolved-local data: $1 rows.",
					String(Object.values(data?.deleted || {}).reduce((sum, n) => sum + Number(n || 0), 0))
				);
			} catch (error) {
				out.className = "at__result at__result--err";
				out.textContent = t("accountData.deleteFailed", "Delete failed: $1", backendErrorExplanation(error));
			}
		});
	}
	return { title: t("accountData.docTitle", "Preferences - Toolhub"), html, mount };
}
