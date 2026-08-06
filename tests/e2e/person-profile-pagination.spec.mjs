// SPDX-License-Identifier: GPL-3.0-or-later
import { expect, test } from "@playwright/test";
import { useSmokeServer } from "./harness.mjs";

function profilePage(pageNumber) {
	const start = (pageNumber - 1) * 24;
	const results = Array.from({ length: 24 }, (_, offset) => {
		const index = start + offset;
		const name = `profile-tool-${String(index).padStart(3, "0")}`;
		const missing = index === 0;
		return {
			name,
			summary: missing
				? { name, title: name, description: "", origin: "profile_relationship", _missingCanonical: true }
				: { name, title: `Profile Tool ${index}`, description: `Compact profile summary ${index}.` },
			summaryStatus: missing ? "missing" : "available",
			relationships: [
				{
					type: "maintainer",
					status: "verified",
					confidence: 95,
					evidenceCount: 1,
					evidence: [{ source: "toolforge_toolsadmin", method: "toolforge_maintainer", status: "verified" }]
				}
			]
		};
	});
	return {
		id: "person-prolific",
		displayName: "Prolific Maintainer",
		identityQuality: "stable_id",
		profile: {},
		activity: { status: "active", relatedToolCount: 250, verifiedToolCount: 250 },
		toolCount: 250,
		tools: {
			count: 250,
			page: pageNumber,
			pageSize: 24,
			pageCount: 11,
			nextPage: pageNumber < 11 ? pageNumber + 1 : null,
			previousPage: pageNumber > 1 ? pageNumber - 1 : null,
			results
		}
	};
}

test.describe("Prolific person profile", () => {
	const smoke = useSmokeServer();

	test("pages compact summaries without issuing Toolhub detail requests", async ({ page }) => {
		const profileRequests = [];
		const toolDetailRequests = [];
		page.on("request", (request) => {
			const url = new URL(request.url());
			if (url.pathname.startsWith("/api/tools/")) toolDetailRequests.push(url.pathname);
		});
		await page.route("**/v1/people/person-prolific/**", (route) => {
			const url = new URL(route.request().url());
			const pageNumber = Number(url.searchParams.get("tool_page") || 1);
			profileRequests.push(pageNumber);
			return route.fulfill({ contentType: "application/json; charset=utf-8", json: profilePage(pageNumber) });
		});
		await page.route("**/v1/tools/summaries/**", (route) =>
			route.fulfill({ contentType: "application/json; charset=utf-8", json: { results: {} } })
		);

		await page.goto(new URL("/people/person-prolific", smoke.url).href);

		await expect(page.getByRole("heading", { level: 1, name: "Prolific Maintainer" })).toBeVisible();
		await expect(page.locator('[data-tool^="profile-tool-"]')).toHaveCount(24);
		await expect(page.getByText("250 tools", { exact: true })).toBeVisible();
		await expect(page.getByText("Showing 1–24 of 250", { exact: true })).toBeVisible();
		await expect(page.getByText(/Tool metadata is unavailable/)).toBeVisible();
		expect(toolDetailRequests).toEqual([]);

		await page.locator("[data-person-tools-pager]").getByRole("button", { name: "2", exact: true }).click();
		await expect(page).toHaveURL(/\/people\/person-prolific\?page=2$/);
		await expect(page.getByText("Showing 25–48 of 250", { exact: true })).toBeVisible();
		await expect(page.locator('[data-tool="profile-tool-024"]')).toBeVisible();
		expect(profileRequests).toEqual([1, 2]);
		expect(toolDetailRequests).toEqual([]);

		await page.goBack();
		await expect(page).toHaveURL(/\/people\/person-prolific$/);
		await expect(page.getByText("Showing 1–24 of 250", { exact: true })).toBeVisible();
		expect(profileRequests).toEqual([1, 2, 1]);
		expect(toolDetailRequests).toEqual([]);
	});
});
