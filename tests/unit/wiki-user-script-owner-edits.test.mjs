// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { beforeEach, test, vi } from "vitest";

const h = vi.hoisted(() => ({
	backendGetJson: vi.fn(),
	serverWrite: vi.fn()
}));

vi.mock("../../public_html/lib/core/api.js", async (orig) => {
	const actual = await orig();
	return { ...actual, backendGetJson: h.backendGetJson };
});
vi.mock("../../public_html/lib/core/serversync.js", async (orig) => {
	const actual = await orig();
	return { ...actual, serverWrite: h.serverWrite };
});

const { wikiUserScriptOwnerEditsWorkspace } =
	await import("../../public_html/lib/organisms/wiki-user-script-owner-edits.js");
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
const TOOL = "enwiki-alaexis-ai-source-verification";

function scriptEntry(overrides = {}) {
	return {
		toolName: TOOL,
		title: "Alice verification script",
		owner: "Alice",
		wiki: "en.wikipedia.org",
		sourceUrl: "https://en.wikipedia.org/wiki/User:Alice/verification.js",
		sourceMetadata: {
			title: "Source title",
			keywords: ["source", "verified"],
			user_docs_url: [{ url: "https://example.org/source", language: "en" }]
		},
		currentMetadata: {
			title: "Current title",
			subtitle: "Current subtitle",
			description: "Current description",
			license: "GPL-3.0-or-later",
			keywords: ["current", "metadata"],
			user_docs_url: [{ url: "https://example.org/docs", language: "en" }],
			developer_docs_url: [{ url: "https://example.org/developers" }]
		},
		ownerCuratedFields: ["title", "description"],
		projectionAvailable: true,
		historyOnly: false,
		...overrides
	};
}

function ownerContext(overrides = {}) {
	return {
		supported: true,
		canEdit: true,
		ownerProof: { username: "Alice", wiki: "en.wikipedia.org" },
		items: [],
		...overrides
	};
}

function mountWorkspace(entries = [scriptEntry()]) {
	const workspace = wikiUserScriptOwnerEditsWorkspace();
	document.body.innerHTML = workspace.html;
	h.backendGetJson.mockResolvedValueOnce({ entries });
	return workspace;
}

async function openEditor(toolName, context) {
	h.backendGetJson.mockResolvedValueOnce(context);
	const button = /** @type {HTMLButtonElement} */ (document.querySelector(`[data-wiki-owner-open="${toolName}"]`));
	assert.ok(button);
	button.click();
	await tick();
	return /** @type {HTMLElement} */ (
		document.querySelector(`[data-wiki-owner-entry="${toolName}"] [data-wiki-owner-editor]`)
	);
}

function submit(form) {
	form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
}

beforeEach(() => {
	h.backendGetJson.mockReset();
	h.serverWrite.mockReset();
	h.serverWrite.mockResolvedValue({});
	document.body.innerHTML = "";
});

test("workspace shows source and effective metadata, filters malformed rows, and rejects unsafe source links", async () => {
	const workspace = mountWorkspace([
		scriptEntry({ title: "Alice <script>alert(1)</script>" }),
		scriptEntry({
			toolName: "unsafe-script",
			title: "Source-only script",
			sourceUrl: "javascript:alert(1)",
			sourceMetadata: {},
			currentMetadata: {},
			ownerCuratedFields: [],
			projectionAvailable: false,
			historyOnly: true
		}),
		null,
		[]
	]);
	document.body.innerHTML = workspace.html;
	workspace.mount();
	await tick();

	assert.equal(document.querySelectorAll("[data-wiki-owner-entry]").length, 2);
	assert.match(document.body.innerHTML, /Current effective Evolved value/);
	assert.match(document.body.innerHTML, /Evolved projection unavailable/);
	assert.match(document.body.innerHTML, /Source title/);
	assert.match(document.body.innerHTML, /Current title/);
	assert.match(document.body.innerHTML, /No catalogue metadata is available/);
	assert.match(document.body.innerHTML, /History only/);
	assert.match(document.body.innerHTML, /Alice &lt;script&gt;/);
	assert.doesNotMatch(document.body.innerHTML, /<script>alert\(1\)<\/script>/);
	assert.doesNotMatch(document.body.innerHTML, /href="javascript:/);
});

test("verified owner editor renders editable fields and scoped revision history", async () => {
	const workspace = mountWorkspace();
	document.body.innerHTML = workspace.html;
	workspace.mount();
	await tick();
	const editor = await openEditor(
		TOOL,
		ownerContext({
			items: [
				{
					id: 3,
					kind: "catalog-curations",
					data: {
						id: 3,
						editKind: "wiki_userscript_owner",
						reviewStatus: "pending",
						patch: { title: "Proposed title", keywords: ["new", "keywords"], unknown_field: "fallback" },
						rationale: "Corrected after review",
						conflictFields: ["title", 4],
						modifiedAt: "2026-10-10T12:00:00Z"
					}
				},
				{
					id: 4,
					kind: "catalog-curations",
					data: {
						id: 4,
						editKind: "wiki_userscript_owner",
						reviewStatus: "approved",
						patch: { user_docs_url: [{ url: "https://example.org/docs", language: "en" }] }
					}
				},
				{
					id: 5,
					kind: "catalog-curations",
					data: { id: 5, editKind: "wiki_userscript_owner", reviewStatus: "rejected", patch: {} }
				},
				{
					id: 6,
					kind: "catalog-curations",
					data: { id: 6, editKind: "other", reviewStatus: "pending", patch: {} }
				},
				{ id: 7, kind: "catalog-curations", data: [] },
				{ id: 8, kind: "other", data: { editKind: "wiki_userscript_owner" } },
				{
					id: 9,
					kind: "catalog-curations",
					data: { id: 9, editKind: "wiki_userscript_owner", reviewStatus: "unknown-status", patch: {} }
				}
			]
		})
	);

	assert.match(editor.textContent, /Verified page owner/);
	assert.match(editor.textContent, /Alice/);
	assert.ok(editor.querySelector('[data-owner-edit-field="title"]'));
	assert.ok(editor.querySelector('[data-owner-edit-field="description"]') instanceof HTMLTextAreaElement);
	assert.ok(editor.querySelector('[data-owner-edit-field="keywords"]') instanceof HTMLTextAreaElement);
	assert.ok(editor.querySelector('[data-owner-edit-field="user_docs_url"]') instanceof HTMLTextAreaElement);
	assert.ok(editor.querySelector('[data-owner-edit-field="license"]') instanceof HTMLInputElement);
	assert.match(editor.textContent, /Pending moderation/);
	assert.match(editor.textContent, /Approved Evolved curation/);
	assert.match(editor.textContent, /Rejected/);
	assert.match(editor.textContent, /Status unavailable/);
	assert.match(editor.textContent, /Source conflict on: title/);
	assert.match(editor.textContent, /unknown field/);
	assert.match(editor.textContent, /Revision 3/);
	assert.doesNotMatch(editor.textContent, /Revision 6/);
	assert.equal(editor.querySelectorAll(".wiki-user-scripts__revision").length, 4);
});

test("legacy scalar documentation URLs remain visible in the owner editor", async () => {
	const currentMetadata = {
		...scriptEntry().currentMetadata,
		user_docs_url: "https://example.org/legacy-docs"
	};
	const workspace = mountWorkspace([scriptEntry({ currentMetadata })]);
	workspace.mount();
	await tick();
	const editor = await openEditor(TOOL, ownerContext());
	const docs = /** @type {HTMLTextAreaElement} */ (editor.querySelector('[data-owner-edit-field="user_docs_url"]'));

	assert.deepEqual(JSON.parse(docs.value), [{ url: "https://example.org/legacy-docs" }]);
});

test("legacy scalar documentation links are not proposed as an unchanged edit", async () => {
	const currentMetadata = {
		...scriptEntry().currentMetadata,
		user_docs_url: "https://example.org/legacy-docs"
	};
	const workspace = mountWorkspace([scriptEntry({ currentMetadata })]);
	workspace.mount();
	await tick();
	const editor = await openEditor(TOOL, ownerContext());
	const form = /** @type {HTMLFormElement} */ (editor.querySelector("form"));
	form.querySelector("[data-owner-edit-rationale]").value = "The existing link remains correct.";
	submit(form);
	await tick();

	assert.equal(h.serverWrite.mock.calls.length, 0);
	assert.equal(
		form.querySelector("[data-owner-editor-notice]").textContent,
		"Change at least one catalogue field before submitting."
	);
});

test("owner edit requires a non-empty rationale before any write", async () => {
	const workspace = mountWorkspace();
	document.body.innerHTML = workspace.html;
	workspace.mount();
	await tick();
	const editor = await openEditor(TOOL, ownerContext());
	const form = /** @type {HTMLFormElement} */ (editor.querySelector("form"));
	const rationale = /** @type {HTMLTextAreaElement} */ (form.querySelector("[data-owner-edit-rationale]"));
	form.querySelector('[data-owner-edit-field="title"]').value = "Changed title";
	form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));

	assert.equal(h.serverWrite.mock.calls.length, 0);
	assert.equal(
		form.querySelector("[data-owner-editor-notice]").textContent,
		"Explain the correction before submitting."
	);
	assert.equal(document.activeElement, rationale);
});

test("owner edit rejects malformed and non-array documentation JSON", async () => {
	const workspace = mountWorkspace();
	document.body.innerHTML = workspace.html;
	workspace.mount();
	await tick();
	const editor = await openEditor(TOOL, ownerContext());
	const form = /** @type {HTMLFormElement} */ (editor.querySelector("form"));
	form.querySelector("[data-owner-edit-rationale]").value = "Fix the documentation link.";
	const links = /** @type {HTMLTextAreaElement} */ (form.querySelector('[data-owner-edit-field="user_docs_url"]'));

	links.value = '{"url":"https://example.org/docs"}';
	submit(form);
	assert.match(form.querySelector("[data-owner-editor-notice]").textContent, /must be a JSON array/);

	links.value = "[";
	submit(form);
	assert.match(form.querySelector("[data-owner-editor-notice]").textContent, /must be valid JSON/);
	assert.equal(h.serverWrite.mock.calls.length, 0);
});

test("owner edit reports unchanged metadata without creating a proposal", async () => {
	const currentMetadata = {
		...scriptEntry().currentMetadata,
		user_docs_url: [],
		developer_docs_url: []
	};
	const workspace = mountWorkspace([scriptEntry({ currentMetadata })]);
	document.body.innerHTML = workspace.html;
	workspace.mount();
	await tick();
	const editor = await openEditor(TOOL, ownerContext());
	const form = /** @type {HTMLFormElement} */ (editor.querySelector("form"));
	form.querySelector("[data-owner-edit-rationale]").value = "The current metadata is correct.";
	form.querySelector('[data-owner-edit-field="user_docs_url"]').value = "";
	form.querySelector('[data-owner-edit-field="developer_docs_url"]').value = "";
	submit(form);

	assert.equal(
		form.querySelector("[data-owner-editor-notice]").textContent,
		"Change at least one catalogue field before submitting."
	);
	assert.equal(h.serverWrite.mock.calls.length, 0);
});

test("owner edit submits bounded changes and keeps a saved revision when refresh fails", async () => {
	const workspace = wikiUserScriptOwnerEditsWorkspace();
	document.body.innerHTML = workspace.html;
	h.backendGetJson.mockResolvedValueOnce({
		entries: [
			scriptEntry({
				currentMetadata: {
					title: "Current title",
					subtitle: "",
					description: "",
					license: "",
					keywords: [],
					user_docs_url: [],
					developer_docs_url: []
				}
			})
		]
	});
	workspace.mount();
	await tick();
	h.backendGetJson.mockResolvedValueOnce(ownerContext({ items: [] }));
	document.querySelector(`[data-wiki-owner-open="${TOOL}"]`).click();
	await tick();

	const editor = /** @type {HTMLElement} */ (
		document.querySelector(`[data-wiki-owner-entry="${TOOL}"] [data-wiki-owner-editor]`)
	);
	const form = /** @type {HTMLFormElement} */ (editor.querySelector("form"));
	form.querySelector('[data-owner-edit-field="title"]').value = "  Updated title  ";
	form.querySelector('[data-owner-edit-field="keywords"]').value = Array.from(
		{ length: 51 },
		(_, index) => ` keyword-${index + 1} `
	).join("\n");
	form.querySelector('[data-owner-edit-field="user_docs_url"]').value = JSON.stringify([
		{ url: "https://example.org/owner-docs", language: "en" }
	]);
	form.querySelector("[data-owner-edit-rationale]").value = "Add the source documentation that was missing.";
	h.serverWrite.mockResolvedValueOnce({
		item: {
			id: 12,
			kind: "catalog-curations",
			data: {
				id: 12,
				editKind: "wiki_userscript_owner",
				reviewStatus: "pending",
				patch: { title: "Updated title" },
				rationale: "Add the source documentation that was missing.",
				modifiedAt: "2026-10-11T12:00:00Z"
			}
		}
	});
	h.backendGetJson.mockRejectedValueOnce(new Error("refresh offline"));
	submit(form);
	await tick();
	await tick();

	const [method, path, body] = h.serverWrite.mock.calls[0];
	assert.equal(method, "POST");
	assert.equal(path, `/v1/catalog/tools/${TOOL}/owner-edits/`);
	assert.equal(body.patch.title, "Updated title");
	assert.equal(body.patch.keywords.length, 50);
	assert.deepEqual(body.patch.user_docs_url, [{ url: "https://example.org/owner-docs", language: "en" }]);
	assert.equal(body.rationale, "Add the source documentation that was missing.");
	assert.match(editor.textContent, /Saved for moderation/);
	assert.match(editor.textContent, /Updated title/);
	assert.match(editor.textContent, /Pending moderation/);
});

test("read-only and unsupported pages stay non-editable while switching hides the previous panel", async () => {
	const secondTool = "other-user-script";
	const workspace = mountWorkspace([scriptEntry(), scriptEntry({ toolName: secondTool, title: "Other script" })]);
	document.body.innerHTML = workspace.html;
	workspace.mount();
	await tick();
	const readonly = await openEditor(TOOL, ownerContext({ canEdit: false }));
	assert.match(readonly.textContent, /not verified as the owner/);
	assert.equal(readonly.querySelector("form"), null);

	const unsupported = await openEditor(secondTool, ownerContext({ supported: false, canEdit: false }));
	assert.equal(readonly.hidden, true);
	assert.equal(unsupported.hidden, false);
	assert.match(unsupported.textContent, /not an editable Wikimedia user-script page/);
	assert.match(unsupported.textContent, /No owner proposals yet/);
	assert.equal(unsupported.querySelector("form"), null);
});

test("listing and ownership failures remain visible and fail closed", async () => {
	let workspace = wikiUserScriptOwnerEditsWorkspace();
	document.body.innerHTML = workspace.html;
	h.backendGetJson.mockResolvedValueOnce(null);
	workspace.mount();
	await tick();
	assert.match(document.querySelector("[data-wiki-owner-list]").textContent, /could not be loaded/);

	document.body.innerHTML = "";
	workspace = wikiUserScriptOwnerEditsWorkspace();
	document.body.innerHTML = workspace.html;
	h.backendGetJson.mockRejectedValueOnce(new Error("offline"));
	workspace.mount();
	await tick();
	assert.match(document.querySelector("[data-wiki-owner-list]").textContent, /offline/);

	document.body.innerHTML = "";
	workspace = mountWorkspace();
	document.body.innerHTML = workspace.html;
	workspace.mount();
	await tick();
	h.backendGetJson.mockResolvedValueOnce(null);
	document.querySelector(`[data-wiki-owner-open="${TOOL}"]`).click();
	await tick();
	assert.match(document.querySelector("[data-wiki-owner-editor]").textContent, /Ownership could not be verified/);
	assert.equal(document.querySelector("[data-wiki-owner-editor] form"), null);
});

test("ownership check transport failures render a safe message", async () => {
	const workspace = mountWorkspace();
	workspace.mount();
	await tick();
	h.backendGetJson.mockRejectedValueOnce(new Error("ownership endpoint offline"));
	document.querySelector(`[data-wiki-owner-open="${TOOL}"]`).click();
	await tick();

	const panel = /** @type {HTMLElement} */ (document.querySelector("[data-wiki-owner-editor]"));
	assert.match(panel.textContent, /ownership endpoint offline/);
	assert.equal(panel.querySelector("form"), null);
});

test("owner edit displays write failures and restores the submit button", async () => {
	const workspace = mountWorkspace();
	document.body.innerHTML = workspace.html;
	workspace.mount();
	await tick();
	const editor = await openEditor(TOOL, ownerContext());
	const form = /** @type {HTMLFormElement} */ (editor.querySelector("form"));
	form.querySelector('[data-owner-edit-field="title"]').value = "Updated title";
	form.querySelector("[data-owner-edit-rationale]").value = "Correct the title.";
	h.serverWrite.mockRejectedValueOnce({ body: { error: "The proposal was rejected." }, message: "generic failure" });
	submit(form);
	await tick();

	assert.match(form.querySelector("[data-owner-editor-notice]").textContent, /The proposal was rejected/);
	assert.equal(form.querySelector('button[type="submit"]').disabled, false);
});
