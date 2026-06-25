// SPDX-License-Identifier: GPL-3.0-or-later
import js from "@eslint/js";
import globals from "globals";
import importPlugin from "eslint-plugin-import";
import sonarjs from "eslint-plugin-sonarjs";
import unicorn from "eslint-plugin-unicorn";

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
	"unicorn/template-indent": "error"
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
			"import/no-cycle": ["error", { maxDepth: 8 }]
		}
	},
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
	}
];
