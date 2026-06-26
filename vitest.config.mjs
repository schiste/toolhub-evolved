// SPDX-License-Identifier: GPL-3.0-or-later
// Vitest config. happy-dom gives unit tests a real DOM (document/localStorage/
// window) so view/organism code is testable without hand-rolled stubs, and the
// V8 coverage provider backs both the coverage gate and Stryker's vitest-runner
// (per-test coverage → fast incremental mutation across the whole app).
import { defineConfig } from "vitest/config";

export default defineConfig({
	test: {
		environment: "happy-dom",
		include: ["tests/unit/**/*.test.mjs"],
		coverage: {
			provider: "v8",
			include: ["public_html/**/*.js"],
			reporter: ["text", "html"]
		}
	}
});
