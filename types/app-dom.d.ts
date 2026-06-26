// SPDX-License-Identifier: GPL-3.0-or-later
// Pragmatic global augmentations for type-checking this vanilla-JS SPA under
// `tsc --checkJs`. Deliberately narrow: they describe real, intentional patterns
// in the app, not a blanket relaxation.

interface Element {
	// The force-graph organism stores its imperative handle on its container node
	// (write-only bookkeeping; never read back, so its shape is opaque here).
	forceGraphHandle?: unknown;
}

interface EventTarget {
	// Every delegated click/keydown handler in this app fires on an Element target,
	// so `e.target.closest(...)` / `e.target.id` are always valid in our handlers.
	closest(selectors: string): Element | null;
	readonly id: string;
}
