// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { beforeEach, test, vi } from "vitest";

const h = vi.hoisted(() => ({
	backendGetJson: vi.fn(),
	paginate: vi.fn(),
	serverWrite: vi.fn(),
	clearAll: vi.fn()
}));

vi.mock("../../public_html/lib/core/api.js", async (orig) => {
	const actual = await orig();
	return { ...actual, backendGetJson: h.backendGetJson, paginate: h.paginate };
});
vi.mock("../../public_html/lib/core/serversync.js", async (orig) => {
	const actual = await orig();
	return { ...actual, serverWrite: h.serverWrite };
});
vi.mock("../../public_html/lib/core/store.js", async (orig) => {
	const actual = await orig();
	return { ...actual, demoStore: { ...actual.demoStore, clearAll: h.clearAll } };
});

const { setServerUser } = await import("../../public_html/lib/core/session.js");
const { viewAccountSettings, viewDeveloperSettings, viewMyTools } = await import("../../public_html/views/account.js");

beforeEach(() => {
	vi.clearAllMocks();
	document.body.innerHTML = "";
	window.confirm = vi.fn(() => true);
	setServerUser("Ada Lovelace");
});

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

test("viewAccountSettings renders export, delete, and OAuth controls", () => {
	const r = viewAccountSettings();
	assert.equal(r.title, "Evolved data settings - Toolhub");
	assert.ok(r.html.includes("Generate export"));
	assert.ok(r.html.includes("Delete Evolved-local data"));
	assert.ok(r.html.includes('href="/oauth/login"'));
	assert.ok(r.html.includes('method="post" action="/oauth/logout"'));
});

test("viewDeveloperSettings renders the Toolhub developer hub and profile links", () => {
	const r = viewDeveloperSettings();
	assert.equal(r.title, "Developer settings - Toolhub");
	assert.ok(r.html.includes("Official Toolhub developer settings"));
	assert.ok(r.html.includes("Signed toolinfo authorship"));
	assert.ok(r.html.includes("toolinfo schema"));
	assert.ok(r.html.includes("toolinfo.json reference"));
	assert.ok(r.html.includes("&quot;_schema&quot;: &quot;/toolinfo/1.2.2&quot;"));
	assert.ok(r.html.includes("current.yaml"));
	assert.ok(r.html.includes("Register key"));
	assert.ok(r.html.includes("Build payload"));
	assert.ok(r.html.includes('href="/my-tools"'));
	assert.ok(r.html.includes('href="/api-docs"'));
	assert.ok(r.html.includes("Review official Toolhub tools and Evolved authorship verification"));
	assert.ok(r.html.includes("My apps"));
	assert.ok(
		r.html.includes('href="https://toolhub.wikimedia.org/api/oauth/applications/?user__username=Ada%20Lovelace"')
	);
	assert.ok(!r.html.includes('href="/my-apps"'));
	assert.ok(r.html.includes("API token"));
	assert.ok(r.html.includes("Authorized apps"));
	assert.ok(r.html.includes('href="https://toolhub.wikimedia.org/developer-settings"'));
});

test("developer settings loads registered author keys", async () => {
	h.backendGetJson.mockResolvedValue({
		keys: [{ keyId: "release-2026", algorithm: "ed25519", fingerprint: "SHA256:abc", revokedAt: "" }]
	});
	const r = viewDeveloperSettings();
	document.body.innerHTML = r.html;
	r.mount();
	await tick();
	assert.deepEqual(h.backendGetJson.mock.calls[0], ["/v1/author-keys/"]);
	assert.ok(document.body.innerHTML.includes("release-2026"));
	assert.ok(document.body.innerHTML.includes("SHA256:abc"));
	assert.ok(document.body.innerHTML.includes("Active"));
	assert.equal(document.querySelector("[data-sign-key]").value, "release-2026");
});

test("developer settings registers and revokes author keys", async () => {
	h.backendGetJson.mockResolvedValue({
		keys: [{ keyId: "release-2026", algorithm: "ed25519", fingerprint: "SHA256:abc", revokedAt: "" }]
	});
	h.serverWrite.mockResolvedValue({ ok: true });
	const r = viewDeveloperSettings();
	document.body.innerHTML = r.html;
	r.mount();
	await tick();
	document.querySelector("#author-key-id").value = "next";
	document.querySelector("#author-public-key").value = "MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTE=";
	document.querySelector("[data-author-key-form]").dispatchEvent(new Event("submit", { bubbles: true }));
	await tick();
	assert.deepEqual(h.serverWrite.mock.calls[0], [
		"POST",
		"/v1/author-keys/",
		{ keyId: "next", publicKey: "MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTE=" }
	]);
	document.querySelector("[data-author-key-revoke]").click();
	await tick();
	assert.deepEqual(h.serverWrite.mock.calls[1], ["DELETE", "/v1/author-keys/release-2026/"]);
});

test("developer settings builds a canonical signing payload", async () => {
	h.backendGetJson.mockResolvedValue({
		keys: [{ keyId: "release-2026", algorithm: "ed25519", fingerprint: "SHA256:abc", revokedAt: "" }]
	});
	h.serverWrite.mockResolvedValue({
		canonicalPayload: '{"name":"ada-tool"}',
		canonicalPayloadBase64: "eyJuYW1lIjoiYWRhLXRvb2wifQ==",
		signatureMetadata: { algorithm: "ed25519", key_id: "release-2026", signature: "<base64 signature>" },
		signedToolinfoPreview: {
			name: "ada-tool",
			x_toolhub_evolved_signature: {
				algorithm: "ed25519",
				key_id: "release-2026",
				signature: "<base64 signature>"
			}
		}
	});
	const r = viewDeveloperSettings();
	document.body.innerHTML = r.html;
	r.mount();
	await tick();
	document.querySelector("#signature-toolinfo").value = '{"name":"ada-tool"}';
	document.querySelector("[data-signing-form]").dispatchEvent(new Event("submit", { bubbles: true }));
	await tick();
	assert.deepEqual(h.serverWrite.mock.calls[0], [
		"POST",
		"/v1/toolinfo/signing-payload/",
		{ keyId: "release-2026", toolinfo: { name: "ada-tool" } }
	]);
	assert.equal(document.querySelector("#signature-canonical").value, '{"name":"ada-tool"}');
	assert.ok(document.querySelector("#signature-metadata").value.includes("release-2026"));
	assert.equal(document.querySelector("[data-signature-output]").hidden, false);
});

test("developer settings reports invalid signing JSON", async () => {
	h.backendGetJson.mockResolvedValue({ keys: [] });
	const r = viewDeveloperSettings();
	document.body.innerHTML = r.html;
	r.mount();
	await tick();
	document.querySelector("#signature-toolinfo").value = "{";
	document.querySelector("[data-signing-form]").dispatchEvent(new Event("submit", { bubbles: true }));
	await tick();
	assert.equal(h.serverWrite.mock.calls.length, 0);
	assert.equal(document.querySelector("[data-developer-result]").textContent, "Toolinfo must be valid JSON.");
});

test("viewMyTools lists official Toolhub tools owned by the signed-in user", async () => {
	h.backendGetJson.mockResolvedValue({
		verified: [
			{
				tool: {
					name: "ada-tool",
					title: "Ada Tool",
					url: "https://example.org/ada",
					author: [{ name: "Ada Lovelace" }],
					tool_type: "web app",
					modified_date: "2026-01-01T00:00:00Z"
				},
				claims: [
					{
						verificationMethod: "toolforge_maintainer",
						verificationStatus: "verified",
						isVerified: true
					},
					{
						verificationMethod: "toolhub_write_access",
						verificationStatus: "verified",
						isVerified: true
					},
					{
						verificationMethod: "signed_toolinfo",
						verificationStatus: "verified",
						isVerified: true
					}
				]
			}
		],
		possible: [
			{
				tool: {
					name: "ada-developer-tool",
					title: "Ada Developer Tool",
					url: "",
					author: [{ name: "Different Display Name", developer_username: "Ada Lovelace" }],
					tool_type: null,
					modified_date: null
				},
				claims: [
					{
						verificationMethod: "author_display_name",
						verificationStatus: "unverified",
						isVerified: false
					}
				]
			}
		]
	});
	const r = await viewMyTools();
	assert.equal(r.title, "My tools - Toolhub");
	assert.deepEqual(h.backendGetJson.mock.calls[0], ["/v1/me/tools/"]);
	assert.equal(h.paginate.mock.calls.length, 0);
	assert.ok(r.html.includes("Ada Tool"));
	assert.ok(r.html.includes("Ada Developer Tool"));
	assert.ok(r.html.includes("ada-tool"));
	assert.ok(r.html.includes("web app"));
	assert.ok(r.html.includes("https://example.org/ada"));
	assert.ok(r.html.includes("Verified: Toolforge maintainer"));
	assert.ok(r.html.includes("Verified: Toolhub write access"));
	assert.ok(r.html.includes("Verified: signed toolinfo"));
	assert.ok(r.html.includes("Unverified author name"));
	assert.ok(r.html.includes("Official Toolhub data + Evolved verification"));
	assert.ok(
		r.html.includes(
			"Verification is per tool: a verified author claim on one tool does not verify the same author name everywhere."
		)
	);
	assert.ok(!r.html.includes("Possible match"));
	assert.ok(r.html.includes("2 tools"));
});

test("viewMyTools renders an empty state", async () => {
	h.backendGetJson.mockResolvedValue({ verified: [], possible: [] });
	const r = await viewMyTools();
	assert.ok(r.html.includes("No Toolhub tools list this account as an author or maintainer."));
	assert.ok(r.html.includes("0 tools"));
});

test("viewMyTools reports load failures", async () => {
	h.backendGetJson.mockRejectedValue(new Error("offline"));
	const r = await viewMyTools();
	assert.ok(r.html.includes("Unable to load your Toolhub tools right now."));
});

test("export action renders the JSON export", async () => {
	h.backendGetJson.mockResolvedValue({ user: { username: "Ada" }, overlay: { favorites: ["tool-a"] } });
	const r = viewAccountSettings();
	document.body.innerHTML = r.html;
	r.mount();
	document.querySelector("[data-export]").click();
	await tick();
	assert.deepEqual(h.backendGetJson.mock.calls[0], ["/v1/user/export/"]);
	const text = document.querySelector("[data-export-json]").value;
	assert.ok(text.includes('"favorites": ['));
	assert.ok(document.querySelector("[data-account-result]").textContent.includes("Export generated"));
});

test("export action reports backend failures", async () => {
	h.backendGetJson.mockRejectedValue(new Error("offline"));
	const r = viewAccountSettings();
	document.body.innerHTML = r.html;
	r.mount();
	document.querySelector("[data-export]").click();
	await tick();
	const out = document.querySelector("[data-account-result]");
	assert.equal(out.className, "at__result at__result--err");
	assert.equal(out.textContent, "Export failed: offline");
});

test("delete action calls the server and clears the local cache", async () => {
	h.serverWrite.mockResolvedValue({ deleted: { favorites: 1, lists: 2 } });
	const r = viewAccountSettings();
	document.body.innerHTML = r.html;
	r.mount();
	document.querySelector("[data-delete-evolved]").click();
	await tick();
	assert.deepEqual(h.serverWrite.mock.calls[0], ["DELETE", "/v1/user/evolved-data/"]);
	assert.equal(h.clearAll.mock.calls.length, 1);
	assert.ok(document.querySelector("[data-account-result]").textContent.includes("3 rows"));
});

test("delete action handles an empty deletion summary", async () => {
	h.serverWrite.mockResolvedValue({});
	const r = viewAccountSettings();
	document.body.innerHTML = r.html;
	r.mount();
	document.querySelector("[data-delete-evolved]").click();
	await tick();
	assert.equal(h.clearAll.mock.calls.length, 1);
	assert.ok(document.querySelector("[data-account-result]").textContent.includes("0 rows"));
});

test("delete action treats null row counts as zero", async () => {
	h.serverWrite.mockResolvedValue({ deleted: { favorites: null } });
	const r = viewAccountSettings();
	document.body.innerHTML = r.html;
	r.mount();
	document.querySelector("[data-delete-evolved]").click();
	await tick();
	assert.equal(h.clearAll.mock.calls.length, 1);
	assert.ok(document.querySelector("[data-account-result]").textContent.includes("0 rows"));
});

test("delete action reports backend failures without clearing local cache", async () => {
	h.serverWrite.mockRejectedValue(new Error("permission denied"));
	const r = viewAccountSettings();
	document.body.innerHTML = r.html;
	r.mount();
	document.querySelector("[data-delete-evolved]").click();
	await tick();
	const out = document.querySelector("[data-account-result]");
	assert.equal(out.className, "at__result at__result--err");
	assert.equal(out.textContent, "Delete failed: permission denied");
	assert.equal(h.clearAll.mock.calls.length, 0);
});

test("delete action can be cancelled", async () => {
	window.confirm = vi.fn(() => false);
	const r = viewAccountSettings();
	document.body.innerHTML = r.html;
	r.mount();
	document.querySelector("[data-delete-evolved]").click();
	await tick();
	assert.equal(h.serverWrite.mock.calls.length, 0);
	assert.equal(h.clearAll.mock.calls.length, 0);
});
