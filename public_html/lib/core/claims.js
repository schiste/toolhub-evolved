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
		maintainer: t("claim.roleMaintainer", "Maintainer")
	});
	return labels[role] || t("claim.roleRelationship", "Relationship");
}

/** @param {string} method */
export function claimMethodLabel(method) {
	const labels = /** @type {Record<string, string>} */ ({
		author_display_name: t("claim.authorTitle", "I am a listed author"),
		toolforge_maintainer: t("claim.toolforgeTitle", "Verify Toolforge maintenance"),
		toolinfo_url_control: t("claim.urlTitle", "Prove control of a toolinfo URL"),
		signed_toolinfo: t("claim.signedTitle", "Verify signed toolinfo")
	});
	return labels[method] || method;
}

/** @param {any} relationship */
export function primaryRelationshipEvidence(relationship) {
	const evidence = Array.isArray(relationship?.evidence) ? relationship.evidence : [];
	const matchingStatus = evidence.find((/** @type {any} */ item) => item?.status === relationship?.status);
	return matchingStatus || evidence[0] || null;
}

/** @param {string} method */
export function evidenceMethodLabel(method) {
	const labels = /** @type {Record<string, string>} */ ({
		toolhub_author_metadata: t("peopleEvidence.methodToolhubAuthor", "Toolhub author metadata"),
		toolforge_maintainer: t("peopleEvidence.methodToolforgeMaintainer", "Toolforge Toolsadmin maintainer"),
		signed_toolinfo: t("peopleEvidence.methodSignedToolinfo", "Signed toolinfo"),
		toolinfo_url_control: t("peopleEvidence.methodToolinfoControl", "Toolinfo URL control"),
		author_display_name: t("peopleEvidence.methodDisplayName", "Author display-name match")
	});
	return labels[method] || method || t("peopleEvidence.methodUnknown", "Unspecified method");
}

/** @param {string} source */
export function evidenceSourceLabel(source) {
	const labels = /** @type {Record<string, string>} */ ({
		toolhub_author_metadata: t("peopleEvidence.sourceToolhubAuthor", "Toolhub author field"),
		toolforge_toolsadmin: t("peopleEvidence.sourceToolsadmin", "Toolforge Toolsadmin"),
		evolved_author_claim: t("peopleEvidence.sourceClaim", "Toolhub Evolved claim")
	});
	return labels[source] || source || t("peopleEvidence.sourceUnknown", "Unknown source");
}

/** @param {string} quality */
export function identityQualityLabel(quality) {
	const labels = /** @type {Record<string, string>} */ ({
		stable: t("peopleEvidence.identityStable", "Identity backed by a stable account ID"),
		stable_id: t("peopleEvidence.identityStable", "Identity backed by a stable account ID"),
		handle: t("peopleEvidence.identityHandle", "Identity backed by a public account handle")
	});
	return labels[quality] || t("peopleEvidence.identityIncomplete", "Identity evidence incomplete");
}

/**
 * Describe precisely what one public relationship proves.
 * @param {any} relationship
 * @returns {{ label: string, tone: "verified" | "canonical" | "unverified" | "stale" | "failed" }}
 */
export function relationshipTrust(relationship) {
	const role = relationship?.type || "";
	const status = relationship?.status || "unverified";
	const evidence = primaryRelationshipEvidence(relationship);
	const method = evidence?.method || "";

	if (status === "stale") {
		return {
			label: t("peopleEvidence.previousVerification", "Previous verification—renewal needed"),
			tone: "stale"
		};
	}
	if (status === "failed" || status === "revoked") {
		return {
			label:
				status === "revoked"
					? t("peopleEvidence.revoked", "Relationship verification revoked")
					: t("peopleEvidence.failed", "Relationship verification failed"),
			tone: "failed"
		};
	}
	if (status === "verified") {
		if (role === "maintainer" && method === "toolforge_maintainer") {
			return {
				label: t("peopleEvidence.verifiedToolforgeMaintainer", "Verified Toolforge maintainer"),
				tone: "verified"
			};
		}
		if (role === "maintainer" && ["signed_toolinfo", "toolinfo_url_control"].includes(method)) {
			return {
				label: t("peopleEvidence.verifiedMaintainerControl", "Verified maintainer control"),
				tone: "verified"
			};
		}
		return {
			label: t(
				"peopleEvidence.verifiedRelationship",
				"Verified $1 relationship",
				relationshipLabel(role).toLocaleLowerCase()
			),
			tone: "verified"
		};
	}
	if (role === "author" && (relationship?.toolhubCanonical || method === "toolhub_author_metadata")) {
		return { label: t("peopleEvidence.listedAuthor", "Listed author"), tone: "canonical" };
	}
	return { label: t("peopleEvidence.unverifiedAttribution", "Unverified attribution"), tone: "unverified" };
}
