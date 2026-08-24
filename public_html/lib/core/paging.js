// SPDX-License-Identifier: GPL-3.0-or-later
/**
 * The page sizes every "how many per page" control offers.
 *
 * Fibonacci from 8 to 144. The gaps widen as the numbers grow, which is the
 * shape a size picker wants: the step from 8 to 13 is a decision a reader
 * makes, the step from 130 to 144 is not. The sequence below 8 is dropped --
 * 1, 1, 2, 3 and 5 are all shorter than one row of the card grid, and the
 * literal sequence opens with 1 twice, which would render two options carrying
 * the same value.
 *
 * 144 is also the ceiling the read APIs enforce: `MAX_PAGE_SIZE` in
 * `backend/catalog_read.py` and the `maximum=` arguments in `v1_accounts.py`
 * and `v1_people.py`. Those clamp silently rather than rejecting, so an option
 * larger than the ceiling would return a short page while the pager kept
 * dividing the total by the size that was asked for -- every page past the
 * clamp unreachable, with nothing on screen to say so. Raise both ends
 * together or neither.
 */
export const PAGE_SIZE_OPTIONS = Object.freeze([8, 13, 21, 34, 55, 89, 144]);

/**
 * The size used when the URL carries no preference, or one we do not offer.
 *
 * Third in the list rather than first: a default at the bottom of the range
 * makes every other choice a widening, and readers who never touch the control
 * would get the narrowest view of the catalogue by default.
 */
export const DEFAULT_PAGE_SIZE = 21;

/**
 * Resolve a URL-supplied page size to one this application actually offers.
 *
 * A value outside the list falls back to the default rather than being clamped
 * to the nearest offered size. Falling back is the honest answer: the control
 * can only display a size it has an option for, so a clamped value would leave
 * the select showing one number while the page held another.
 * @param {string | null} value
 * @returns {number}
 */
export function resolvePageSize(value) {
	// Stryker disable next-line StringLiteral: when value is null the fallback is parsed by Number.parseInt; "" and any non-numeric sentinel both yield NaN (→ default page size) — equivalent.
	const parsed = Number.parseInt(value ?? "", 10);
	return PAGE_SIZE_OPTIONS.includes(parsed) ? parsed : DEFAULT_PAGE_SIZE;
}
