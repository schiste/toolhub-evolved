// SPDX-License-Identifier: GPL-3.0-or-later
// Accessibility INTERACTION tests (keyboard, focus, escape, traps, landmarks) —
// complements the axe static scan in smoke.spec.mjs.
import { expect, test } from "@playwright/test";
import { useSmokeServer } from "./harness.mjs";

test.describe("accessibility interactions", () => {
	const smoke = useSmokeServer();

	async function open(page, path = "/") {
		await page.goto(new URL(path, smoke.url).href);
		await expect(page.locator("#view")).toBeVisible();
	}

	test("skip link is the first stop and shows a focus ring", async ({ page }) => {
		await open(page);
		const skip = page.locator(".skip");
		await expect(skip).toHaveAttribute("href", "#view");
		// Seed focus, step off, then Tab back via the keyboard: proves .skip is the
		// first tabbable AND engages :focus-visible (which programmatic focus won't).
		await skip.focus();
		await page.keyboard.press("Shift+Tab");
		await page.keyboard.press("Tab");
		await expect(skip).toBeFocused();
		expect(await skip.evaluate((el) => el.matches(":focus-visible"))).toBe(true);
	});

	test("landmarks are present with accessible names", async ({ page }) => {
		await open(page);
		await expect(page.getByRole("banner")).toBeVisible();
		await expect(page.getByRole("navigation", { name: "Primary", exact: true })).toBeVisible();
		await expect(page.getByRole("main")).toBeVisible();
		await expect(page.getByRole("contentinfo")).toBeVisible();
	});

	test("icon-bearing controls all have an accessible name", async ({ page }) => {
		await open(page);
		const controls = page.locator("button:has(svg), a:has(svg)");
		const count = await controls.count();
		expect(count).toBeGreaterThan(0);
		for (let i = 0; i < count; i += 1) {
			const name = await controls
				.nth(i)
				.evaluate(
					(el) =>
						(el.textContent || "").trim() || el.getAttribute("aria-label") || el.getAttribute("title") || ""
				);
			expect(name, `control #${i} has no accessible name`).not.toBe("");
		}
	});

	test("Escape closes the language menu and resets aria-expanded", async ({ page }) => {
		await open(page);
		const btn = page.locator("#lang-btn");
		const menu = page.locator("#lang-menu");
		await btn.click();
		await expect(menu).not.toHaveAttribute("hidden", /.*/);
		await expect(btn).toHaveAttribute("aria-expanded", "true");
		await expect(page.locator(".lang__opt").first()).toBeFocused();
		await page.keyboard.press("Escape");
		await expect(menu).toHaveAttribute("hidden", /.*/);
		await expect(btn).toHaveAttribute("aria-expanded", "false");
	});

	test("Escape closes the account menu when experiments are on", async ({ page }) => {
		await open(page);
		await page.locator("#exp-toggle").click();
		const btn = page.locator("#acct-btn");
		await expect(btn).toBeVisible();
		await btn.click();
		const menu = page.locator("#acct-menu");
		await expect(menu).not.toHaveAttribute("hidden", /.*/);
		await expect(btn).toHaveAttribute("aria-expanded", "true");
		await page.keyboard.press("Escape");
		await expect(menu).toHaveAttribute("hidden", /.*/);
		await expect(btn).toHaveAttribute("aria-expanded", "false");
	});

	test("quick-view traps focus and Escape restores it to the opener", async ({ page }) => {
		await open(page, "/search");
		const opener = page.locator(".tcard__title").first();
		await expect(opener).toBeVisible();
		await opener.click();
		const qv = page.locator("#qv");
		await expect(qv).not.toHaveClass(/hidden/);
		await expect(qv).toHaveAttribute("aria-hidden", "false");
		// Focus starts inside the dialog and stays trapped across several Tabs.
		await expect(page.locator(".qv__x")).toBeFocused();
		for (let i = 0; i < 6; i += 1) {
			await page.keyboard.press("Tab");
			expect(await page.evaluate(() => document.querySelector("#qv").contains(document.activeElement))).toBe(
				true
			);
		}
		await page.keyboard.press("Escape");
		await expect(qv).toHaveClass(/hidden/);
		await expect(opener).toBeFocused();
	});
});
