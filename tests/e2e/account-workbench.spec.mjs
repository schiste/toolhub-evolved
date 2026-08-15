// SPDX-License-Identifier: GPL-3.0-or-later
import { expect, test } from "@playwright/test";
import { useSmokeServer } from "./harness.mjs";

test.describe("Account workbench layout", () => {
	const smoke = useSmokeServer();

	async function mockSignedIn(page) {
		await page.route("**/v1/user/", (route) =>
			route.fulfill({
				contentType: "application/json; charset=utf-8",
				json: { authenticated: true, username: "Schiste", csrf: "csrf-token" }
			})
		);
		await page.route("**/v1/overlay/", (route) =>
			route.fulfill({ contentType: "application/json; charset=utf-8", json: {} })
		);
	}

	test("keeps My tools tabs aligned and retired submit UI absent", async ({ page }) => {
		await mockSignedIn(page);
		await page.route("**/v1/crawler/runs/", (route) =>
			route.fulfill({ contentType: "application/json; charset=utf-8", json: { count: 0, results: [] } })
		);
		await page.route("**/v1/me/tools/", (route) =>
			route.fulfill({
				contentType: "application/json; charset=utf-8",
				json: {
					username: "Schiste",
					person: { id: "person-schiste", displayName: "Christophe" },
					identities: { wikiUsername: "Schiste", toolforgeDeveloperUsernames: ["schiste"] },
					toolforgeProjects: [{ name: "wiki-polis", developerUsernames: ["schiste"] }],
					verified: [
						{
							tool: {
								name: "toolforge-wiki-polis",
								title: "A Wikimedia wrapper for polis discussions",
								description: "Discussion analysis for Wikimedia projects.",
								url: "https://toolforge.org/",
								author: [{ name: "Schiste" }],
								tool_type: "web app",
								modified_date: "2026-03-01T12:00:00Z"
							},
							claims: [{ verificationMethod: "toolforge_maintainer", isVerified: true }],
							toolforgeProjects: ["wiki-polis"],
							toolinfoSource: {
								sourceUrl: "https://toolsadmin.wikimedia.org/tools/toolinfo/v1.2/toolinfo.json",
								sourceKind: "toolsadmin",
								sourceLabel: "Source toolsadmin",
								itemCount: 2880,
								lastFetchedAt: "2026-07-29T10:00:00Z"
							}
						}
					],
					possible: [
						{
							tool: {
								name: "toolforge-wiki-polis",
								title: "A Wikimedia wrapper for polis discussions",
								description: "Duplicate unverified candidate that must not surface.",
								url: "https://toolforge.org/",
								author: [{ name: "Schiste" }],
								tool_type: "web app",
								modified_date: "2026-03-01T12:00:00Z"
							},
							claims: [{ verificationMethod: "author_display_name", isVerified: false }]
						}
					],
					toolinfoSources: {}
				}
			})
		);

		await page.setViewportSize({ width: 1365, height: 768 });
		await page.goto(new URL("/my-tools", smoke.url).href);

		await expect(page.getByRole("heading", { name: "My tools" })).toBeVisible();
		await expect(page.getByText("Submit a tool")).toHaveCount(0);
		await expect(page.locator("#submit-tool")).toHaveCount(0);
		await expect(page.locator(".account-workbench__toolbar")).toHaveCount(0);
		await expect(page.locator(".account-workbench__section-head")).toHaveCount(0);
		await expect(page.locator("#my-tools-heading")).toHaveCount(0);
		await expect(
			page.locator('.account-workbench__body > .account-workbench__section[aria-labelledby="my-tools-heading"]')
		).toHaveCount(0);
		await expect(page.getByText("Toolhub authorship")).toHaveCount(0);
		await expect(page.getByText("Official Toolhub data + Evolved verification")).toHaveCount(0);
		await expect(page.getByText("toolsadmin feed")).toHaveCount(0);

		const tabs = page.locator(".account-workbench__nav .tab-bar__item");
		await expect(tabs).toHaveCount(5);
		const tabBoxes = await tabs.evaluateAll((items) =>
			items.map((item) => {
				const rect = item.getBoundingClientRect();
				return { top: rect.top, height: rect.height };
			})
		);
		const firstTab = tabBoxes[0];
		expect(tabBoxes.every((box) => Math.abs(box.top - firstTab.top) <= 1)).toBe(true);
		expect(tabBoxes.every((box) => Math.abs(box.height - firstTab.height) <= 1)).toBe(true);
		await expect(page.locator(".account-workbench__nav .is-active")).toHaveCSS("color", "rgb(12, 87, 168)");
		await expect(page.locator(".account-workbench__nav .is-active")).toHaveCSS(
			"background-color",
			"rgb(231, 240, 250)"
		);
		await expect
			.poll(() =>
				page.locator(".account-workbench__nav .is-active").evaluate((item) => {
					const after = getComputedStyle(item, "::after");
					return { backgroundColor: after.backgroundColor, bottom: after.bottom, height: after.height };
				})
			)
			.toEqual({ backgroundColor: "rgb(12, 87, 168)", bottom: "0px", height: "3px" });
		await expect(page.locator('.account-workbench__nav a[href="/preferences"]')).toHaveText(/Preferences/);

		await expect(page.locator(".account-records__table")).toBeVisible();
		await page.getByRole("button", { name: "Create toolinfo.json" }).click();
		await expect(page.getByRole("heading", { name: "Generated toolinfo.json" })).toBeVisible();
		await expect(page.locator('[data-toolinfo-field="name"]')).toHaveValue("toolforge-wiki-polis");
		await expect(page.locator('[data-toolinfo-field="author-wiki"]')).toHaveValue("Schiste");
		await expect(page.locator('[data-toolinfo-field="author-developer"]')).toHaveValue("schiste");
		await expect(page.locator("[data-toolinfo-preview]")).toHaveValue(/"developer_username": "schiste"/);
		await expect(page.getByText("Unverified author name")).toHaveCount(0);
		await expect(page.getByText("Verified: Toolforge maintainer")).toBeVisible();
		const badgeOverflow = await page.locator(".account-records__table .sync-badge").evaluateAll((badges) =>
			badges
				.map((badge) => {
					const cell = badge.closest("td");
					if (!cell) return "";
					const badgeRect = badge.getBoundingClientRect();
					const cellRect = cell.getBoundingClientRect();
					return badgeRect.right > cellRect.right + 1
						? `${badge.textContent?.trim() || "badge"} overflows its table cell`
						: "";
				})
				.filter(Boolean)
		);
		expect(badgeOverflow).toEqual([]);
	});

	test("keeps collection tabs free of duplicate section headings", async ({ page }) => {
		await mockSignedIn(page);
		await page.setViewportSize({ width: 1365, height: 768 });

		for (const routePath of ["/my-lists", "/favorites"]) {
			await page.goto(new URL(routePath, smoke.url).href);
			await expect(page.locator("#my-lists-heading")).toHaveCount(0);
			await expect(page.locator("#favorites-heading")).toHaveCount(0);
			await expect(page.locator(".account-workbench__body > .account-workbench__content-section")).toHaveCount(0);
			await expect(page.locator(".account-workbench__nav [aria-current='page']")).toBeVisible();
		}
	});
});
