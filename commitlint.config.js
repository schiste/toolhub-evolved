// SPDX-License-Identifier: GPL-3.0-or-later
// Commit hygiene over the push range (run in CI). Intentionally lenient: accepts
// Conventional Commits OR a clean capitalized imperative subject — it enforces
// length/punctuation/non-emptiness, not a mandated type vocabulary.
export default {
	// Treat the whole header as the subject so non-Conventional (clean imperative)
	// subjects are accepted; we enforce hygiene, not a mandated type vocabulary.
	parserPreset: { parserOpts: { headerPattern: /^(.+)$/, headerCorrespondence: ["subject"] } },
	rules: {
		"header-max-length": [2, "always", 72],
		"subject-empty": [2, "never"],
		"subject-full-stop": [2, "never", "."],
		"body-leading-blank": [2, "always"]
	}
};
