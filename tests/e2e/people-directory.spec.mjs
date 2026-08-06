// SPDX-License-Identifier: GPL-3.0-or-later
import { expect, test } from "@playwright/test";
import { useSmokeServer } from "./harness.mjs";

function person(index) {
	return {
		id: `person-${index}`,
		displayName: `Ada ${index}`,
		identityQuality: "stable_id",
		profile: {},
		activity: { relatedToolCount: 3 },
		relationshipSummary: {
			types: ["author", "maintainer"],
			verifiedTypes: ["maintainer"]
		}
	};
}

test.describe("People directory", () => {
	const smoke = useSmokeServer();

	test("restores URL filters, preserves them across paging, and supports browser history", async ({ page }) => {
		await page.route("**/v1/people/**", (route) => {
			const url = new URL(route.request().url());
			if (url.pathname === "/v1/people/attributions/") {
				return route.fulfill({
					contentType: "application/json; charset=utf-8",
					json: { count: 0, page: 1, pageSize: 10, pageCount: 1, results: [] }
				});
			}
			if (url.pathname !== "/v1/people/") return route.fallback();
			const currentPage = Number(url.searchParams.get("page") || 1);
			return route.fulfill({
				contentType: "application/json; charset=utf-8",
				json: {
					count: 50,
					page: currentPage,
					pageSize: 24,
					pageCount: 3,
					results: [person(currentPage)]
				}
			});
		});

		await page.goto(new URL("/people?q=Ada&role=maintainer&project=wikidata.org", smoke.url).href);

		await expect(page.locator('[name="q"]')).toHaveValue("Ada");
		await expect(page.locator('[name="role"]')).toHaveValue("maintainer");
		await expect(page.locator('[name="project"]')).toHaveValue("wikidata.org");
		await expect(page.getByText("Verified: Maintainer", { exact: true })).toBeVisible();
		await page.locator("[data-people-pager]").getByRole("button", { name: "2", exact: true }).click();
		await expect(page).toHaveURL(
			/\/people\?(?=.*q=Ada)(?=.*role=maintainer)(?=.*project=wikidata\.org)(?=.*page=2)/
		);
		await expect(page.getByText(/Showing 25–25 of 50 people/)).toBeVisible();

		await page.goBack();
		await expect(page).toHaveURL(
			/\/people\?(?=.*q=Ada)(?=.*role=maintainer)(?=.*project=wikidata\.org)(?!.*page=2)/
		);
		await expect(page.getByText(/Showing 1–1 of 50 people/)).toBeVisible();
	});

	test("renders a retryable directory error and recovers in place", async ({ page }) => {
		let offline = true;
		await page.route("**/v1/people/**", (route) => {
			const url = new URL(route.request().url());
			if (url.pathname === "/v1/people/attributions/") {
				return route.fulfill({
					contentType: "application/json; charset=utf-8",
					json: { count: 0, page: 1, pageSize: 10, pageCount: 1, results: [] }
				});
			}
			if (url.pathname !== "/v1/people/") return route.fallback();
			if (offline) return route.fulfill({ status: 503, json: { error: "offline" } });
			return route.fulfill({
				contentType: "application/json; charset=utf-8",
				json: { count: 1, page: 1, pageSize: 24, pageCount: 1, results: [person(1)] }
			});
		});

		await page.goto(new URL("/people?q=Ada", smoke.url).href);
		await expect(page.getByRole("alert")).toContainText("People search could not be loaded");

		offline = false;
		await page.getByRole("button", { name: "Retry search" }).click();
		await expect(page.getByText("Ada 1", { exact: true })).toBeVisible();
		await expect(page.getByRole("alert")).toHaveCount(0);
	});
});
