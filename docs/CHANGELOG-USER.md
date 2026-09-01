<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: the-deploy-that-checks-itself -->
<!-- Release title: The Deploy That Checks Itself -->
<!-- Source range: ea9baf5..ab04a445 (6 commits) -->

# What's New for Users

- Nothing on the site looks different this time. This release is entirely about the site noticing when something is wrong before you do — which is worth saying out loud, because the previous release shipped a fault that a visitor found first: the new Data layer page served its own error state for the half-minute after going live, and nothing in the deploy was watching.
- A release is no longer finished when the files are copied across. The deploy now asks the live site four questions — is it ready, does the catalogue answer, does a real feature work, is the write guard still refusing what it should refuse — and if any answer is wrong it stops and names the version to go back to. Previously the deploy reported success as soon as the copy finished, so a broken release announced itself as a good one.
- Between releases the site is now checked every fifteen minutes rather than whenever somebody happens to look. An outage on a Sunday afternoon used to be noticed by whoever tried to use the site; now it is noticed by the check.
- The site will now only answer to its own address. A request arriving under some other hostname is refused outright instead of being served, which closes a small but real way of making the site's own links point somewhere else.
- Every one of the 2,523 pieces of interface text now ships with a note explaining it to translators — what it means, where it appears, and what each inserted value is. That is the standard translatewiki expects before a language can be worked on at all, and until now most of the catalogue had a placeholder instead of an explanation.
- A language can also no longer be published half-finished. A translation file has to cover the complete set of messages, with nothing left blank and every inserted value accounted for, or it does not ship. A partial translation is worse than none: it puts two languages on the same screen.
- The libraries the site is built on are now checked for known vulnerabilities on every change, in both the JavaScript and the Python toolchains. Six advisories were outstanding when that check was first switched on. All six are now cleared.
