// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { beforeEach, test, vi } from "vitest";

const h = vi.hoisted(() => ({ backendGetJson: vi.fn(), serverWrite: vi.fn() }));

vi.mock("../../public_html/lib/core/api.js", async (importOriginal) => {
	const actual = await importOriginal();
	return { ...actual, backendGetJson: h.backendGetJson };
});
vi.mock("../../public_html/lib/core/serversync.js", async (importOriginal) => {
	const actual = await importOriginal();
	return { ...actual, serverWrite: h.serverWrite };
});

const { closeClaimDrawer, openClaimDrawer } = await import("../../public_html/lib/organisms/claim-drawer.js");
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

function options(claims = []) {
	return {
		claims,
		options: [
			{
				method: "author_display_name",
				relationship: "author",
				available: true,
				authorNames: ["Ada Lovelace"]
			},
			{
				method: "toolhub_write_access",
				relationship: "record_owner",
				available: true,
				automatic: true
			}
		]
	};
}

beforeEach(() => {
	closeClaimDrawer();
	document.querySelector("[data-claim-drawer]")?.remove();
	document.body.className = "";
	vi.clearAllMocks();
});

test("claim drawer creates a listed-author association and explains automatic record authority", async () => {
	h.backendGetJson.mockResolvedValue(options());
	h.serverWrite.mockResolvedValue({ claims: [{ id: 1 }] });
	await openClaimDrawer("ada-tool");
	assert.ok(document.body.classList.contains("claim-drawer-open"));
	assert.ok(document.body.textContent.includes("I am a listed author"));
	assert.ok(document.body.textContent.includes("Associate this name"));
	assert.ok(document.body.textContent.includes("Recorded automatically after a successful official write"));

	const form = document.querySelector('[data-claim-method="author_display_name"]');
	form.dispatchEvent(new SubmitEvent("submit", { bubbles: true, cancelable: true }));
	await tick();
	assert.deepEqual(h.serverWrite.mock.calls[0], [
		"POST",
		"/v1/tools/ada-tool/claims/",
		{ method: "author_display_name", authorName: "Ada Lovelace" }
	]);
	assert.equal(h.backendGetJson.mock.calls.length, 2);
});

test("claim drawer can verify and revoke active proof rows", async () => {
	h.backendGetJson.mockResolvedValue(
		options([
			{
				id: 9,
				toolName: "ada-tool",
				authorName: "Ada",
				requestedRelationship: "maintainer",
				verificationMethod: "toolinfo_url_control",
				verificationStatus: "unverified",
				evidenceUrl: "https://example.org/toolinfo.json"
			}
		])
	);
	h.serverWrite.mockResolvedValue({ ok: true });
	await openClaimDrawer("ada-tool");
	document.querySelector('[data-claim-verify="9"]').click();
	await tick();
	assert.deepEqual(h.serverWrite.mock.calls[0], ["POST", "/v1/claims/9/verify/"]);
	document.querySelector('[data-claim-revoke="9"]').click();
	await tick();
	assert.deepEqual(h.serverWrite.mock.calls[1], ["DELETE", "/v1/claims/9/"]);
});
