// SPDX-License-Identifier: GPL-3.0-or-later
export default {
	expect: {
		timeout: 5000
	},
	forbidOnly: true,
	fullyParallel: false,
	reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],
	retries: 0,
	testDir: "tests/e2e",
	timeout: 30000,
	use: {
		browserName: "chromium",
		ignoreHTTPSErrors: false,
		trace: "retain-on-failure"
	}
};
