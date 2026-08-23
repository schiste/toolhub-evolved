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
JavaScript. What this document previously claimed, that a page whose body is
really CSS never earns a directory entry, is not true and was never measured:
`classify()` reads a role off the number of code lines, and a long stylesheet is
a `script` to that test. Of the 32,154 enwiki directory candidates counted on
2026-08-21, 12,470 are `content_model = css`. See the gap at the end; there is
still no stylesheet tier and no plan for one.

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

`backend.userscript_directory` decides which pages are distinct scripts. Read
against production on 2026-08-23, across all three censused wikis:

| Wiki   | Script pages | Distinct scripts | Active | Archived |
| ------ | ------------ | ---------------- | ------ | -------- |
| enwiki | 39,950       | 6,207            | 1,700  | 4,507    |
| meta   | 10,299       | 2,602            | 720    | 1,882    |
| frwiki | 6,551        | 1,395            | 410    | 985      |

enwiki is still being enumerated and its page count is a floor, not a total.
frwiki is complete: 13,616 user-space `.js` and `.css` pages, 6,551 of them real
scripts.

(The frwiki figures this document previously carried — 1,453 scripts, 671
active — were measured before a load from the target's own owner stopped
counting as demand, which is most of the difference in the tiers, and before the
near-copy fold existed, which is most of the difference in the scripts. The
pilot figures before those — 9,919 pages, 2,051 scripts, 1,264 originals — were
measured over `.js` alone and before the search was sorted into creation order.)

Getting from 6,551 to 1,395 is not deduplication. Most of the difference is not
byte-identical copies at all — it is per-user configuration. In the pilot, 472
people had a page called `LiveRCparam.js`, each holding their own settings for
one shared tool. Hashing finds none of them, because no two are the same.

What finds them is content and the filename, in three passes:

1. **Exact copies fold on fingerprint.** Same comment-stripped body, same script.
2. **Near copies fold on resemblance.** A page more than `NEAR_COPY_SIMILARITY`
   (0.9) of the way to an earlier one is a fork of it — somebody's copy with
   their own settings, or their own edits, in it.
3. **Crowded names fold on the filename.** When `CROWDED_OWNERS` (5) or more
   distinct owners have a page under the same basename, the later ones are
   presumed to be instances of whatever the first one was, in the order the
   collapse ranks by: creation date first, `discovery_rank` where none is
   known.

Five owners is a low threshold, and it is where it is because of what the curve
does either side of it. Lowering it costs originals at an accelerating rate;
raising it buys them back at a flat, low one. On enwiki, 5 → 4 recovers 102
scripts, 4 → 3 recovers 189 and 3 → 2 recovers 365, while 5 → 8 costs about 94
scripts an owner, 8 → 12 about 37 and 12 → 25 about 17. frwiki and meta trace the
same convex shape at a tenth the size:

| Owners | enwiki | meta  | frwiki |
| ------ | ------ | ----- | ------ |
| ≥ 2    | 5,551  | 2,435 | 1,268  |
| ≥ 3    | 5,916  | 2,518 | 1,346  |
| ≥ 4    | 6,105  | 2,573 | 1,383  |
| ≥ 5    | 6,207  | 2,602 | 1,395  |
| ≥ 8    | 6,488  | 2,623 | 1,449  |
| ≥ 12   | 6,635  | 2,665 | 1,478  |
| ≥ 25   | 6,854  | 2,793 | 1,608  |

Five is the last threshold before folding gets expensive. It is still blunt
enough to be dangerous on its own — a genuinely popular name would bury real
scripts — so it never fires alone:

> **A page that other people demonstrably load keeps its identity, whatever it is
> called.**

That guard is `INDEPENDENT_DEMAND`, and it is set to 1. It is the one number in
this subsystem that is a judgement rather than a measurement, and the measurement
is what makes the judgement easy. Starting from what the name rule leaves on its
own, and counting the scripts each threshold rescues back:

| Guard threshold | enwiki | meta  | frwiki |
| --------------- | ------ | ----- | ------ |
| name rule alone | 6,028  | 2,412 | 1,338  |
| ≥ 25 sources    | +22    | +2    | +2     |
| ≥ 5 sources     | +28    | +5    | +2     |
| ≥ 3 sources     | +15    | +5    | +3     |
| ≥ 2 sources     | +19    | +9    | +4     |
| ≥ 1 source      | +95    | +169  | +46    |

The largest single step is at 1 on all three wikis, and everything above it is a
thin tail — so the choice is binary: either somebody other than the author
loading a page is enough to make it its own script, or it is not. It is. Folding
a genuine instance into its tool costs a duplicate entry that demand ranking
pushes to the bottom anyway; the reverse error is silent and unrecoverable.
Protecting reused pages directly is also what lets the crowd threshold sit at 5
rather than 25 — folding 1,066 more enwiki pages, 267 more on frwiki and 241 more
on meta, while losing nothing anybody imports.

The rule validates itself in a way worth stating, because it is the reason to
trust it on a wiki nobody has hand-checked. "Earliest wins" recovers tool authors
without being told what a tool author is: 471 of the 472 `LiveRCparam.js` pages
fold onto EDUCA33E, who wrote LiveRC, and the `AdvancedContribs.js` group folds
onto Maloq, who wrote AdvancedContribs. The 472nd is somebody else's settings
file that another editor loads, so the guard keeps it — which is exactly the case
`INDEPENDENT_DEMAND` exists for.

### Resemblance, and why it is not a hash

The second pass answers a question no hash can. A fork with one line changed has
a fingerprint unrelated to the page it was copied from; on frwiki 678 pairs of
pages are more than 99% the same text and share no fingerprint at all. The shape
of the difference is what says what they are: `lrcParams["RCLimit"] = 35`
against `= 30`, one `@import` line present in one copy and not the other.

Every page carries a **sketch** alongside its fingerprint — the smallest 64
hashes of every five-line window of its comment-stripped body, base64 of their
raw bytes. Because the hash is uniform the smallest 64 are a uniform sample, so
two sketches overlap in proportion to the bodies, and `similarity` reads a
Jaccard estimate off the pair without either body being loaded. Measured against
exact Jaccard over 10,366 frwiki pairs, 8,506 estimates were exactly right and
none was off by more than 0.2.

0.9 is the threshold because the failure it guards against is silent. Folding two
unrelated scripts together loses one permanently; folding one entry too late
leaves a duplicate that demand ranking pushes down. Measured on frwiki, dropping
to 0.7 folds 1,610 pages instead of 1,104 and raises the count of groups spanning
more than three distinct filenames — the signature of an over-broad fold — from 6
to 14.

Two rules keep the pass from over-reaching:

- **Every page is compared only against originals already accepted**, in
  creation order, never against another fork. Joining whatever matches would let
  resemblance chain — A resembles B, B resembles C, therefore A and C are one
  script even where they share nothing — and a chain has no bound. Here every
  member of a group is within 0.9 of the one page the group is named after,
  which stays true however large the group gets.
- **Sketches are found through an index of their hashes**, not by comparing
  every pair. Two bodies sharing none of the 64 sampled hashes cannot be 90% the
  same, so the pairs the index skips are pairs the comparison would have
  rejected.

Measured over the three censused wikis:

| Wiki   | Script pages | After exact | After near | Pages folded | Groups | `.js` pages folded | Directory originals |
| ------ | ------------ | ----------- | ---------- | ------------ | ------ | ------------------ | ------------------- |
| enwiki | 32,154       | 23,485      | 22,310     | 2,421        | 700    | 1,012              | 5,157 → 4,939       |
| meta   | 10,299       | 8,869       | 8,619      | 379          | 164    | 216                | 2,705 → 2,642       |
| frwiki | 6,551        | 5,779       | 5,546      | 274          | 139    | 200                | 1,498 → 1,458       |

The `.js` groups are the ones the filename rule could never have reached, because
the names differ: `sysopdectector.js` onto `sysopdetector.js`, `ancien
monobook.js` onto `monobook.js`, `deluxehistory test.js` onto
`deluxehistory.js`, `popup.js` and `popupLocal.js` onto `popups.js`.

This is also what closes the wiki-aware hashing question the prefix work left
open. Widening `fingerprint()` to each wiki's own namespace spellings would rewrite
every hash already stored and make each page look like a fork of itself until
the corpus was swept again. It is unnecessary: two bodies that differ only in
how they spell a namespace are a near copy by any measure, and the sketch finds
them without anyone deciding in advance which spellings to fold — which is the
general case, since a hash can only ever be widened to differences somebody
anticipated.

Each surviving original keeps its folded pages as members, related as
`original` (a fact), `copy` (same fingerprint — a fact), `fork` (most of the
same body, with edits — an observation) or `variant` (same name, different body
— an inference). A reviewer reading the directory has to be able to tell which
rule filed a page.

**Demand is counted in people, not pages.** Somebody who loads a script from both
`common.js` and `vector.js` is one user of it. Demand is also selected by
_target_ rather than by source wiki, so an import stored against another wiki
that points here still counts — those cross-wiki edges are the strongest argument
any script has for becoming a global gadget.

**Loading your own page is not demand for it.** `User:X/common.js` loading
`User:X/helper.js` is one person wiring up their own setup, and an author is not
evidence for their own script. Owners are compared rather than titles, so this
holds on a wiki whose namespace 2 is called something else, and it holds across
wikis: usernames are global, so `User:X` on enwiki loading `User:X/tool.js` on
frwiki is still the author. This is not a small correction — 575 of frwiki's
4,544 resolved load edges and 1,293 of Meta's 11,638 are somebody voting for
themselves, which is 366 of 923 frwiki pages and 725 of 1,980 Meta pages losing
_all_ their demand, and half the pages that had exactly one user having none. A
source with no census row has no resolved owner to compare, so it stands for
itself and still counts.

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
  author loads it. Ordered most-loaded first.
- **`archive`** — "what exists". No importer anybody can see. Ordered oldest
  first, which is the order the cold-storage question is actually asked in.

Nothing is dropped for being unloaded. The archive tier exists so that "we found
nothing" and "nothing is there" stay distinguishable.

The split it produces is the steadiest number in this subsystem: 1,700 of 6,207
scripts active on enwiki, 720 of 2,602 on meta, 410 of 1,395 on frwiki — 27.4%,
27.7% and 29.4%. Those corpora differ by a factor of four in size and completely
in language and purpose, so whatever this boundary measures, it is not an frwiki
habit. Roughly three quarters of everything user space holds is code nobody but
its author loads, and that appears to be a property of user space rather than of
any one wiki.

The tier boundary currently coincides with `INDEPENDENT_DEMAND`, which is
arithmetic rather than design: that constant settles whether a page is its own
script, this one settles where a script already known to be its own gets filed.
Moving either must not move the other.

## Stored data

All five tables are rebuildable from a fresh sweep. None holds anything that is
not already publicly readable on the wiki.

| Table                           | Contents                                                                                                                                                                             |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `user_script_pages`             | One row per observed page: owner, basename, content model, role, fingerprint, `sketch`, revision id, `discovery_rank`, body, `deleted_at`                                            |
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
"nothing exists": `pages`, `sweepsCompleted`, `enumerated`, `enumeratedBy` and
the per-tier counts, plus three separate timestamps. They are separate because a
census is stale in three unrelated ways and only one of them is about the job
still running: `checkedAt` is the last run of any kind — liveness, and the one
that says nothing about the data, since a watch stamps it hourly whether the
wiki moved or not; `sweptAt` is when this wiki's user space was last enumerated
and walked; `currentTo` is the wiki's own clock, how far into recent changes the
watch has read. frwiki has been all three at once — checked this hour, swept in
July, current to a fortnight ago — and a reader given only the first would have
called it fresh. A wiki whose first sweep has not finished says so.

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

- **`fingerprint()` still folds English and French only.** Closed, in two
  halves. For titles, `backend/wiki_prefixes` reads each wiki's namespace names,
  aliases and interwiki map from `meta=siteinfo`, stores them, and hands them to
  the fold, so `Benutzer:X/y.js` and `en:User:Lupin/popups.js` now resolve to
  the page and wiki they name. For bodies, `fingerprint()` deliberately did not
  move — widening it rewrites every hash already stored — and does not need to:
  the near-copy fold recognizes two bodies that differ only in a namespace
  spelling without being told the spellings.
- **The thresholds have not been re-read since same-owner demand stopped
  counting.** Closed. `demand()` now skips a load from anywhere in the target's
  own owner's space rather than only a page loading itself, which removes 44% of
  enwiki's pages-with-demand, 40% of frwiki's and 37% of meta's — an author
  loading their own script was that large a share of the signal. The thresholds
  were then re-read with the rule in place; see the next gap.
- **Thresholds are calibrated against one wiki.** Closed. `CROWDED_OWNERS`,
  `INDEPENDENT_DEMAND` and the tier split were re-measured on 2026-08-23 against
  enwiki, meta and frwiki together, with the same-owner demand rule and the
  near-copy fold both in place — the state neither was originally measured in.
  All three hold, and none of the constants moved. The evidence is in "The
  collapse" and "Tiers" above: the crowd curve is convex about 5 on every wiki,
  the guard's largest rescue is at 1 on every wiki, and the active share lands
  between 27% and 30% on all three. What is _not_ closed is enwiki's
  enumeration, which is still running, so its counts are a floor.
- **Fork detection is a hash.** Closed. Every page carries a sketch of its body
  alongside its fingerprint, and a page more than 0.9 of the way to an earlier
  one is filed as a `fork` of it — 3,074 pages across the three wikis, 1,428 of
  them `.js`, in groups the filename rule could not reach. See "Resemblance, and
  why it is not a hash" above.
- **39% of the directory's candidates are stylesheets.** A page's role is read
  from its body, and a long `.css` page is as much a "script" as a long `.js`
  one to that test. Of the pages the directory collapsed on 2026-08-21, 12,470 of
  enwiki's 32,154 were `content_model = css`, 4,450 of meta's 10,299 and 2,246 of
  frwiki's 6,551. They fold correctly — most of the largest near-copy groups on every
  wiki are people copying each other's `monobook.css` — but a user stylesheet is
  not a tool, and promoting one into the catalog would be wrong. Nothing filters
  on `content_model` yet.
- **Gadget usage is not joined in.** Demand is counted from pages this census can
  read. A script installed as a wiki gadget is loaded by people who never create
  a page at all, and the `gadgetusage` API knows those numbers; nothing reads it.
- **Half of frwiki's load edges resolve to nothing, and most of them never
  will.** Of 8,216 stored edges, 4,029 named a page the census holds. Checking
  the other 638 distinct titles against the live API is what told them apart,
  and the answer was mostly not a bug: 279 name a `User:` page that does not
  exist on frwiki at all — loads of scripts long since deleted or never
  created, which nothing can resolve because there is nothing to resolve to.
  Another 173 name `MediaWiki:` gadget definitions, correctly unresolved because
  the census enumerates user space only. The rest was small and mixed, and the
  three parts of it that were bugs are now closed: ~16 used a namespace alias
  from another language (`Benutzer:`, `Gebruiker:`) and ~6 carried an interwiki
  prefix (`:En:`, `:Id:`), both of which the per-wiki prefixes above now fold
  and follow; 38 named no namespace, and an argument that names no page now
  produces no edge at all rather than an unresolvable one; and a
  `mw.loader.load('ext.gadget.x')` names a ResourceLoader module, which is
  recorded in `target_module` rather than misfiled as a title. Raw
  `/w/index.php?title=…` URLs and `[[…]]` brackets were normalized at parse time
  earlier. What remains is 53 titles that name a `User:` page which _does_ exist
  on frwiki and is missing from the census anyway (see below). **The figures in
  this bullet predate those fixes**; the next full sweep is what re-measures
  them.
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
