// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { test } from "vitest";
import {
	fieldProvenance,
	reviewBadge,
	syncBadge,
	syncState,
	syncStatusPanel,
	validationErrorMessages
} from "../../public_html/lib/molecules/sync-status.js";

test("syncBadge renders canonical status labels", () => {
	assert.equal(
		syncBadge({ syncStatus: "official" }),
		'<span class="sync-badge sync-badge--official">Published to Toolhub</span>'
	);
	assert.equal(
		syncBadge({ syncStatus: "local_fallback", syncLabel: "old label" }),
		'<span class="sync-badge sync-badge--local-fallback">Saved locally after Toolhub rejected it</span>'
	);
});

test("fieldProvenance includes retry availability for fallback records", () => {
	const html = fieldProvenance("Title", { syncStatus: "local_fallback" });
	assert.ok(html.includes("Title"));
	assert.ok(html.includes("Saved locally after Toolhub rejected it"));
	assert.ok(html.includes("Retry available"));
});

test("reviewBadge renders public review states", () => {
	assert.equal(reviewBadge("pending"), '<span class="sync-badge sync-badge--review-pending">Pending review</span>');
	assert.equal(reviewBadge("approved"), '<span class="sync-badge sync-badge--review-approved">Reviewed</span>');
	assert.equal(
		reviewBadge("rejected"),
		'<span class="sync-badge sync-badge--review-rejected">Review rejected</span>'
	);
	assert.equal(reviewBadge("unknown"), "");
});

test("syncStatusPanel renders retry/discard actions and validation details", () => {
	const html = syncStatusPanel(
		{
			syncStatus: "local_fallback",
			lastError: "title rejected",
			validationErrors: [{ field: "title", message: "Too short" }]
		},
		{ retryAttrs: "data-retry", discardAttrs: "data-discard" }
	);
	assert.ok(html.includes("Write status"));
	assert.ok(html.includes("Toolhub response:"));
	assert.ok(html.includes("title rejected"));
	assert.ok(html.includes("title: Too short"));
	assert.ok(html.includes("data-retry"));
	assert.ok(html.includes("data-discard"));
});

test("syncStatusPanel explains permission failures and accepts contextual guidance", () => {
	const permission = syncStatusPanel({
		syncStatus: "local_fallback",
		lastError: "You do not have permission",
		toolhubResponse: { status_code: 403, code: 4005 }
	});
	assert.ok(permission.includes("What this means:"));
	assert.ok(permission.includes("account is not allowed to perform this action"));
	assert.ok(permission.includes("HTTP 403"));
	assert.ok(permission.includes("Toolhub code 4005"));

	const crawler = syncStatusPanel(
		{ syncStatus: "local_fallback", lastError: "permission denied" },
		{ guidance: "Update toolinfo.json and wait for the next crawl." }
	);
	assert.ok(crawler.includes("Update toolinfo.json and wait for the next crawl."));
});

test("crawler-owned fallback does not advertise a retry", () => {
	const html = syncStatusPanel(
		{ syncStatus: "local_fallback", lastError: "permission denied", origin: "crawler" },
		{ retryAttrs: "data-retry" }
	);
	assert.equal(syncState({ syncStatus: "local_fallback", origin: "crawler" }).retryAvailable, false);
	assert.equal(html.includes("Retry available"), false);
	assert.equal(html.includes("data-retry"), false);
});

test("validationErrorMessages accepts mixed backend shapes", () => {
	assert.deepEqual(validationErrorMessages(["plain", { field: "url", detail: "Invalid" }, { title: ["Missing"] }]), [
		"plain",
		"url: Invalid",
		"title: Missing"
	]);
	assert.deepEqual(validationErrorMessages(7), ["7"]);
	assert.deepEqual(validationErrorMessages({ message: "General failure" }), ["General failure"]);
	assert.deepEqual(validationErrorMessages({ tool: { title: "Missing" } }), ["tool: title: Missing"]);
	const state = syncState({ syncStatus: "sync_error", validationErrors: { name: "Required" } });
	assert.equal(state.retryAvailable, true);
	assert.deepEqual(state.validationErrors, ["name: Required"]);
	assert.equal(syncState({ syncStatus: "unknown" }).label, "Saved locally");
});
