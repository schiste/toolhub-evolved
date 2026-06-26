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
		setupFiles: ["./tests/unit/_storage-setup.mjs"],
		coverage: {
			provider: "v8",
			include: ["public_html/**/*.js"],
			reporter: ["text", "html"],
			// Honest floor (a ratchet), not a vanity 100. The app is at 100% MUTATION;
			// branch coverage caps below 100 because documented equivalent-mutant
			// defensive guards (e.g. `if (!el)` that never fires) are unreachable —
			// forcing them to "execute" would mean deleting safety code.
			thresholds: { statements: 98, branches: 95, functions: 99, lines: 99 }
		}
	}
});
