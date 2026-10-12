// SPDX-License-Identifier: GPL-3.0-or-later
import { expect, test } from "@playwright/test";
import { useSmokeServer } from "./harness.mjs";

const TOOL_NAME = "userscript-enwiki-alice-verification.js";
const SOURCE_URL = "https://en.wikipedia.org/wiki/User:Alice/verification.js";

function isWikimediaRequest(requestUrl) {
	const hostname = new URL(requestUrl).hostname;
	return ["wikipedia.org", "wikimedia.org"].some((domain) => hostname === domain || hostname.endsWith(`.${domain}`));
}

test("checks the host before counting Wikimedia requests", () => {
	expect(isWikimediaRequest("https://en.wikipedia.org/w/api.php")).toBe(true);
	expect(isWikimediaRequest("https://meta.wikimedia.org/w/api.php")).toBe(true);
	expect(isWikimediaRequest("https://attacker.example/?next=https://wikipedia.org")).toBe(false);
	expect(isWikimediaRequest("https://wikipedia.org.attacker.example/w/api.php")).toBe(false);
	expect(isWikimediaRequest("https://notwikipedia.org/w/api.php")).toBe(false);
});

function revision(id, reviewStatus, title) {
	return {
		kind: "catalog-curations",
		id,
		data: {
			id,
			toolName: TOOL_NAME,
			patch: { title },
			rationale: `Proposal ${id}`,
			reviewStatus,
			editKind: "wiki_userscript_owner",
			createdAt: "2026-10-10T12:00:00Z",
			modifiedAt: "2026-10-10T12:00:00Z",
			conflictFields: []
		}
	};
}

async function mockSignedIn(page) {
	await page.route("**/v1/user/", (route) =>
		route.fulfill({
			contentType: "application/json; charset=utf-8",
			json: { authenticated: true, username: "Alice", csrf: "csrf-token" }
		})
	);
	await page.route("**/v1/overlay/", (route) =>
		route.fulfill({ contentType: "application/json; charset=utf-8", json: {} })
	);
	await page.route("**/v1/crawler/runs/", (route) =>
		route.fulfill({ contentType: "application/json; charset=utf-8", json: { count: 0, results: [] } })
	);
	await page.route("**/v1/me/tools/", (route) =>
		route.fulfill({
			contentType: "application/json; charset=utf-8",
			json: {
				username: "Alice",
				person: { id: "person-alice", displayName: "Alice" },
				identities: { wikiUsername: "Alice", toolforgeDeveloperUsernames: [] },
				verified: [],
				possible: [],
				toolinfoSources: {}
			}
		})
	);
	await page.route("**/v1/me/wiki-user-scripts/", (route) =>
		route.fulfill({
			contentType: "application/json; charset=utf-8",
			json: {
				entries: [
					{
						toolName: TOOL_NAME,
						title: "Approved local title",
						wiki: "en.wikipedia.org",
						owner: "Alice",
						sourceUrl: SOURCE_URL,
						sourceMetadata: {
							title: "Census title",
							description: "Description transcribed from the page",
							license: "GPL-3.0-or-later",
							keywords: ["verification"],
							user_docs_url: [{ url: "https://en.wikipedia.org/wiki/User:Alice/docs", language: "en" }]
						},
						currentMetadata: {
							title: "Approved local title",
							description: "Current Evolved description",
							license: "GPL-3.0-or-later",
							keywords: ["verification", "evolved"],
							user_docs_url: [{ url: "https://en.wikipedia.org/wiki/User:Alice/docs", language: "en" }],
							developer_docs_url: []
						},
						projectionAvailable: true,
						ownerCuratedFields: ["title"],
						historyOnly: false,
						verificationRequired: true
					}
				],
				truncated: false
			}
		})
	);
}

function ownerContext(canEdit, items) {
	return {
		ok: true,
		toolName: TOOL_NAME,
		supported: true,
		canEdit,
		reason: canEdit ? "verified_owner" : "wiki_owner_mismatch",
		ownerProof: {
			wiki: "en.wikipedia.org",
			username: "Alice",
			sourceUrl: SOURCE_URL,
			proofMethod: "verified_person_binding_and_centralauth_id"
		},
		items
	};
}

test.describe("Wiki user-script owner metadata", () => {
	const smoke = useSmokeServer();

	test("submits Evolved-local metadata and keeps pending/rejected revisions out of current values", async ({
		page
	}) => {
		await mockSignedIn(page);
		let revisions = [revision(8, "pending", "Pending suggestion"), revision(7, "rejected", "Rejected suggestion")];
		let submittedPayload;
		const wikiWrites = [];
		page.on("request", (request) => {
			if (isWikimediaRequest(request.url()) && request.method() !== "GET") {
				wikiWrites.push(request.method());
			}
		});
		await page.route(`**/v1/catalog/tools/${TOOL_NAME}/owner-edits/`, async (route) => {
			if (route.request().method() === "POST") {
				submittedPayload = route.request().postDataJSON();
				const created = revision(9, "pending", submittedPayload.patch.title);
				revisions = [created, ...revisions];
				await route.fulfill({
					status: 201,
					contentType: "application/json; charset=utf-8",
					json: { ok: true, source: "evolved", syncStatus: "evolved_real", item: created }
				});
				return;
			}
			await route.fulfill({
				contentType: "application/json; charset=utf-8",
				json: ownerContext(true, revisions)
			});
		});

		await page.goto(new URL("/my-tools", smoke.url).href);
		await expect(page.getByRole("heading", { name: "My wiki user-script listings" })).toBeVisible();
		await expect(page.getByText(/Evolved-local metadata proposal/)).toBeVisible();
		await page.getByRole("button", { name: "Review metadata" }).click();

		await expect(page.getByLabel("Display title")).toHaveValue("Approved local title");
		await expect(page.getByLabel("Description")).toHaveValue("Current Evolved description");
		await expect(page.getByText("Pending moderation")).toBeVisible();
		await expect(page.getByText("Rejected", { exact: true })).toBeVisible();
		await expect(page.getByText("Pending suggestion")).toBeVisible();
		await expect(page.getByLabel("Display title")).not.toHaveValue("Pending suggestion");
		await expect(page.getByText("Source-page census values")).toBeVisible();
		await expect(page.getByText("global-9001")).toHaveCount(0);

		await page.getByLabel("Display title").fill("A revised local title");
		await page.getByLabel("Why are you proposing this edit?").fill("Correct the display title");
		await page.getByRole("button", { name: "Submit for moderation" }).click();

		await expect(page.getByText(/Saved for moderation/)).toBeVisible();
		await expect
			.poll(() => submittedPayload)
			.toEqual({
				patch: { title: "A revised local title" },
				rationale: "Correct the display title"
			});
		expect(wikiWrites).toEqual([]);
	});

	test("shows only the owner's history when exact Wikimedia ownership is not verified", async ({ page }) => {
		await mockSignedIn(page);
		await page.route(`**/v1/catalog/tools/${TOOL_NAME}/owner-edits/`, (route) =>
			route.fulfill({
				contentType: "application/json; charset=utf-8",
				json: ownerContext(false, [revision(7, "rejected", "Rejected suggestion")])
			})
		);

		await page.goto(new URL("/my-tools", smoke.url).href);
		await page.getByRole("button", { name: "Review metadata" }).click();

		await expect(page.getByText(/not verified as the owner/i)).toBeVisible();
		await expect(page.getByText("Rejected", { exact: true })).toBeVisible();
		await expect(page.getByLabel("Display title")).toHaveCount(0);
		await expect(page.getByRole("button", { name: "Submit for moderation" })).toHaveCount(0);
	});
});
