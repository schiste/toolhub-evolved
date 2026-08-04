// SPDX-License-Identifier: GPL-3.0-or-later
import { t } from "./i18n.js";

/** @param {string} status */
export function claimStatusLabel(status) {
	const labels = /** @type {Record<string, string>} */ ({
		verified: t("claim.statusVerified", "Verified"),
		unverified: t("claim.statusUnverified", "Unverified"),
		failed: t("claim.statusFailed", "Verification failed"),
		stale: t("claim.statusStale", "Needs re-verification"),
		revoked: t("claim.statusRevoked", "Revoked")
	});
	return labels[status] || status;
}

/** @param {string} role */
export function relationshipLabel(role) {
	const labels = /** @type {Record<string, string>} */ ({
		author: t("claim.roleAuthor", "Author"),
		maintainer: t("claim.roleMaintainer", "Maintainer"),
		record_owner: t("claim.roleRecordOwner", "Toolhub record owner"),
		catalog_actor: t("claim.roleCatalogActor", "Catalog contributor")
	});
	return labels[role] || t("claim.roleRelationship", "Relationship");
}

/** @param {string} method */
export function claimMethodLabel(method) {
	const labels = /** @type {Record<string, string>} */ ({
		author_display_name: t("claim.authorTitle", "I am a listed author"),
		toolforge_maintainer: t("claim.toolforgeTitle", "Verify Toolforge maintenance"),
		toolinfo_url_control: t("claim.urlTitle", "Prove control of a toolinfo URL"),
		signed_toolinfo: t("claim.signedTitle", "Verify signed toolinfo"),
		toolhub_write_access: t("claim.recordOwnerTitle", "Toolhub record authority")
	});
	return labels[method] || method;
}
