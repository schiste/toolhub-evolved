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
		await page.route("**/v1/community/**", (route) => {
			const url = new URL(route.request().url());
			if (url.pathname !== "/v1/community/") return route.fallback();
			const currentPage = Number(url.searchParams.get("page") || 1);
			return route.fulfill({
				contentType: "application/json; charset=utf-8",
				json: {
					count: 50,
					page: currentPage,
					pageSize: 24,
					pageCount: 3,
					counts: { people: 50, accounts: 0, unresolvedAttributions: 0 },
					accountSync: { status: "ready", complete: true },
					results: [
						{ kind: "person", person: person(currentPage), identityEvidence: {}, matchBasis: ["identity"] }
					]
				}
			});
		});

		await page.goto(new URL("/people?q=Ada&role=maintainer&project=wikidata.org", smoke.url).href);

		await expect(page.locator('[name="q"]')).toHaveValue("Ada");
		await expect(page.locator('[name="role"]')).toHaveValue("maintainer");
		await expect(page.locator('[name="project"]')).toHaveValue("wikidata.org");
		await expect(page.getByText("Verified Maintainer relationship", { exact: true })).toBeVisible();
		await page.locator("[data-people-pager]").getByRole("button", { name: "2", exact: true }).click();
		await expect(page).toHaveURL(
			/\/people\?(?=.*q=Ada)(?=.*role=maintainer)(?=.*project=wikidata\.org)(?=.*page=2)/
		);
		await expect(page.getByText(/Showing 25–25 of 50 results/)).toBeVisible();

		await page.goBack();
		await expect(page).toHaveURL(
			/\/people\?(?=.*q=Ada)(?=.*role=maintainer)(?=.*project=wikidata\.org)(?!.*page=2)/
		);
		await expect(page.getByText(/Showing 1–1 of 50 results/)).toBeVisible();
	});

	test("renders a retryable directory error and recovers in place", async ({ page }) => {
		let offline = true;
		await page.route("**/v1/community/**", (route) => {
			const url = new URL(route.request().url());
			if (url.pathname !== "/v1/community/") return route.fallback();
			if (offline) return route.fulfill({ status: 503, json: { error: "offline" } });
			return route.fulfill({
				contentType: "application/json; charset=utf-8",
				json: {
					count: 1,
					page: 1,
					pageSize: 24,
					pageCount: 1,
					counts: { people: 1, accounts: 0, unresolvedAttributions: 0 },
					accountSync: { status: "ready", complete: true },
					results: [{ kind: "person", person: person(1), identityEvidence: {}, matchBasis: ["identity"] }]
				}
			});
		});

		await page.goto(new URL("/people?q=Ada", smoke.url).href);
		await expect(page.getByRole("alert")).toContainText("Community search could not be loaded");

		offline = false;
		await page.getByRole("button", { name: "Retry search" }).click();
		await expect(page.getByText("Ada 1", { exact: true })).toBeVisible();
		await expect(page.getByRole("alert")).toHaveCount(0);
	});
});

test.describe("Unified account evidence", () => {
	const smoke = useSmokeServer();
	const longName = "A very long official account name that remains fully visible to every sighted user";
	const account = {
		id: "42",
		username: longName,
		groups: ["user", "admin"],
		dateJoined: "2024-01-02T00:00:00Z",
		wikimediaGlobalUserId: "9001",
		wikimediaRegisteredAt: "20080403000000",
		personId: "person-42",
		identityLinkStatus: "linked"
	};
	const sync = { status: "ready", complete: true, lastCompletedAt: "2026-08-07T00:00:00Z" };

	test("preserves unified search, account details, legacy URLs, history, and full names", async ({ page }) => {
		await page.route("**/v1/accounts/**", (route) => {
			const url = new URL(route.request().url());
			if (url.pathname === "/v1/accounts/42/") {
				return route.fulfill({ contentType: "application/json; charset=utf-8", json: { ...account, sync } });
			}
			if (url.pathname !== "/v1/accounts/") return route.fallback();
			const currentPage = Number(url.searchParams.get("page") || 1);
			return route.fulfill({
				contentType: "application/json; charset=utf-8",
				json: {
					count: 2313,
					page: currentPage,
					pageSize: 24,
					pageCount: 97,
					results: [account],
					sync
				}
			});
		});
		await page.route("**/v1/community/**", (route) => {
			const url = new URL(route.request().url());
			if (url.pathname !== "/v1/community/") return route.fallback();
			const currentPage = Number(url.searchParams.get("page") || 1);
			return route.fulfill({
				contentType: "application/json; charset=utf-8",
				json: {
					count: 2313,
					page: currentPage,
					pageSize: 24,
					pageCount: 97,
					counts: { people: 0, accounts: 2313, unresolvedAttributions: 0 },
					accountSync: sync,
					results: [{ kind: "account", account, matchBasis: ["official_account"] }]
				}
			});
		});

		await page.goto(new URL("/people?view=accounts&q=official&page=2", smoke.url).href);

		await expect(page.getByRole("heading", { name: "Community directory" })).toBeVisible();
		await expect(page.getByText(/Search people, usernames, and tools in one place/)).toBeVisible();
		await expect(page.locator('[name="q"]')).toHaveValue("official");
		await expect(page).toHaveURL(/\/people\?(?=.*q=official)(?=.*page=2)(?!.*view=accounts)/);
		await expect(page.getByText(/Showing 25–25 of 2313 results/)).toBeVisible();
		const name = page.getByText(longName, { exact: true });
		await expect(name).toBeVisible();
		await expect(name).toHaveCSS("white-space", "normal");

		await name.click();
		await expect(page).toHaveURL(/\/people\?(?=.*q=official)(?=.*page=2)(?=.*account=42)/);
		await expect(page.getByText("Wikimedia global user ID", { exact: true })).toBeVisible();
		await expect(page.getByRole("link", { name: "Open linked public person" })).toHaveAttribute(
			"href",
			"/people/person-42"
		);

		await page.goBack();
		await expect(page.locator('[name="q"]')).toHaveValue("official");
		await expect(page).toHaveURL(/\/people\?(?=.*q=official)(?=.*page=2)/);
	});

	test("distinguishes a failed unified request from zero results and recovers", async ({ page }) => {
		let offline = true;
		await page.route("**/v1/community/**", (route) => {
			if (offline) return route.fulfill({ status: 503, json: { error: "offline" } });
			return route.fulfill({
				contentType: "application/json; charset=utf-8",
				json: {
					count: 1,
					page: 1,
					pageSize: 24,
					pageCount: 1,
					counts: { people: 0, accounts: 1, unresolvedAttributions: 0 },
					accountSync: sync,
					results: [{ kind: "account", account, matchBasis: ["official_account"] }]
				}
			});
		});

		await page.goto(new URL("/people?q=official", smoke.url).href);
		await expect(page.getByRole("alert")).toContainText("Community search could not be loaded");
		await expect(page.getByText(/0 results/)).toHaveCount(0);

		offline = false;
		await page.getByRole("button", { name: "Retry search" }).click();
		await expect(page.getByText(longName, { exact: true })).toBeVisible();
		await expect(page.getByRole("alert")).toHaveCount(0);
	});
});
