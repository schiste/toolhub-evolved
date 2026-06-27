// SPDX-License-Identifier: GPL-3.0-or-later
import js from "@eslint/js";
import globals from "globals";
// eslint-plugin-import-x: the maintained fork of eslint-plugin-import, used
// because upstream eslint-plugin-import has no ESLint 10 peer support yet. Same
// `import/*` rule names, so the rule config below is unchanged.
import importPlugin from "eslint-plugin-import-x";
import sonarjs from "eslint-plugin-sonarjs";
import unicorn from "eslint-plugin-unicorn";
import headers from "eslint-plugin-headers";

// ---- Architecture boundaries (replaces the bespoke quality.mjs gate) --------
// Network + persistent storage are browser globals, so they're enforced with
// no-restricted-globals (banned by default, re-allowed per module via ordered
// override blocks). DOM injection is matched structurally with no-restricted-syntax.
const NETWORK_GLOBALS = [
	{ name: "fetch", message: "Network access is only allowed in lib/core/api.js; call apiGet() instead." },
	{ name: "XMLHttpRequest", message: "Network access is only allowed in lib/core/api.js; call apiGet() instead." }
];
const STORAGE_GLOBALS = [
	{ name: "localStorage", message: "Persistent storage belongs in core (store/session/theme/i18n/signals)." },
	{ name: "sessionStorage", message: "Persistent storage belongs in core (store/session/theme/i18n/signals)." }
];
const DOM_INJECTION_SYNTAX = [
	{
		selector: "AssignmentExpression[left.property.name='innerHTML']",
		message: "core/atoms must be DOM-free; return HTML strings for a molecule/organism/view to render."
	},
	{
		selector: "AssignmentExpression[left.property.name='outerHTML']",
		message: "core/atoms must be DOM-free; return HTML strings to render."
	},
	{ selector: "CallExpression[callee.property.name='insertAdjacentHTML']", message: "core/atoms must be DOM-free." },
	{ selector: "CallExpression[callee.property.name='appendChild']", message: "core/atoms must be DOM-free." },
	{ selector: "CallExpression[callee.property.name='replaceChildren']", message: "core/atoms must be DOM-free." },
	{
		selector: "CallExpression[callee.object.name='document'][callee.property.name='createElement']",
		message: "core/atoms must be DOM-free."
	},
	{
		selector: "MemberExpression[object.name='document'][property.name='body']",
		message: "core/atoms must not touch document.body."
	}
];
// Modules that may legitimately use persistent storage.
const STORAGE_CORE = [
	"public_html/lib/core/store.js",
	"public_html/lib/core/session.js",
	"public_html/lib/core/theme.js",
	"public_html/lib/core/i18n.js",
	"public_html/lib/core/signals.js"
];
// Atomic-Design layering: a layer may import equal/lower, never higher.
const LAYER_ZONES = [
	{
		target: "./public_html/lib/core",
		from: [
			"./public_html/lib/atoms",
			"./public_html/lib/molecules",
			"./public_html/lib/organisms",
			"./public_html/views"
		]
	},
	{
		target: "./public_html/lib/atoms",
		from: ["./public_html/lib/molecules", "./public_html/lib/organisms", "./public_html/views"]
	},
	{ target: "./public_html/lib/molecules", from: ["./public_html/lib/organisms", "./public_html/views"] },
	{ target: "./public_html/lib/organisms", from: ["./public_html/views"] }
];
const LICENSE_HEADER = { source: "string", style: "line", content: "SPDX-License-Identifier: GPL-3.0-or-later" };

const sharedRules = {
	...js.configs.recommended.rules,
	"array-callback-return": "error",
	"block-scoped-var": "error",
	curly: ["error", "multi-line", "consistent"],
	eqeqeq: ["error", "always"],
	"func-style": ["error", "declaration", { allowArrowFunctions: true }],
	"guard-for-in": "error",
	"max-depth": ["error", 5],
	"max-lines-per-function": ["error", { max: 240, skipBlankLines: true, skipComments: true }],
	"max-nested-callbacks": ["error", 4],
	"max-params": ["error", 8],
	"no-alert": "error",
	"no-console": "error",
	"no-debugger": "error",
	"no-duplicate-imports": "error",
	"no-else-return": ["error", { allowElseIf: false }],
	"no-empty": ["error", { allowEmptyCatch: true }],
	"no-eval": "error",
	"no-extend-native": "error",
	"no-implicit-coercion": "error",
	"no-implied-eval": "error",
	"no-lone-blocks": "error",
	"no-loop-func": "error",
	"no-multi-assign": "error",
	"no-new-func": "error",
	"no-object-constructor": "error",
	"no-param-reassign": "error",
	"no-promise-executor-return": "error",
	"no-return-await": "error",
	"no-script-url": "error",
	"no-self-compare": "error",
	"no-sequences": "error",
	"no-template-curly-in-string": "error",
	"no-unmodified-loop-condition": "error",
	"no-unneeded-ternary": "error",
	"no-unreachable-loop": "error",
	"no-unused-expressions": "error",
	"no-unused-vars": ["error", { args: "none", caughtErrors: "none", vars: "all" }],
	"no-use-before-define": ["error", { functions: false, classes: true, variables: true }],
	"no-useless-call": "error",
	"no-useless-computed-key": "error",
	"no-useless-concat": "error",
	"no-useless-rename": "error",
	"no-var": "error",
	"object-shorthand": ["error", "always"],
	"operator-assignment": ["error", "always"],
	"prefer-const": ["error", { destructuring: "all" }],
	"prefer-template": "error",
	"require-atomic-updates": "error",
	"sonarjs/cognitive-complexity": ["error", 45],
	"sonarjs/no-all-duplicated-branches": "error",
	"sonarjs/no-collapsible-if": "error",
	"sonarjs/no-collection-size-mischeck": "error",
	"sonarjs/no-duplicated-branches": "error",
	"sonarjs/no-gratuitous-expressions": "error",
	"sonarjs/no-identical-conditions": "error",
	"sonarjs/no-identical-expressions": "error",
	"sonarjs/no-ignored-return": "error",
	"sonarjs/no-inverted-boolean-check": "error",
	"sonarjs/no-nested-assignment": "error",
	"sonarjs/no-redundant-boolean": "error",
	"sonarjs/no-redundant-jump": "error",
	"sonarjs/no-same-line-conditional": "error",
	"sonarjs/no-small-switch": "error",
	"sonarjs/no-unused-vars": "off",
	"sonarjs/prefer-immediate-return": "error",
	"unicorn/better-regex": "error",
	"unicorn/consistent-destructuring": "error",
	"unicorn/error-message": "error",
	"unicorn/escape-case": "error",
	"unicorn/explicit-length-check": "error",
	"unicorn/new-for-builtins": "error",
	"unicorn/no-abusive-eslint-disable": "error",
	"unicorn/no-array-callback-reference": "error",
	"unicorn/no-await-expression-member": "error",
	"unicorn/no-console-spaces": "error",
	"unicorn/no-hex-escape": "error",
	"unicorn/no-instanceof-array": "error",
	"unicorn/no-invalid-fetch-options": "error",
	"unicorn/no-lonely-if": "error",
	"unicorn/no-negated-condition": "error",
	"unicorn/no-new-array": "error",
	"unicorn/no-new-buffer": "error",
	"unicorn/no-unreadable-array-destructuring": "error",
	"unicorn/no-unnecessary-await": "error",
	"unicorn/no-useless-fallback-in-spread": "error",
	"unicorn/no-useless-length-check": "error",
	"unicorn/no-useless-promise-resolve-reject": "error",
	"unicorn/no-useless-spread": "error",
	"unicorn/no-useless-switch-case": "error",
	"unicorn/prefer-array-find": "error",
	"unicorn/prefer-array-flat": "error",
	"unicorn/prefer-array-flat-map": "error",
	"unicorn/prefer-array-index-of": "error",
	"unicorn/prefer-array-some": "error",
	"unicorn/prefer-default-parameters": "error",
	"unicorn/prefer-includes": "error",
	"unicorn/prefer-logical-operator-over-ternary": "error",
	"unicorn/prefer-modern-dom-apis": "error",
	"unicorn/prefer-negative-index": "error",
	"unicorn/prefer-node-protocol": "error",
	"unicorn/prefer-number-properties": "error",
	"unicorn/prefer-optional-catch-binding": "error",
	"unicorn/prefer-query-selector": "error",
	"unicorn/prefer-set-has": "error",
	"unicorn/prefer-spread": "error",
	"unicorn/prefer-string-replace-all": "error",
	"unicorn/prefer-string-slice": "error",
	"unicorn/prefer-string-starts-ends-with": "error",
	"unicorn/prefer-string-trim-start-end": "error",
	"unicorn/require-array-join-separator": "error",
	"unicorn/require-number-to-fixed-digits-argument": "error",
	"unicorn/template-indent": "error",
	"no-warning-comments": ["error", { terms: ["todo", "fixme", "xxx", "hack"], location: "anywhere" }],
	"no-restricted-properties": [
		"error",
		{ object: "document", property: "write", message: "document.write() is forbidden." }
	]
};

const importRules = {
	"import/extensions": ["error", "always", { ignorePackages: true }],
	"import/no-absolute-path": "error",
	"import/no-duplicates": "error",
	"import/no-self-import": "error",
	"import/no-unresolved": ["error", { commonjs: false, caseSensitive: true }]
};

export default [
	{
		ignores: [
			"node_modules/**",
			".quality/**",
			"playwright-report/**",
			"test-results/**",
			"coverage/**",
			"htmlcov/**"
		]
	},
	// License header on first-party source.
	{
		files: ["public_html/**/*.js", "tools/**/*.mjs", "tests/**/*.mjs"],
		plugins: { headers },
		rules: { "headers/header-format": ["error", LICENSE_HEADER] }
	},
	// Browser app: layering, no network/storage by default, node built-ins banned.
	{
		files: ["public_html/**/*.js"],
		languageOptions: {
			ecmaVersion: "latest",
			sourceType: "module",
			globals: globals.browser
		},
		plugins: {
			import: importPlugin,
			sonarjs,
			unicorn
		},
		rules: {
			...sharedRules,
			...importRules,
			"import/no-cycle": ["error", { maxDepth: 8 }],
			"import/no-restricted-paths": ["error", { zones: LAYER_ZONES }],
			"no-restricted-imports": [
				"error",
				{
					patterns: [
						"node:*",
						"fs",
						"path",
						"http",
						"https",
						"crypto",
						"child_process",
						"os",
						"url",
						"util",
						"stream"
					]
				}
			],
			"no-restricted-globals": ["error", ...NETWORK_GLOBALS, ...STORAGE_GLOBALS]
		}
	},
	// core + atoms must be DOM-free.
	{
		files: ["public_html/lib/core/**/*.js", "public_html/lib/atoms/**/*.js"],
		rules: { "no-restricted-syntax": ["error", ...DOM_INJECTION_SYNTAX] }
	},
	// api.js is the sole network module (storage still banned).
	{
		files: ["public_html/lib/core/api.js"],
		rules: { "no-restricted-globals": ["error", ...STORAGE_GLOBALS] }
	},
	// Core storage modules may use persistent storage (network still banned).
	{
		files: STORAGE_CORE,
		rules: { "no-restricted-globals": ["error", ...NETWORK_GLOBALS] }
	},
	// Tooling, tests, and config run in Node.
	{
		files: ["*.js", "tools/**/*.mjs", "tests/**/*.mjs", "playwright.config.mjs"],
		languageOptions: {
			ecmaVersion: "latest",
			sourceType: "module",
			globals: { ...globals.node, ...globals.browser }
		},
		plugins: {
			import: importPlugin,
			sonarjs,
			unicorn
		},
		rules: {
			...sharedRules,
			...importRules,
			"no-console": "off"
		}
	},
	// Unit tests legitimately use a few patterns the strict rules flag only because
	// of the test context: stubbing timers/globals (no-promise-executor-return,
	// require-atomic-updates), javascript:-URL fixtures that verify URL sanitizing
	// (no-script-url), and cache-busting dynamic imports of the side-effecting entry
	// module (import/no-unresolved). Product code keeps all of these — relaxed for
	// unit tests only.
	{
		files: ["tests/unit/**/*.test.mjs"],
		rules: {
			"no-promise-executor-return": "off",
			"require-atomic-updates": "off",
			"no-script-url": "off",
			"import/no-unresolved": "off"
		}
	}
];
