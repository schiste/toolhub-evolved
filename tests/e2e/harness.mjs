// SPDX-License-Identifier: GPL-3.0-or-later
// Shared Playwright lifecycle: boot the deterministic smoke server once per
// describe block and tear it down afterwards. Returns a ref whose `.url` is
// populated by the time tests run.
import { test } from "@playwright/test";
import { startSmokeServer } from "../../tools/smoke-server.mjs";

export function useSmokeServer() {
	const ref = { url: "" };
	let server;
	test.beforeAll(async () => {
		server = await startSmokeServer({ port: 0 });
		ref.url = server.url;
	});
	test.afterAll(async () => {
		if (!server) return;
		await new Promise((resolve, reject) => {
			server.server.close((error) => (error ? reject(error) : resolve()));
		});
	});
	return ref;
}
