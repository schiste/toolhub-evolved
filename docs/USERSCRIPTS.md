# User-Script Directory

A wiki's user space is where its tooling actually lives. Anyone can create
`User:<name>/something.js`, and thousands of people have; the wiki records every
one of those pages and nothing about what they are. This subsystem reads that
corpus through the public Action API and turns it into a directory that answers
the question the wiki cannot: **how many distinct scripts are there, who uses
each one, and which of them enough people already load to be worth promoting to
a gadget.**

It is a pilot. `fr.wikipedia.org` is the only wiki configured today, and every
number quoted below is measured on it. Nothing here is wiki-specific by design —
the one place a wiki gets special treatment is `LOCAL_LOADERS`, and that is
explicit and per wiki — but no second wiki has been swept, so treat the
thresholds as calibrated against frwiki and nothing else.

Everything is read through anonymous `GET`s with a contact User-Agent. There are
no writes, no authenticated endpoints, and no credentials anywhere in this
subsystem.

## What counts as a script

**The content model decides, never the file suffix.** `User:Penquista/monobook.css`
on frwiki contains JavaScript. MediaWiki records a content model per page,
CirrusSearch indexes it, and asking for it directly is the only route that
agrees with what the parser does. An enumeration that trusts the suffix both
misses that page and miscategorises it.

Within the pages that are JavaScript, most are not tools. `backend.userscripts`
classifies a body into one of four roles:

| Role     | What it is                                           |
| -------- | ---------------------------------------------------- |
| `empty`  | no code at all                                       |
| `stub`   | at most `STUB_MAX_LINES` (2) lines of code           |
| `shim`   | loader calls plus at most `SHIM_MAX_OTHER_LINES` (3) |
| `script` | everything else                                      |

Only `script` pages become directory candidates. That is not a tidiness rule: in
a full pass over frwiki's 9,919 user-space JavaScript pages, the largest group of
byte-identical pages was 1,045 empty ones, and the most-copied non-empty page was
43 bytes of `importScript` pointing at a gadget. A census that counts pages
measures the wrong thing.

CSS-model pages are enumerated — they have to be, because a `.css` page can hold
JavaScript — but a page whose body is really CSS never earns a directory entry.
There is no stylesheet tier and no plan for one.

**Analysis runs on the body with comments removed.** `fingerprint()` hashes the
comment-stripped, whitespace-normalized text for exactly one reason: Popups
appears on frwiki as three byte-exact groups that differ only in their credit
comments and their load mechanism. Hashing raw text reports one script as three.

**Loader verbs are per wiki.** The global verbs (`importScript`, `mw.loader.load`
and friends) are recognized everywhere. frwiki additionally defines its own
import verb, `obtenir`, in `MediaWiki:Common.js`, and 101 pages use it; it
resolves to a gadget page by a naming convention that exists only there. Nothing
is guessed — a local verb is declared in `LOCAL_LOADERS` for a specific wiki or
it is not recognized at all. `importStylesheet` is parsed but flagged
`is_stylesheet`, so loading somebody's CSS is not counted as loading their
script.

## Discovery and reading

`backend.userscript_census` asks the search index for pages in namespace 2 whose
content model is `javascript` or `css`. The alternative — walking
`list=allpages` and filtering on the suffix — reads several hundred thousand
titles to find nine thousand pages, and gets the suffix question wrong at the end
of it.

Two API limits shape the code:

- **Search refuses an offset of 10,000 or more** (`SEARCH_OFFSET_CAP`). A model
  with more hits than that cannot be walked in one query, so the count is
  reported and `enumeration_complete` goes false rather than the walk quietly
  stopping. An enumeration that silently truncates at 10,000 looks exactly like
  a complete one.
- **A response is capped at 2 MB**, which a batch of large scripts can exceed. A
  batch that comes back too large is split rather than dropped. Pages are read
  `CONTENT_BATCH` (20) at a time.

Nothing here fetches on its own. Every Action API call goes through the existing
`WikimediaClient`, which validates the host before each request.

## Sweep and watch

`backend.userscript_sweep` runs the same machinery two ways. A **sweep** walks
the search index for every page of a script content model, and is how a wiki
first enters the directory. A **watch** follows `recentchanges` since the stored
cursor, and is how it stays current. Between them they are the difference between
a census and a directory.

Neither is transactional across the wiki and neither pretends to be. A pass that
runs for minutes over a live wiki will see pages created, edited and deleted
underneath it. Per `backend.job_contract`, a page that cannot be read is a
durable observation — a row — and only a pass that could not run at all is a job
failure. A complete enumeration also tombstones the pages it no longer lists, and
deleted pages are excluded from the directory: a script the wiki no longer serves
cannot become a gadget, and leaving it in would let it go on claiming to be the
original of the pages that copied it.

**Work is skipped by revision id.** Re-reading a wiki costs thousands of
requests; re-analysing a stored page costs microseconds. A page whose revision
has not moved is left untouched, which is what makes an hourly watch cheap enough
to schedule at all. Bodies are stored so re-analysis stays free, capped at
`MAX_STORED_BODY` (512 KiB) per page — a limit about what is worth keeping, not
about what fits.

**Creation dates come from the Wiki Replicas; enumeration order is the
fallback.** The collapse's "earliest page wins" rule only ever compares two
pages, so it needs an order rather than a calendar — but the order has to be a
real one. Three things supply it, in descending order of authority:

1. `created_at_wiki`, the page's oldest revision timestamp, read from the Wiki
   Replicas by `backend.userscript_creation_dates`. One query returns every
   user-space `.js`/`.css` page on a wiki; frwiki's whole corpus comes back in
   about a second. Only a title and a timestamp are read — the `revision` table
   also carries actor ids and edit comments, and neither is selected.
2. `discovery_rank`, the order the census enumerated the page in. This is
   creation order because the search asks for `create_timestamp_asc`; before
   that it was CirrusSearch relevance, which had nothing to say about which page
   came first.
3. Title, to break exact ties, so the directory names the same original twice
   over identical data.

A page with no creation date sorts _behind_ every page that has one. That is the
weaker claim and the true one: being enumerated first is not evidence of
predating a script from 2003. Every host without `replica.my.cnf` — CI, a
laptop, anything that is not Toolforge — is in that state for its whole corpus
and collapses on enumeration order alone, exactly as before.

The Action API is not the route for this. `prop=revisions` with `rvdir=newer`
is `invalidparammix` for more than one title, so walking histories oldest-first
costs one request per page: measured at 0.542s anonymous, the 2,051 pages the
collapse actually sees are roughly 20 minutes and the full 9,919-page corpus
about an hour and a half. The `letype=create` log is not a shortcut either —
it starts on 2018-06-27, and about 99% of the User-namespace creations in it
are neither `.js` nor `.css`.

## The collapse: originals and instances

`backend.userscript_directory` decides which pages are distinct scripts. On
frwiki, 9,919 user-space JavaScript pages contain 2,051 real scripts, and those
2,051 pages are **1,264 distinct scripts**.

Getting from 2,051 to 1,264 is not deduplication. Two thirds of the difference is
not byte-identical copies at all — it is per-user configuration. 472 people have
a page called `LiveRCparam.js`, each holding their own settings for one shared
tool. Hashing finds none of them, because no two are the same.

What finds them is the filename, in two passes:

1. **Exact copies fold on fingerprint.** Same comment-stripped body, same script.
2. **Crowded names fold on the filename.** When `CROWDED_OWNERS` (5) or more
   distinct owners have a page under the same basename, the later ones are
   presumed to be instances of whatever the first one was, ordered by
   `discovery_rank`.

Five owners is a low threshold and blunt enough to be dangerous on its own — a
genuinely popular name would bury real scripts — so it never fires alone:

> **A page that other people demonstrably load keeps its identity, whatever it is
> called.**

That guard is `INDEPENDENT_DEMAND`, and it is set to 1. It is the one number in
this subsystem that is a judgement rather than a measurement, and the measurement
is what makes the judgement easy. Starting from the 1,229 originals the name rule
leaves on its own:

| Guard threshold | Originals | Rescued |
| --------------- | --------- | ------- |
| ≥ 1 source      | 1,264     | +35     |
| ≥ 2 sources     | 1,239     | +10     |
| ≥ 3 sources     | 1,233     | +4      |
| ≥ 5 sources     | 1,232     | +3      |
| ≥ 25 sources    | 1,229     | +0      |

Nearly the whole effect sits between 1 and 2, so the choice is binary: either
somebody other than the author loading a page is enough to make it its own
script, or it is not. It is. Folding a genuine instance into its tool costs a
duplicate entry that demand ranking pushes to the bottom anyway; the reverse
error is silent and unrecoverable. Protecting reused pages directly is also what
let the crowd threshold drop from 25 owners to 5 — folding 787 pages instead of
670 while losing nothing anybody imports.

The rule validates itself in a way worth stating, because it is the reason to
trust it on a wiki nobody has hand-checked. "Earliest wins" recovers tool authors
without being told what a tool author is: 471 of the 472 `LiveRCparam.js` pages
fold onto EDUCA33E, who wrote LiveRC, and the `AdvancedContribs.js` group folds
onto Maloq, who wrote AdvancedContribs. The 472nd is somebody else's settings
file that another editor loads, so the guard keeps it — which is exactly the case
`INDEPENDENT_DEMAND` exists for.

Each surviving original keeps its folded pages as members, related as
`original`, `copy` (same fingerprint) or `variant` (same name, different body).

**Demand is counted in people, not pages.** Somebody who loads a script from both
`common.js` and `vector.js` is one user of it. Demand is also selected by
_target_ rather than by source wiki, so an import stored against another wiki
that points here still counts — those cross-wiki edges are the strongest argument
any script has for becoming a global gadget. A page loading itself is not demand
for it; a script that installs its own helper subpage would otherwise vote for
itself.

## Tiers

`tier_of` files every original into one of two tiers, and the boundary is one
distinct source rather than a threshold, because the tiers answer different
questions:

- **`active`** — "what could become a gadget". At least one person other than the
  author loads it. Ordered most-loaded first. **603 scripts on frwiki.**
- **`archive`** — "what exists". No importer anybody can see. Ordered oldest
  first, which is the order the cold-storage question is actually asked in.
  **661 scripts on frwiki.**

Nothing is dropped for being unloaded. The archive tier exists so that "we found
nothing" and "nothing is there" stay distinguishable.

The tier boundary currently coincides with `INDEPENDENT_DEMAND`, which is
arithmetic rather than design: that constant settles whether a page is its own
script, this one settles where a script already known to be its own gets filed.
Moving either must not move the other.

## Stored data

All five tables are rebuildable from a fresh sweep. None holds anything that is
not already publicly readable on the wiki.

| Table                           | Contents                                                                                                                                      |
| ------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `user_script_pages`             | One row per observed page: owner, basename, content model, role, fingerprint, revision id, `discovery_rank`, body, `deleted_at`               |
| `user_script_imports`           | One row per load edge, keyed on source, verb and target; `is_stylesheet` separates CSS loads from script loads                                |
| `user_script_census_state`      | Per-wiki cursor and counters: `changes_cursor`, `sweeps_completed`, `enumeration_complete`, `enumeration_totals`, status, timings, last error |
| `user_script_directory`         | The projected directory: one row per original, with `tier`, `demand`, `instances` and `position`                                              |
| `user_script_directory_members` | Every page folded under an original, with its `relation`                                                                                      |

`backend.userscript_projection.project()` rebuilds the last two from the first
two. It is whole-corpus and idempotent: running it twice over unchanged pages
produces the same rows. It reads no wiki and makes no request, so it runs at the
end of every pass — including one that wrote nothing, because the collapse is
global and one new page can change which page is the original of a script. A
directory rebuilt only when the sweep found something would drift out of
agreement with the pages it claims to describe.

## Read API

`backend.v1_userscripts` serves what the projection last wrote and nothing else.
If an answer here disagrees with the directory, this module is wrong. All three
routes are public, read-rate-limited, and touch only the local database.

- `GET /v1/userscripts/wikis/` — every wiki with census state or directory
  entries, each with its coverage.
- `GET /v1/userscripts/directory/?wiki=&tier=&owner=&limit=&offset=` — one tier
  of one wiki's directory. `limit` defaults to 25 and clamps to 200.
- `GET /v1/userscripts/script/?wiki=&title=` — one original plus the pages folded
  under it.

**Every response carries coverage metadata**, so an empty result never reads as
"nothing exists": `pages`, `sweepsCompleted`, `sweptAt`, `computedAt`, and the
per-tier counts. A wiki whose first sweep has not finished says so.

Asking for a page that was folded away answers `404` with
`{"error": "not an original", "filedUnder": "<origin title>"}` rather than a bare
miss — where the page went is the most useful thing the directory can say about
it.

## The directory page

`/userscripts` (`public_html/views/userscripts.js`) is the reader for all of the
above: a wiki picker, `active`/`archive` tabs, an owner filter, and a pager, all
of it in the URL so any view can be linked. Rows link out to the page on the wiki
itself — the `wiki` identifier _is_ the host, so `fr.wikipedia.org` becomes
`https://fr.wikipedia.org/wiki/…`.

It is the one view that deliberately does not use `backendGetJson`, because that
helper discards non-2xx bodies and this view's most useful answer — `filedUnder`
on a folded page — arrives in a 404 body.

## Scheduled job

`proxy/userscript_sweep.py` is the Toolforge entrypoint, registered in
`jobs.yaml` as `userscript-census` and guarded by `tools/job_guard.sh`:

```
schedule: "23 * * * *"     # hourly watch
USERSCRIPT_WIKIS=fr.wikipedia.org,meta.wikimedia.org
```

- `USERSCRIPT_WIKIS` — comma-separated hosts, in order. Defaults to
  `fr.wikipedia.org,meta.wikimedia.org`. Set inline in the job command, not as a
  Toolforge envvar.
- `USERSCRIPT_SWEEP=1` — ask for a full sweep. A full sweep is thousands of
  requests and is not something to run hourly, so the schedule runs a watch and
  the sweep is asked for explicitly. **A wiki with no completed sweep gets one
  whether or not this run asked for it** — a watch with no cursor would otherwise
  learn only what changed since it started.

The projection follows every run. See [RUNBOOK.md](RUNBOOK.md) for lock
reclamation, log locations, and the shared job contract.

## Wikis in the census

frwiki is the corpus under study. Meta is there for one reason: `global.js` and
`global.css` live on Meta, they load scripts hosted on other wikis, and the
demand query already selects load edges by _target_ across source wikis. Those
cross-wiki edges are the strongest argument any script has for becoming a global
gadget, and until Meta was swept that channel was empty.

Adding a wiki is not just an entry in `USERSCRIPT_WIKIS`. Its local loader verbs
have to be read out of its own `MediaWiki:Common.js` and written into
`LOCAL_LOADERS`, because they cannot be inferred; a wiki added without that step
still works, it just scores every load made through a local verb at zero. Meta
needs no entry — its `Common.js` overrides `importScript` rather than defining a
new verb, and `importScript` is already a global loader verb.

### Meta is larger than one enumeration

Measured 2026-08-20, Meta holds **23,587** javascript-model and **8,925**
css-model pages in user space. `SEARCH_OFFSET_CAP` is 10,000, so
`enumerate_titles` short-circuits on the javascript half: it returns the first
`SEARCH_PAGE_SIZE` (500) titles and sets `complete = False`. `discover()` ANDs
completeness across both models, `sweep()` writes `enumeration_complete = False`
and — correctly — skips `_mark_missing`, since a page absent from a truncated
enumeration has not been shown to be gone.

The consequence is that Meta's javascript census covers roughly 500 of 23,587
pages. That is recorded honestly rather than papered over: the state row says
so, `coverage()` returns `enumerated: false`, and `/userscripts` prints a notice
that only part of the wiki's user space has been read. The css half is under the
cap and is complete.

The remedy `Discovery`'s own docstring prescribes — narrowing the query by title
prefix — is not implemented. `search_query()` and `enumerate_titles()` both
accept a `prefix=`, but `discover()` never passes one, so nothing splits an
over-cap wiki into walkable buckets. Until that exists, Meta contributes a
sample of its cross-wiki edges rather than all of them, and any wiki with more
than 10,000 pages of one model will land the same way.

### Owners, and the namespaces titles arrive in

The search and recent-changes queries both ask for namespace 2 _by number_, and
the wiki answers in its own language: `User:` on Meta, `Utilisateur:` on frwiki,
`Benutzer:` on dewiki, `利用者:` on jawiki. Two separate mechanisms deal with
that, and it is worth knowing which does what.

`userscripts.canonical_title()` folds the aliases in `_NAMESPACE_ALIASES` —
`User`, `Utilisateur`, `Utilisatrice` — onto `User:`, so one page written two
ways is one row. That list is hardcoded and covers English and French only; it
is what makes the frwiki gender-variant spellings (`Utilisatrice:Evpok` is
returned for a page written `Utilisateur:Evpok`) collapse to one title.

The owner is _not_ resolved from that list. `owner_of_user_page()` takes
everything before the first colon to be the namespace prefix, whatever it is
called, and returns the segment below it. That is sound because of where it is
called: `store_page()` is the only caller, and every title reaching it came from
a namespace-2 search or a namespace-2 recent-changes filter, so the page is
known to be in user space before the question is asked. Given a title from
anywhere else the function returns nonsense rather than `""` — which is why it
has that name, and why nothing else calls it.

Everything downstream reads the stored `owner` column instead of re-deriving it.
`demand()` outer-joins each import back to its source page for exactly this
reason: the owner it counts people by is the one the sweep resolved when the
namespace was known, not a second derivation that could disagree with the first.

The two mechanisms sit at different scopes on purpose. A wiki outside the alias
list still gets correct owners — the crowded-name fold and per-person demand
both work on dewiki today — it just stores its titles under its own prefix
rather than a canonical one.

## Known gaps

- **`_NAMESPACE_ALIASES` covers English and French.** Titles from any other wiki
  are stored under that wiki's own prefix. Owners resolve correctly regardless,
  but a page written two ways on such a wiki is two rows, and `fingerprint()`
  normalizes only those same three aliases when hashing a body. Widening it
  properly means reading each wiki's namespace names and aliases from
  `meta=siteinfo`, which nothing does.
- **Demand does not skip same-owner loads.** `demand()` skips only a page
  loading _itself_, though its docstring describes the broader case — "a script
  that installs its own helper subpage would otherwise vote for itself". With
  owners resolved, `User:X/common.js` loading `User:X/helper.js` adds X to
  helper.js's demand. Whether that is one person's setup or genuine use is a
  judgment the collapse rules have not made.
- **Thresholds are calibrated against one wiki.** `CROWDED_OWNERS`,
  `INDEPENDENT_DEMAND` and the tier split were all measured on frwiki. Meta is
  swept but only partially enumerated, so it is not yet a second data point to
  check them against.
- **Fork detection is a hash.** `fingerprint()` finds copies that differ only in
  comments and whitespace. It does not find a script somebody edited — a fork with
  one line changed reads as a distinct original. Recognizing those needs
  normalization beyond hashing, and it is not written.
- **Gadget usage is not joined in.** Demand is counted from pages this census can
  read. A script installed as a wiki gadget is loaded by people who never create
  a page at all, and the `gadgetusage` API knows those numbers; nothing reads it.
- **Nothing analyses the code yet.** The directory is the prerequisite — security
  review, API-usage extraction, and "which of these should be one global gadget"
  all run on top of it and none of them exist.
