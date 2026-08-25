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
const { viewAccountSettings } = await import("../../public_html/views/account-settings.js");
const { viewDeveloperSettings } = await import("../../public_html/views/developer-settings.js");
const { viewMyTools } = await import("../../public_html/views/my-tools.js");

beforeEach(() => {
	vi.clearAllMocks();
	document.body.innerHTML = "";
	window.confirm = vi.fn(() => true);
	setServerUser("Ada Lovelace");
});

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

test("viewAccountSettings renders export, delete, and OAuth controls", () => {
	const r = viewAccountSettings();
	assert.equal(r.title, "Preferences - Toolhub");
	assert.ok(!r.html.includes("Evolved preferences"));
	assert.ok(!r.html.includes("Configurable Evolved-only settings will appear here as they become available."));
	assert.ok(r.html.includes("Generate export"));
	assert.ok(r.html.includes("Delete Evolved-local data"));
	assert.ok(r.html.includes("Connected identities"));
	assert.ok(r.html.includes('href="/oauth/login"'));
	assert.ok(r.html.includes('method="post" action="/oauth/logout"'));
});

test("viewDeveloperSettings renders signed-toolinfo settings without the removed developer page directory", () => {
	const r = viewDeveloperSettings();
	assert.equal(r.title, "Developer settings - Toolhub");
	assert.ok(!r.html.includes("Official Toolhub developer settings"));
	assert.ok(!r.html.includes("Developer pages"));
	assert.ok(r.html.includes("Signed toolinfo authorship"));
	assert.ok(r.html.includes("toolinfo.json reference"));
	assert.ok(r.html.includes("&quot;_schema&quot;: &quot;/toolinfo/1.2.2&quot;"));
	assert.ok(r.html.includes("current.yaml"));
	assert.ok(r.html.includes("Register key"));
	assert.ok(r.html.includes("Build payload"));
	assert.ok(!r.html.includes("account-data__links"));
	assert.ok(!r.html.includes('href="/api-docs"'));
	assert.ok(!r.html.includes("Review official Toolhub tools and Evolved authorship verification"));
	assert.ok(!r.html.includes("My apps"));
	assert.ok(!r.html.includes('href="/my-apps"'));
	assert.ok(!r.html.includes("API token"));
	assert.ok(!r.html.includes("Authorized apps"));
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

test("viewMyTools lists official Toolhub tools related to the signed-in user", async () => {
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
				],
				relationships: [
					{ requestedRelationship: "maintainer", verificationStatus: "verified", isVerified: true },
					{ requestedRelationship: "author", verificationStatus: "unverified", isVerified: false }
				],
				toolinfoDiscovery: {
					status: "found",
					method: "sitemap",
					toolinfoUrl: "https://example.org/meta/toolinfo.json",
					checkedAt: "2026-07-28T12:00:00Z"
				},
				toolinfoSource: {
					toolName: "ada-tool",
					sourceUrl: "https://toolsadmin.wikimedia.org/tools/toolinfo/v1.2/toolinfo.json",
					sourceKind: "toolsadmin",
					sourceLabel: "Toolsadmin feed",
					lastFetchedAt: "2026-07-28T12:30:00Z",
					itemCount: 2880
				}
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
				],
				relationships: [
					{ requestedRelationship: "author", verificationStatus: "unverified", isVerified: false }
				],
				toolinfoDiscovery: { status: "pending" }
			}
		]
	});
	const r = await viewMyTools();
	assert.equal(r.title, "My tools - Toolhub");
	assert.deepEqual(h.backendGetJson.mock.calls[0], ["/v1/me/tools/"]);
	assert.equal(h.paginate.mock.calls.length, 0);
	assert.ok(r.html.includes("Ada Tool"));
	assert.ok(r.html.includes("Ada Developer Tool"));
	assert.ok(r.html.includes("Your relationship"));
	assert.ok(r.html.includes(">Maintainer</span>"));
	assert.ok(r.html.includes(">Author</span>"));
	assert.ok(!r.html.includes(">Owner</th>"));
	assert.ok(!r.html.includes("Relationship unavailable"));
	assert.ok(r.html.includes("ada-tool"));
	assert.ok(r.html.includes("web app"));
	assert.ok(r.html.includes("https://example.org/ada"));
	assert.ok(r.html.includes("Verified: Toolforge maintainer"));
	assert.ok(!r.html.includes("Verified: Toolhub write access"));
	assert.ok(!r.html.includes("Verified: signed toolinfo"));
	assert.ok(r.html.includes("Unverified author name"));
	assert.ok(r.html.includes("Metadata source"));
	assert.ok(r.html.includes("Official crawler source"));
	assert.ok(r.html.includes("Toolsadmin feed"));
	assert.ok(!r.html.includes(">Toolsadmin feed</a>"));
	assert.ok(r.html.includes("2,880 tools"));
	assert.ok(r.html.includes("Self-hosted check: found in sitemap"));
	assert.ok(r.html.includes("Queued for discovery"));
	assert.ok(!r.html.includes("Official Toolhub data + Evolved verification"));
	assert.ok(!r.html.includes("Toolhub authorship"));
	assert.ok(!r.html.includes("Verification is per tool"));
	assert.ok(!r.html.includes("Possible match"));
	assert.ok(r.html.includes("Find or register toolinfo.json"));
});

test("viewMyTools prefers verified rows when the same tool appears in possible matches", async () => {
	h.backendGetJson.mockResolvedValue({
		verified: [
			{
				tool: { name: "shared-tool", title: "Shared Tool", url: "https://shared.example", author: [] },
				claims: [{ verificationMethod: "toolforge_maintainer", verificationStatus: "verified" }]
			}
		],
		possible: [
			{
				tool: { name: "shared-tool", title: "Shared Tool", url: "https://shared.example", author: [] },
				claims: [{ verificationMethod: "author_display_name", verificationStatus: "unverified" }]
			}
		]
	});

	const r = await viewMyTools();
	const page = document.createElement("div");
	page.innerHTML = r.html;
	const rows = page.querySelectorAll(".account-records__table tbody tr");

	assert.equal(rows.length, 1);
	assert.match(rows[0].textContent, /Shared Tool/);
	assert.ok(r.html.includes("Verified: Toolforge maintainer"));
	assert.ok(!r.html.includes("Unverified author name"));
});

test("viewMyTools does not show self-hosted failures when official crawler source exists", async () => {
	h.backendGetJson.mockResolvedValue({
		verified: [
			{
				tool: {
					name: "toolforge-toolhub-evolved",
					title: "Toolhub Evolved",
					url: "https://toolhub-evolved.toolforge.org/",
					author: [{ name: "Christophe" }]
				},
				claims: [
					{
						verificationMethod: "toolforge_maintainer",
						verificationStatus: "verified",
						isVerified: true
					}
				],
				toolinfoDiscovery: { status: "error", lastError: "DNS failed" },
				toolinfoSource: {
					toolName: "toolforge-toolhub-evolved",
					sourceUrl: "https://toolsadmin.wikimedia.org/tools/toolinfo/v1.2/toolinfo.json",
					sourceKind: "toolsadmin",
					sourceLabel: "Toolsadmin feed",
					itemCount: 2880
				}
			}
		],
		possible: []
	});

	const r = await viewMyTools();

	assert.ok(r.html.includes("Toolhub Evolved"));
	assert.ok(r.html.includes("Verified: Toolforge maintainer"));
	assert.ok(r.html.includes("Official crawler source"));
	assert.ok(r.html.includes("Toolsadmin feed"));
	assert.ok(!r.html.includes(">Toolsadmin feed</a>"));
	assert.ok(!r.html.includes("Check failed"));
	assert.ok(!r.html.includes("DNS failed"));
});

test("viewMyTools labels invalid crawler evidence URLs", async () => {
	h.backendGetJson.mockResolvedValue({
		verified: [
			{
				tool: {
					name: "bad-source",
					title: "Bad Source",
					url: "https://tool.example",
					author: []
				},
				claims: [],
				toolinfoDiscovery: {
					status: "found",
					method: "root",
					toolinfoUrl: "https://exa mple.org/toolinfo.json"
				},
				toolinfoSource: {
					toolName: "bad-source",
					sourceUrl: "javascript:alert(1)",
					sourceKind: "toolsadmin",
					sourceLabel: "Toolsadmin feed"
				}
			}
		],
		possible: [
			{
				tool: {
					name: "bad-discovery",
					title: "Bad Discovery",
					url: "https://tool2.example",
					author: []
				},
				claims: [],
				toolinfoDiscovery: {
					status: "found",
					method: "root",
					toolinfoUrl: "https://exa mple.org/toolinfo.json"
				}
			}
		]
	});

	const r = await viewMyTools();

	assert.ok(!r.html.includes('href="https://exa mple.org/toolinfo.json"'));
	assert.ok(!r.html.includes('href="javascript:alert(1)"'));
	assert.ok(!r.html.includes('aria-label="Toolsadmin feed: invalid URL"'));
	assert.ok(r.html.includes('aria-label="Toolsadmin feed: toolsadmin"'));
	assert.ok(r.html.includes('aria-label="toolinfo.json URL: invalid URL"'));
	assert.ok(r.html.includes('data-url-state="invalid"'));
});

test("viewMyTools renders all toolinfo discovery states", async () => {
	h.backendGetJson.mockResolvedValue({
		verified: [
			{
				tool: { name: "root-tool", title: "Root Tool", url: "https://root.example", author: [] },
				claims: [],
				toolinfoDiscovery: {
					status: "found",
					method: "root",
					toolinfoUrl: "https://root.example/toolinfo.json"
				}
			}
		],
		possible: [
			{
				tool: { name: "missing-tool", title: "Missing Tool", url: "https://missing.example", author: [] },
				claims: [],
				toolinfoDiscovery: { status: "not_found", checkedAt: "2026-07-28T12:00:00Z" }
			},
			{
				tool: { name: "error-tool", title: "Error Tool", url: "https://error.example", author: [] },
				claims: [],
				toolinfoDiscovery: { status: "error", lastError: "DNS failed" }
			},
			{
				tool: { name: "no-url-tool", title: "No URL Tool", author: [] },
				claims: [],
				toolinfoDiscovery: {
					status: "no_url",
					lastError: "official Toolhub record has no URL to probe"
				}
			}
		]
	});
	const r = await viewMyTools();
	assert.ok(r.html.includes("Found at root"));
	assert.ok(r.html.includes("toolinfo.json not found"));
	assert.ok(r.html.includes("Check failed"));
	assert.ok(r.html.includes("DNS failed"));
	assert.ok(r.html.includes("No homepage URL"));
	assert.ok(r.html.includes("official Toolhub record has no URL to probe"));
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
	assert.equal(
		out.textContent,
		"Export failed: offline No official change was published; retry or report this error if it continues."
	);
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
	assert.equal(
		out.textContent,
		"Delete failed: permission denied You are signed in, but this account is not allowed to perform this action. Check your Toolhub permissions or use the account that owns the tool."
	);
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

test("preferences edits the immutable-person profile and renders claim history", async () => {
	h.backendGetJson.mockReset();
	h.serverWrite.mockReset();
	h.backendGetJson
		.mockResolvedValueOnce({ bindings: [], candidates: [], proofMethods: { toolforgeSshSignature: true } })
		.mockResolvedValueOnce({
			profile: {
				personId: "3d6fdd39-b090-4c19-919f-7753b45e1046",
				displayName: "Ada Lovelace",
				bio: "Builds tools",
				location: "London",
				websiteUrl: "https://example.org",
				avatarUrl: "https://example.org/avatar.png",
				links: ["https://meta.wikimedia.org/wiki/User:Ada"],
				visibility: "public"
			}
		})
		.mockResolvedValueOnce({
			claims: [
				{
					toolName: "ada-tool",
					requestedRelationship: "maintainer",
					verificationMethod: "toolforge_maintainer",
					verificationStatus: "verified"
				}
			]
		});
	h.serverWrite.mockResolvedValue({
		profile: {
			personId: "3d6fdd39-b090-4c19-919f-7753b45e1046",
			displayName: "Ada Lovelace",
			bio: "Updated bio",
			links: [],
			visibility: "private"
		}
	});
	const view = viewAccountSettings();
	document.body.innerHTML = view.html;
	view.mount();
	await tick();
	await tick();
	assert.equal(document.querySelector('[name="bio"]').value, "Builds tools");
	assert.ok(document.querySelector("[data-profile-link]").innerHTML.includes("/people/3d6fdd39"));
	assert.ok(document.querySelector("[data-claim-history]").textContent.includes("ada-tool"));
	assert.ok(document.querySelector("[data-claim-history]").textContent.includes("Verified"));

	document.querySelector('[name="bio"]').value = "Updated bio";
	document.querySelector('[name="links"]').value = "";
	document.querySelector('[name="private"]').checked = true;
	document.querySelector("[data-profile-form]").dispatchEvent(new Event("submit", { bubbles: true }));
	await tick();
	assert.deepEqual(h.serverWrite.mock.calls[0], [
		"PUT",
		"/v1/me/profile/",
		{
			bio: "Updated bio",
			location: "London",
			websiteUrl: "https://example.org",
			avatarUrl: "https://example.org/avatar.png",
			links: [],
			visibility: "private"
		}
	]);
	assert.ok(document.querySelector("[data-account-result]").textContent.includes("Profile saved"));
});

test("preferences reconnects a Toolforge account with a one-time SSH signature", async () => {
	let connected = false;
	h.backendGetJson.mockImplementation((path) => {
		if (path === "/v1/me/account-links/") {
			return Promise.resolve({
				bindings: connected
					? [
							{
								provider: "toolforge",
								externalId: "9001",
								username: "ada-dev",
								status: "verified",
								toolCount: 4
							}
						]
					: [{ provider: "toolhub", externalId: "42", status: "verified" }],
				candidates: connected
					? []
					: [{ username: "ada-dev", externalId: "9001", toolCount: 4, sshSignatureAvailable: true }],
				proofMethods: { toolforgeSshSignature: true },
				upstreamRepair: {
					profileUrl: "https://toolsadmin.wikimedia.org/profile/",
					sshKeysUrl: "https://toolsadmin.wikimedia.org/profile/settings/ssh-keys/"
				}
			});
		}
		if (path === "/v1/me/profile/") return Promise.resolve({ profile: {} });
		return Promise.resolve({ claims: [] });
	});
	h.serverWrite.mockImplementation((method, path) => {
		if (path.endsWith("/challenges/")) {
			return Promise.resolve({
				challengeId: "challenge-1",
				challenge: "toolhub-evolved-account-link-v1\nnonce:test",
				username: "ada-dev",
				command: "printf challenge | ssh-keygen -Y sign"
			});
		}
		connected = true;
		return Promise.resolve({ ok: true });
	});

	const view = viewAccountSettings();
	document.body.innerHTML = view.html;
	view.mount();
	await tick();
	await tick();
	assert.ok(document.querySelector("[data-account-links]").textContent.includes("ada-dev"));
	document.querySelector('[name="username"]').value = "ada-dev";
	document.querySelector("[data-account-link-start]").dispatchEvent(new Event("submit", { bubbles: true }));
	await tick();
	assert.equal(document.querySelector("[data-account-link-command]").value, "printf challenge | ssh-keygen -Y sign");
	document.querySelector('[name="signature"]').value = "-----BEGIN SSH SIGNATURE-----\ntest";
	document.querySelector("[data-account-link-verify]").dispatchEvent(new Event("submit", { bubbles: true }));
	await tick();
	await tick();

	assert.deepEqual(h.serverWrite.mock.calls[0], [
		"POST",
		"/v1/me/account-links/toolforge/challenges/",
		{ username: "ada-dev" }
	]);
	assert.deepEqual(h.serverWrite.mock.calls[1], [
		"POST",
		"/v1/me/account-links/toolforge/verify/",
		{
			challengeId: "challenge-1",
			challenge: "toolhub-evolved-account-link-v1\nnonce:test",
			signature: "-----BEGIN SSH SIGNATURE-----\ntest"
		}
	]);
	assert.ok(document.querySelector("[data-account-links]").textContent.includes("4 Toolforge tools"));
});
