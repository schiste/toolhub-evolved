// SPDX-License-Identifier: GPL-3.0-or-later
import { $, esc } from "../lib/core/dom.js";
import { backendErrorMessage, backendGetJson } from "../lib/core/api.js";
import { t } from "../lib/core/i18n.js";
import { serverWrite } from "../lib/core/serversync.js";
import { demoStore } from "../lib/core/store.js";
import { button } from "../lib/atoms/button.js";
import { logoutForm } from "../lib/organisms/account.js";
import { accountSection, accountWorkbenchPage } from "../lib/organisms/account-workbench.js";

function exportTextarea(value = "") {
	return `<textarea class="le__input account-data__export" data-export-json rows="12" aria-label="${t("accountData.exportJson", "Evolved data export JSON")}" readonly>${esc(value)}</textarea>`;
}

export function viewAccountSettings() {
	const html = accountWorkbenchPage({
		active: "data",
		title: t("accountData.title", "Evolved data settings"),
		intro: t(
			"accountData.intro",
			"Export or delete the local Evolved data attached to this Toolhub sign-in. Official Toolhub records, lists, favorites, and crawler registrations are not deleted here."
		),
		source: t("accountData.source", "Evolved-local data"),
		metrics: [
			{
				value: t("accountData.exportMetricValue", "JSON"),
				label: t("accountData.exportMetric", "Export format"),
				detail: t("accountData.exportMetricDetail", "Portable account snapshot")
			},
			{
				value: t("accountData.deleteMetricValue", "Local only"),
				label: t("accountData.deleteMetric", "Deletion scope"),
				detail: t("accountData.deleteMetricDetail", "Official Toolhub records stay intact")
			}
		],
		body: `
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
