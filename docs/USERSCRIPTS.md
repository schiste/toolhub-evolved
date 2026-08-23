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

Discovery asks for pages in namespace 2 whose content model is `javascript` or
`css`. The alternative — walking `list=allpages` and filtering on the suffix —
reads several hundred thousand titles to find nine thousand pages, and gets the
suffix question wrong at the end of it.

`backend.userscript_enumeration` picks between two roads to that list:

- **The Wiki Replicas** (`wiki_replica.ENUMERATION_QUERY`), preferred. One
  indexed read of `page` filtered on `page_content_model`, ordered by `page_id`,
  with no cap and no paging. Namespace-2 pages always record an explicit content
  model, so the predicate is exact: it finds the twenty to sixty pages per wiki
  holding JavaScript under a name that does not end in `.js`, and skips the
  wikitext pages that do. `page_id` order is creation order, which is the
  ordering `discovery_rank` records, obtained for free.
- **The search index** (`backend.userscript_census`), the fallback. Replicas are
  reachable only from inside Toolforge, so a laptop, CI, or any host without
  `replica.my.cnf` still has to be able to run a census. What this road gives up
  is completeness on a large wiki, and it says so rather than pretending.

The replica road costs one Action API request — `meta=siteinfo`, to learn what
the wiki calls namespace 2. The replica stores `page_title` without a namespace
and with underscores; the API answers with the local name and spaces, and the
census keys ranks, revisions and tombstones on the title, so the two spellings
have to be made one before anything is fetched.

Three limits shape the code:

- **Search refuses an offset of 10,000 or more** (`SEARCH_OFFSET_CAP`). A model
  with more hits than that cannot be walked in one query, so the count is
  reported and `enumeration_complete` goes false rather than the walk quietly
  stopping. An enumeration that silently truncates at 10,000 looks exactly like
  a complete one. **`prefix:` cannot be used to work around this**: measured
  against Meta, one `-prefix:` clause partitions exactly, two are silently
  dropped, and two positive ones return nothing. The search API cannot be made
  to prove it named everything, which is why the replica is preferred.
- **A response is capped at 2 MB**, which a batch of large scripts can exceed. A
  batch that comes back too large is split rather than dropped. Pages are read
  `CONTENT_BATCH` (20) at a time.
- **A run's own budget.** Naming 155,000 pages is cheap; fetching them is ~7,800
  requests. `sweep(limit=)` bounds one run and `sweep_cursor` carries the
  position forward, so successive runs cover the corpus instead of re-reading
  its first slice. Only the run that reaches the end counts as a completed
  sweep, tombstones what the wiki no longer lists, and lets the wiki fall
  through to watching.

A census keeps whichever road it got, so the road is recorded with it in
`enumeration_source` — `replica`, `search` (no credentials on this host), or
`search-fallback` (credentials, but the replica did not answer). A finished
sweep never runs again on its own, so without this a wiki swept from the index
before the replica road existed would hold that census for good. `run()` sweeps
again when the recorded road has since been superseded, which only `search`
ever is: `search-fallback` means the exact road was tried and failed, and
re-trying it every run would sweep the wiki hourly to arrive at the same list.

Nothing here fetches on its own. Every Action API call goes through the existing
`WikimediaClient`, which validates the host before each request.

## Sweep and watch

`backend.userscript_sweep` runs the same machinery two ways. A **sweep** walks
every page of a script content model, in creation order, and is how a wiki
first enters the directory — over as many runs as its `limit` requires. A **watch** follows `recentchanges` since the stored
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
costs one request per page. At the measured 0.542s anonymous, frwiki's 13,616
pages are about two hours, and the 6,556 the collapse actually considers still
about an hour. The replica answers all of them in one query. The `letype=create`
log is not a shortcut either — it starts on 2018-06-27, and about 99% of the
User-namespace creations in it are neither `.js` nor `.css`.

## The collapse: originals and instances

`backend.userscript_directory` decides which pages are distinct scripts. The
first production sweep, on 2026-08-21, read 13,616 user-space `.js` and `.css`
pages on frwiki. 6,556 of them are real scripts, and those 6,556 pages are
**1,453 distinct scripts** — 671 with a live audience, 782 archived.

(The pilot figures this document previously carried — 9,919 pages, 2,051
scripts, 1,264 originals — were measured over `.js` alone, on a smaller
enumeration, and before the search was sorted into creation order.)

Getting from 6,556 to 1,453 is not deduplication. Most of the difference is not
byte-identical copies at all — it is per-user configuration. In the pilot, 472
people had a page called `LiveRCparam.js`, each holding their own settings for
one shared tool. Hashing finds none of them, because no two are the same.

What finds them is the filename, in two passes:

1. **Exact copies fold on fingerprint.** Same comment-stripped body, same script.
2. **Crowded names fold on the filename.** When `CROWDED_OWNERS` (5) or more
   distinct owners have a page under the same basename, the later ones are
   presumed to be instances of whatever the first one was, in the order the
   collapse ranks by: creation date first, `discovery_rank` where none is
   known.

Five owners is a low threshold and blunt enough to be dangerous on its own — a
genuinely popular name would bury real scripts — so it never fires alone:

> **A page that other people demonstrably load keeps its identity, whatever it is
> called.**

That guard is `INDEPENDENT_DEMAND`, and it is set to 1. It is the one number in
this subsystem that is a judgement rather than a measurement, and the measurement
is what makes the judgement easy. Measured on the pilot corpus, starting from
the 1,229 originals the name rule leaves on its own:

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

**Demand is counted by identity, not by spelling.** A load is counted once it has
been resolved to the page it names; the map is then keyed on that page's
canonical title rather than on the string the script happened to write. Keying on
the raw string files demand under names no candidate answers to — measured on
frwiki before the change, 644 of 1,389 entries named no page at all, and not one
of them was a candidate, so the switch moved no score. It is what lets a better
resolver move them: the key now follows the page.

Because of that, projection repairs its own input before reading it, resolving any
load into the wiki that names a page already held. That is a join and not a scan
for nulls, so a load pointing outside the census is never rewritten and never
re-examined. The alternative was to trust that a sweep had run first, and a
directory that goes quiet because two jobs ran in an unlucky order reports
success while saying nothing. `project()` returns the repair count as `repaired`.

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

| Table                           | Contents                                                                                                                                                                             |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `user_script_pages`             | One row per observed page: owner, basename, content model, role, fingerprint, revision id, `discovery_rank`, body, `deleted_at`                                                      |
| `user_script_imports`           | One row per load edge, keyed on source, verb and target; `target_page_id` is that target resolved to a page; `is_stylesheet` separates CSS loads from script loads                   |
| `user_script_census_state`      | Per-wiki cursors and counters: `changes_cursor`, `sweep_cursor`, `sweeps_completed`, `enumeration_complete`, `enumeration_totals`, `enumeration_source`, status, timings, last error |
| `user_script_directory`         | The projected directory: one row per original, with `script_id`, `tier`, `demand`, `instances` and `position`                                                                        |
| `user_script_directory_members` | Every page folded under an original, with its `relation`, `script_id` and `origin_id`                                                                                                |

### Identity

A script's identity is `user_script_pages.id`. It is assigned when the page is
first observed, kept across every re-read — `store_page()` finds and updates,
never deletes and re-inserts — and retired by setting `deleted_at` rather than
by removing the row. It is the only number here that is safe to write down
anywhere else.

The directory tables have ids of their own and those are not it. Both are
deleted and rebuilt whole on every projection, so their `id` columns are
renumbered on a schedule no caller can see. That is why each carries the census
identity alongside the title:

- `user_script_directory.script_id` — the page the collapse named as the
  original of this entry.
- `user_script_directory_members.script_id` / `.origin_id` — the two ends of the
  "this page folded onto that script" edge, said in identities.
- `user_script_imports.target_page_id` — the load edge said in identities.

`target_page_id` is nullable and stays null for most rows, which is the honest
answer rather than a gap: a load can name a page that was deleted, renamed,
never existed, or lives on a wiki outside the census, and there is no row to
point at. The sweep resolves both directions of what each run writes — the loads
made _by_ the pages it stored, and the loads made _of_ them from anywhere — so a
cross-wiki edge closes on whichever run reads the second end. It never scans for
unresolved rows, because a load pointing outside the census never becomes
resolvable and would be re-read forever; the one-off backfill in `migrate.py`
covers the rows written before the column existed.

None of these columns is a foreign key. They are added to live tables by
additive DDL, which cannot carry a constraint, so declaring one would create it
in a fresh test database and nowhere else — and a constraint the tests enforce
but production does not is worse than no constraint at all.

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
- `GET /v1/userscripts/script/?id=` or `?wiki=&title=` — one original plus the
  pages folded under it. Both the entry and each member carry `id`, the census
  identity described above; prefer it over the title, which moves when a page is
  renamed and is reused when one is deleted.

**Every response carries coverage metadata**, so an empty result never reads as
"nothing exists": `pages`, `sweepsCompleted`, `sweptAt`, `computedAt`, and the
per-tier counts. A wiki whose first sweep has not finished says so.

Asking for a page that was folded away answers `404` with
`{"error": "not an original", "filedUnder": "<origin title>", "filedUnderId": <id>}`
rather than a bare miss — where the page went is the most useful thing the
directory can say about it.

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
USERSCRIPT_WIKIS=fr.wikipedia.org,meta.wikimedia.org,en.wikipedia.org
USERSCRIPT_LIMIT=2000
```

- `USERSCRIPT_WIKIS` — comma-separated hosts, in order. Defaults to
  `fr.wikipedia.org,meta.wikimedia.org`. Set inline in the job command, not as a
  Toolforge envvar.
- `USERSCRIPT_SWEEP=1` — ask for a full sweep. A full sweep is thousands of
  requests and is not something to run hourly, so the schedule runs a watch and
  the sweep is asked for explicitly. **A wiki with no completed sweep, or one
  part-way through a bounded sweep, gets one whether or not this run asked for
  it** — a watch with no cursor would otherwise learn only what changed since it
  started, and a sweep abandoned half-way would never reach the other half.
- `USERSCRIPT_LIMIT` — how many pages one run may read. 0 (the default) means
  the whole wiki in one run. With a limit, the run reads a slice, records where
  it stopped in `sweep_cursor`, and the next run continues from there; only the
  run that reaches the end counts as a completed sweep, tombstones what is gone,
  and lets the wiki fall through to watching. 2000 titles is 100 content
  requests at `CONTENT_BATCH` 20, so enwiki's 155,561 pages take about 78 runs
  — a little over three days — for a first pass.
- `USERSCRIPT_WATCH_LIMIT` — recent-changes entries per watch. Independent of
  `USERSCRIPT_LIMIT`, so bounding sweeps does not shrink the hourly watch.

The projection follows every run. See [RUNBOOK.md](RUNBOOK.md) for lock
reclamation, log locations, and the shared job contract.

## Wikis in the census

frwiki is the corpus under study. Meta is there for one reason: `global.js` and
`global.css` live on Meta, they load scripts hosted on other wikis, and the
demand query already selects load edges by _target_ across source wikis. Those
cross-wiki edges are the strongest argument any script has for becoming a global
gadget, and until Meta was swept that channel was empty.

English Wikipedia is there for the opposite reason: it is where the largest
population of user scripts is written, so it is where a script proposed anywhere
is most likely to already exist under another name. It is also the corpus that
makes the bounded sweep necessary — 155,561 pages against frwiki's 14,431.

Adding a wiki is not just an entry in `USERSCRIPT_WIKIS`. Its local loader verbs
have to be read out of its own `MediaWiki:Common.js` and written into
`LOCAL_LOADERS`, because they cannot be inferred; a wiki added without that step
still works, it just scores every load made through a local verb at zero.
`LOCAL_LOADERS` is the only table keyed by wiki, and two of the three wikis need
no entry in it, for different reasons: Meta's `Common.js` overrides
`importScript` rather than defining a new verb, and `importScript` is already a
global loader verb; enwiki's defines no load verb at all — read 2026-08-22, it
aliases `addPortletLink` and honours `?withJS=`/`?withCSS=`, and neither of
those is something a user script can call.

### Meta was larger than one search, and is not larger than one replica read

Measured on the replicas on 2026-08-22, Meta holds **25,354** javascript-model
and **9,436** css-model pages in user space — 34,814 in total, against the
search index's 23,596. `SEARCH_OFFSET_CAP` is 10,000, so `enumerate_titles`
used to short-circuit on the javascript half: it returned the first
`SEARCH_PAGE_SIZE` (500) titles and set `complete = False`, and `sweep()` —
correctly — skipped `_mark_missing`, since a page absent from a truncated
enumeration has not been shown to be gone. Meta's javascript census therefore
covered roughly 500 of 25,354 pages.

The remedy `Discovery`'s docstring used to prescribe — narrowing by title prefix
— does not work. Probed live against Meta: `prefix:User:A` returns 1,856 and
`-prefix:User:A` returns 21,740, which sum exactly to the 23,596 total, but a
second `-prefix:` clause is silently dropped and two positive prefixes return
zero. Prefix clauses do not compose, so the index cannot be partitioned into
walkable buckets and cannot be made to prove it named everything.

The replica answers the same question exactly and without a cap, so Meta is now
enumerated in full and `enumeration_complete` is true for it. The `prefix=`
arguments on `search_query()` and `enumerate_titles()` remain, unused, on the
fallback road; nothing passes one, and nothing should.

Any wiki with more than 10,000 pages of one model still lands the old way on a
host with no replica — which is every host outside Toolforge, and is why the
state row and `coverage()` keep reporting enumeration completeness rather than
assuming it.

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
- **Half of frwiki's load edges resolve to nothing, and most of them never
  will.** Of 8,216 stored edges, 4,029 name a page the census holds. Checking
  the other 638 distinct titles against the live API is what tells them apart,
  and the answer is mostly not a bug: 279 name a `User:` page that does not
  exist on frwiki at all — loads of scripts long since deleted or never
  created, which nothing can resolve because there is nothing to resolve to.
  Another 173 name `MediaWiki:` gadget definitions, correctly unresolved because
  the census enumerates user space only. What is left is small and mixed: 53
  name a `User:` page that _does_ exist on frwiki and is missing from the census
  anyway (see below), ~16 use a namespace alias from another language
  (`Benutzer:`, `Gebruiker:`) that `canonical_title` does not fold, ~6 carry an
  interwiki prefix (`:En:`, `:Id:`) that belongs in `target_wiki`, and 38 name
  no namespace. Raw `/w/index.php?title=…` URLs and `[[…]]` brackets used to be
  in this list and are now normalized at parse time.
- **920 frwiki pages are missing from a census that reports itself complete.**
  Not a sweep-depth, staleness or drift problem — all three were measured and
  ruled out. frwiki's user space holds 14,431 script pages in the Wiki Replicas
  and 13,617 in the search index, and frwiki's census was built from the index,
  the day before the replica road landed. `enumeration_complete` was set
  truthfully: no model crossed the offset cap. That is not the same claim as
  "the index named every page", and nothing recorded which road had made it, so
  a finished sweep sat there watching for changes over a corpus 920 pages short.
  meta and enwiki were still mid-sweep on the day the replica road landed and
  picked it up for free — frwiki was stranded for having finished. The road is
  now recorded (`enumeration_source`) and a census built on a superseded one is
  swept again, so the 920 arrive on the next scheduled run. The 53 in the bullet
  above are the subset something actually loads.
- **Nothing analyses the code yet.** The directory is the prerequisite — security
  review, API-usage extraction, and "which of these should be one global gadget"
  all run on top of it and none of them exist.
