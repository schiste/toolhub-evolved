// SPDX-License-Identifier: GPL-3.0-or-later
import {
	claimStatusLabel,
	evidenceMethodLabel,
	evidenceSourceLabel,
	identityQualityLabel,
	relationshipLabel,
	relationshipTrust
} from "../core/claims.js";
import { esc } from "../core/dom.js";
import { t, timeTag } from "../core/i18n.js";

/** @param {any} evidence */
function evidenceRow(evidence) {
	const checked = evidence?.checkedAt
		? `<span>${t("peopleEvidence.lastChecked", "Last checked")} ${timeTag(evidence.checkedAt)}</span>`
		: `<span>${t("peopleEvidence.checkDateUnknown", "Check date unavailable")}</span>`;
	const expires = evidence?.expiresAt
		? `<span>${t("peopleEvidence.validUntil", "Valid until")} ${timeTag(evidence.expiresAt)}</span>`
		: "";
	return `<li>
		<strong>${esc(evidenceSourceLabel(evidence?.source || ""))}</strong>
		<span>${esc(evidenceMethodLabel(evidence?.method || ""))}</span>
		${checked}${expires}
	</li>`;
}

/** @param {any} relationship */
export function relationshipTrustMarkup(relationship) {
	const presentation = relationshipTrust(relationship);
	const evidence = Array.isArray(relationship?.evidence) ? relationship.evidence : [];
	const evidenceCount = Number(relationship?.evidenceCount) || evidence.length;
	const confidence = Math.max(0, Math.min(100, Number(relationship?.confidence) || 0));
	const identityBasis = evidence.find((/** @type {any} */ item) => item?.identityBasis)?.identityBasis || "";
	const authority = relationship?.toolhubCanonical
		? t("peopleEvidence.canonicalToolhub", "Canonical catalog source: Toolhub")
		: t("peopleEvidence.evolvedAuthority", "Relationship evidence maintained by Toolhub Evolved");
	const evidenceList =
		evidence.length > 0
			? `<ul class="relationship-trust__evidence">${evidence.map((/** @type {any} */ item) => evidenceRow(item)).join("")}</ul>`
			: `<p class="relationship-trust__empty">${t("peopleEvidence.noPublicEvidence", "No public evidence details are available.")}</p>`;

	return `<div class="relationship-trust relationship-trust--${presentation.tone}">
		<div class="relationship-trust__head">
			<span class="relationship-trust__badge">${esc(presentation.label)}</span>
			<span class="relationship-trust__role">${esc(relationshipLabel(relationship?.type || ""))}</span>
		</div>
		<details class="relationship-trust__details">
			<summary>${t("peopleEvidence.disclosure", "Evidence and verification details")}</summary>
			<dl class="relationship-trust__facts">
				<div><dt>${t("peopleEvidence.status", "Status")}</dt><dd>${esc(claimStatusLabel(relationship?.status || "unverified"))}</dd></div>
				<div><dt>${t("peopleEvidence.confidence", "Confidence")}</dt><dd>${confidence}/100</dd></div>
				<div><dt>${t("peopleEvidence.observations", "Evidence observations")}</dt><dd>${evidenceCount}</dd></div>
				<div><dt>${t("peopleEvidence.authority", "Authority")}</dt><dd>${esc(authority)}</dd></div>
				${identityBasis ? `<div><dt>${t("peopleEvidence.identityBasis", "Identity basis")}</dt><dd>${esc(identityQualityLabel(identityBasis))}</dd></div>` : ""}
			</dl>
			${evidenceList}
		</details>
	</div>`;
}
