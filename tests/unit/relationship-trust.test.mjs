// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test } from "vitest";
import {
	evidenceMethodLabel,
	evidenceSourceLabel,
	primaryRelationshipEvidence,
	relationshipTrust
} from "../../public_html/lib/core/claims.js";

test("relationship trust distinguishes canonical authorship from verification", () => {
	const presentation = relationshipTrust({
		type: "author",
		status: "unverified",
		toolhubCanonical: true,
		evidence: [{ method: "toolhub_author_metadata", status: "unverified" }]
	});

	assert.deepEqual(presentation, { label: "Listed author", tone: "canonical" });
});

test("relationship trust names the authority verified by each method", () => {
	assert.equal(
		relationshipTrust({
			type: "maintainer",
			status: "verified",
			evidence: [{ method: "toolforge_maintainer", status: "verified" }]
		}).label,
		"Verified Toolforge maintainer"
	);
	assert.equal(
		relationshipTrust({
			type: "maintainer",
			status: "verified",
			evidence: [{ method: "signed_toolinfo", status: "verified" }]
		}).label,
		"Verified maintainer control"
	);
});

test("stale status takes priority over an earlier verified observation", () => {
	const relationship = {
		type: "maintainer",
		status: "stale",
		evidence: [{ method: "toolforge_maintainer", status: "verified" }]
	};

	assert.deepEqual(relationshipTrust(relationship), {
		label: "Previous verification—renewal needed",
		tone: "stale"
	});
});

test("relationship trust keeps unverified and failed claims explicit", () => {
	assert.equal(relationshipTrust({ type: "maintainer", status: "unverified" }).label, "Unverified attribution");
	assert.equal(relationshipTrust({ type: "maintainer", status: "failed" }).label, "Relationship verification failed");
	assert.equal(
		relationshipTrust({ type: "maintainer", status: "revoked" }).label,
		"Relationship verification revoked"
	);
});

test("primary evidence prefers the observation supporting the current status", () => {
	const verified = { method: "signed_toolinfo", status: "verified" };
	assert.equal(
		primaryRelationshipEvidence({
			status: "verified",
			evidence: [{ method: "author_display_name", status: "unverified" }, verified]
		}),
		verified
	);
	assert.equal(primaryRelationshipEvidence({ evidence: [] }), null);
});

test("evidence labels translate public provenance identifiers", () => {
	assert.equal(evidenceMethodLabel("toolforge_maintainer"), "Toolforge Toolsadmin maintainer");
	assert.equal(evidenceMethodLabel(""), "Unspecified method");
	assert.equal(evidenceSourceLabel("toolforge_toolsadmin"), "Toolforge Toolsadmin");
	assert.equal(evidenceSourceLabel(""), "Unknown source");
});
