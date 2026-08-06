// SPDX-License-Identifier: GPL-3.0-or-later
import { expect, test } from "@playwright/test";
import { useSmokeServer } from "./harness.mjs";

test.describe("Tool action audience", () => {
	const smoke = useSmokeServer();

	test("a signed-in audit account without a relationship sees contributor actions", async ({ page }) => {
		await page.route("**/v1/user/", (route) =>
			route.fulfill({
				contentType: "application/json; charset=utf-8",
				json: {
					authenticated: true,
					username: "Audit Account",
					csrf: "csrf-token",
					officialWrites: true
				}
			})
		);
		await page.route("**/v1/overlay/", (route) =>
			route.fulfill({ contentType: "application/json; charset=utf-8", json: {} })
		);
		await page.route("**/v1/tools/toolforge-admin/viewer-context/", (route) =>
			route.fulfill({
				contentType: "application/json; charset=utf-8",
				json: {
					toolName: "toolforge-admin",
					personId: "audit-person",
					audience: "contributor",
					qualifyingRelationships: []
				}
			})
		);

		await page.goto(new URL("/tools/toolforge-admin", smoke.url).href);

		const actions = page.locator(".toolpage__management");
		await expect(actions).toHaveAttribute("aria-label", "Contribute");
		await expect(actions.getByText("Claim a relationship", { exact: true })).toBeVisible();
		await expect(actions.getByText("Suggest tool changes", { exact: true })).toBeVisible();
		await expect(actions.getByText("Contribute annotations", { exact: true })).toBeVisible();
		await expect(page.getByText("Maintainer actions", { exact: true })).toHaveCount(0);
		await expect(page.locator("[data-tool-delete]")).toHaveCount(0);
	});
});
