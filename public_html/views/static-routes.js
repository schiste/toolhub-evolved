// SPDX-License-Identifier: GPL-3.0-or-later
/* The slugs views/static.js can render, split out so the router can recognise a
   static route without importing the pages themselves.

   static.js is the largest module in the app (16.6 KB gzipped). The router only
   ever used STATIC to ask "is this segment a static page?" — a membership test —
   yet importing it for that pulled every word of About, Help, Privacy, Terms,
   the code of conduct and the API page into the first paint, for every visitor,
   including the ones who never open any of them.

   Keep in step with the STATIC map in static.js; tests/unit/view-static.test.mjs
   fails if the two drift apart. */
export const STATIC_SLUGS = [
	"about",
	"help",
	"community",
	"privacy",
	"terms",
	"code-of-conduct",
	"api",
	"mcp-server",
	"rules-of-engagement",
	"health-score",
	"feeds",
	"rss"
];

/** @param {string} slug @returns {boolean} */
export function isStaticSlug(slug) {
	return STATIC_SLUGS.includes(slug);
}
