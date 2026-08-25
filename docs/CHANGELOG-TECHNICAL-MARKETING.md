<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: launch-note-affordance -->
<!-- Release title: The 2021 Note, Now Readable -->
<!-- Source range: a37b8649..98f499d8 (1 commit, promoted as one) -->

# Technical and Marketing Notes

- The 2021 annotation shipped as a `title` attribute and was verified the wrong way: production checks confirmed the attribute was present, the pointer reached the element, and `cursor: help` computed correctly. All true, and all beside the point -- `title` needs about a second of motionless hover, ignores clicks, does not exist on touch, and sat on an element with `tabIndex` -1. Asserting on an attribute is not the same as asserting on an affordance.
- It is now a `<button>` mark plus an absolutely positioned bubble revealed by `:hover` and `:focus-within` on the wrapper, with no JavaScript. `:focus-within` rather than `:focus-visible` is load-bearing: `:focus-visible` deliberately excludes mouse focus, so a click on the mark would not have opened it and the reported bug would have half survived its own fix.
- The button's accessible name is the note text, which avoids an `aria-describedby` id that two charts on one page would collide on. That makes the visible bubble a second copy of words already announced, so it carries `aria-hidden="true"` and `role="tooltip"`. Keyboard users get the shared focus ring `base.css` already applies to every button.
- The bubble is out of flow and hidden by `visibility` rather than `opacity`: out of flow so opening a note cannot change a row's height, and `visibility` so the closed bubble leaves the hit-test tree instead of silently swallowing clicks meant for the bar underneath.
- Verification was behavioral this time, driven in Chrome against the built CSS: hover opens it, click opens it and it survives the pointer leaving, Tab from a preceding link lands on the mark and opens it, and row heights read 21px in every state. Four unit tests pin the placement, that the mark is a real button carrying the note as its accessible name, and that the bubble is present but not announced twice.
