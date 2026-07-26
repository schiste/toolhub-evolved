// SPDX-License-Identifier: GPL-3.0-or-later
import { $, esc } from "../lib/core/dom.js";
import { backendErrorMessage, backendGetJson } from "../lib/core/api.js";
import { t } from "../lib/core/i18n.js";
import { serverWrite } from "../lib/core/serversync.js";
import { demoStore } from "../lib/core/store.js";
import { button } from "../lib/atoms/button.js";

function exportTextarea(value = "") {
	return `<textarea class="le__input account-data__export" data-export-json rows="12" aria-label="${t("accountData.exportJson", "Evolved data export JSON")}" readonly>${esc(value)}</textarea>`;
}

export function viewAccountSettings() {
	const html = `
	<div class="container page account-data">
		<h1 class="page__title">${t("accountData.title", "Evolved data settings")}</h1>
		<p class="page__intro">${t("accountData.intro", "Export or delete the local Evolved data attached to this Toolhub sign-in. Official Toolhub records, lists, favorites, and crawler registrations are not deleted here.")}</p>

		<section class="panel account-data__section" aria-labelledby="account-export-title">
			<h2 class="panel__title" id="account-export-title">${t("accountData.exportTitle", "Export Evolved data")}</h2>
			<div class="le__actions">${button(t("accountData.exportButton", "Generate export"), { variant: "outline", attrs: "data-export" })}</div>
			<div data-export-box>${exportTextarea()}</div>
		</section>

		<section class="panel account-data__section" aria-labelledby="account-delete-title">
			<h2 class="panel__title" id="account-delete-title">${t("accountData.deleteTitle", "Delete Evolved-local data")}</h2>
			<p class="signin-note">${t("accountData.deleteNote", "This removes local drafts, fallbacks, overlays, local favorites cache, crawler URLs, and local activity rows stored by Toolhub Evolved.")}</p>
			<div class="le__actions">${button(t("accountData.deleteButton", "Delete Evolved-local data"), { variant: "danger", attrs: "data-delete-evolved" })}</div>
		</section>

		<section class="panel account-data__section" aria-labelledby="account-oauth-title">
			<h2 class="panel__title" id="account-oauth-title">${t("accountData.oauthTitle", "Toolhub connection")}</h2>
			<div class="toolpage__actions">
				${button(t("accountData.reconnect", "Reconnect Toolhub OAuth"), { variant: "outline", href: "/oauth/login" })}
				${button(t("accountData.logout", "Log out"), { variant: "outline", href: "/oauth/logout" })}
			</div>
		</section>
		<p class="at__result" data-account-result aria-live="polite"></p>
	</div>`;
	function mount() {
		const out = /** @type {HTMLElement} */ ($("[data-account-result]"));
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
					msg: backendErrorMessage(error)
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
					msg: backendErrorMessage(error)
				});
			}
		});
	}
	return { title: t("accountData.docTitle", "Evolved data settings - Toolhub"), html, mount };
}
