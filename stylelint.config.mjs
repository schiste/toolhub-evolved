// SPDX-License-Identifier: GPL-3.0-or-later
// Properties that must reference a design token (var(--…)) rather than a raw
// value, enforced by scale-unlimited/declaration-strict-value. Spacing and gap
// use regex (/^margin/, /^padding/, /gap$/) so EVERY physical/logical longhand
// is covered — a raw `margin-inline-end: 12px` or `row-gap: 8px` can't slip
// through a gap in an enumerated list. Deliberately NOT enforced: width/height/
// grid/inset (one-off layout dimensions, no token family) and border-radius
// (circles legitimately use `50%`); enforcing those would be noise, not drift.
const tokenizedProperties = [
	"/color$/",
	"/^margin/",
	"/^padding/",
	"/gap$/",
	"background",
	"background-color",
	"border",
	"border-color",
	"border-top",
	"border-bottom",
	"border-inline-start",
	"box-shadow",
	"color",
	"fill",
	"font-size",
	"text-decoration-color"
];

export default {
	extends: ["stylelint-config-standard"],
	plugins: ["stylelint-declaration-strict-value"],
	rules: {
		"alpha-value-notation": "number",
		"at-rule-empty-line-before": null,
		"color-function-notation": "modern",
		"color-hex-length": "long",
		"color-named": "never",
		"color-no-hex": true,
		"custom-property-empty-line-before": null,
		"custom-property-pattern": "^[a-z][a-z0-9-]*$",
		"declaration-block-no-redundant-longhand-properties": true,
		"declaration-block-single-line-max-declarations": 8,
		"declaration-no-important": true,
		"declaration-property-value-disallowed-list": {
			"/^transition/": ["/\\ball\\b/"]
		},
		"font-family-no-missing-generic-family-keyword": true,
		"function-disallowed-list": ["rgb", "rgba", "hsl", "hsla"],
		"function-url-quotes": "always",
		"length-zero-no-unit": true,
		"max-nesting-depth": 3,
		"media-feature-range-notation": "context",
		"no-descending-specificity": true,
		"property-no-vendor-prefix": true,
		"rule-empty-line-before": null,
		"scale-unlimited/declaration-strict-value": [
			tokenizedProperties,
			{
				ignoreFunctions: true,
				ignoreValues: ["auto", "currentColor", "inherit", "none", "normal", "transparent", "unset"]
			}
		],
		"selector-class-pattern": [
			"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*(?:__[a-z0-9]+(?:-[a-z0-9]+)*|--[a-z0-9]+(?:-[a-z0-9]+)*|-[a-z0-9]+)*$",
			{ resolveNestedSelectors: true }
		],
		"selector-id-pattern": "^[a-z][a-z0-9-]*$",
		"selector-max-id": 1,
		"selector-max-universal": 0,
		"shorthand-property-no-redundant-values": true,
		"value-keyword-case": ["lower", { ignoreKeywords: ["currentColor"] }]
	},
	overrides: [
		{
			files: ["public_html/styles/tokens.css"],
			rules: {
				"color-no-hex": null,
				"function-disallowed-list": null,
				"scale-unlimited/declaration-strict-value": null
			}
		}
	]
};
