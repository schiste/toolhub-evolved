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

**Creation order comes from `discovery_rank`, not a timestamp.** The collapse's
"earliest page wins" rule only ever compares two pages, and the search index
hands enumeration order over for free, while asking the API for 9,919 creation
dates is 9,919 requests.

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
USERSCRIPT_WIKIS=fr.wikipedia.org
```

- `USERSCRIPT_WIKIS` — comma-separated hosts, in order. Defaults to
  `fr.wikipedia.org`. Set inline in the job command, not as a Toolforge envvar.
- `USERSCRIPT_SWEEP=1` — ask for a full sweep. A full sweep is thousands of
  requests and is not something to run hourly, so the schedule runs a watch and
  the sweep is asked for explicitly. **A wiki with no completed sweep gets one
  whether or not this run asked for it** — a watch with no cursor would otherwise
  learn only what changed since it started.

The projection follows every run. See [RUNBOOK.md](RUNBOOK.md) for lock
reclamation, log locations, and the shared job contract.

## Known gaps

- **Only frwiki has been swept.** Every threshold above is calibrated against one
  wiki. The demand query already counts cross-wiki edges by target, so `global.js`
  on Meta would feed the ranking the moment Meta is swept — but it has not been,
  so that channel is empty today and cross-wiki reuse is currently invisible.
  Adding a wiki is not just an entry in `USERSCRIPT_WIKIS`: its local loader
  verbs have to be read out of its own `MediaWiki:Common.js` and written into
  `LOCAL_LOADERS`, because they cannot be inferred. A wiki added without that
  step still works — it just scores every load made through a local verb at
  zero.
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
