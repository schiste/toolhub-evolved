# Toolhub Digest

The Toolhub Digest turns newly created official Toolhub records into short,
editorial English editions. It publishes one canonical copy on Meta-Wiki and
then exposes that frozen edition through the local archive, RSS, Wikimedia
email, and wiki talk pages.

English is the only generated language today. Every durable row, unique key,
route payload, prompt, and subscription already carries a language code so a
future language can have its own prompt, validation, publication tree, feed,
and subscriber set without changing the English history.

## UTC edition contract

All readers share the same UTC boundaries:

- a daily edition covers `[00:00, 00:00)` on the previous UTC date;
- a weekly edition covers Monday through the following Monday in UTC;
- a monthly edition covers the first day through the first day of the next
  month in UTC.

Only closed periods are eligible. An edition is not created when its period has
no captured tool-creation events. The publisher discovers every event-bearing
closed period that lacks an edition, so a missed job catches up later instead
of shifting boundaries or publishing empty placeholders.

The 06:15 UTC publisher therefore normally creates yesterday's daily edition,
the prior ISO week on Monday, and the prior calendar month on the first day.

## Data and editorial pipeline

`catalog-sync` polls official Toolhub recent changes every 15 minutes. New root
tool revisions are inserted idempotently into `tool_activity_events`; edits,
lists, malformed rows, and the initial cursor baseline are excluded. Edition
generation snapshots the corresponding canonical cache facts into
`digest_edition_tools`. Later catalog edits cannot rewrite an edition.

Lift Wing receives only those verified public facts. Configure the Qwen
inference URL and model with `LIFTWING_API_URL` and `LIFTWING_MODEL`. Its JSON
response is accepted only when every named tool exists in the snapshot, the
number and length of highlights are bounded, the introduction stays within 32
words, each highlight stays within 28 words, editorial blurbs contain no links,
and every highlight cites an exact supporting value from an allowed field in
the frozen facts. The prompt asks Qwen for one concrete thematic introduction
and active-voice highlights that explain what a tool lets someone do, avoiding
title repetition, cadence boilerplate, vague praise, and promotional language.
Daily editions require one validated entry for every supplied tool and label
the section “Every new tool”; an omission, duplicate, or invented identifier
rejects the model response. Weekly and monthly editions select exactly the
smaller of five tools or the period's complete tool count, then retain every
other tool in the complete compact index. Daily
inference therefore receives every tool in the closed UTC day. For busy weekly
and monthly periods, inference receives a bounded set selected from evenly
spaced period buckets, preferring records with richer citable metadata; the
trusted renderer still includes every tool in the edition. Model input contains
only bounded citation fields—never renderer-only URLs or person objects—and
generation failures retain their sanitized HTTP or validation reason in the
audit payload and operator error.
Canonical author names and publishable resolved author and
maintainer identities are frozen alongside the tool metadata. Qwen may mention
those supplied names but never emits URLs. The deterministic renderer adds the
official Toolhub page, safe direct-tool URL, author index or resolved person
page, and resolved maintainer page to HTML, wikitext, and plain text. Any
unavailable, malformed, or ungrounded response uses a short deterministic
fallback, records that decision in `digest_generation_attempts`, and remains
publishable. The hourly audit still fails visibly when a configured Qwen call
falls back, so availability does not hide degraded editorial quality.

The validated edition stores HTML, wikitext, and plain text together. Those
same frozen renderings feed the local blog, Meta, RSS, email, and talk pages.

## Meta publication

Set `DIGEST_META_BASE_TITLE` to the future parent title, for example
`Toolhub/Digest`. Editions are created below:

```text
Toolhub/Digest/Daily/2026-08-12
Toolhub/Digest/Weekly/2026-W32
Toolhub/Digest/Monthly/2026-08
Toolhub/Digest/Archive
```

Individual pages are create-only. A hidden edition marker makes retries
idempotent; an existing page without that marker is a collision and is never
overwritten. The managed Archive page is refreshed after successful
publication. Set `DIGEST_META_DOMAIN` only if publication moves from
`meta.wikimedia.org`.

## Subscription and delivery contract

RSS requires no account and is available at
`/feeds/digests/{daily,weekly,monthly}.xml`.

Email and talk-page subscriptions require a signed-in Toolhub account with a
stable Wikimedia global account id. CentralAuth resolves the current username,
so account renames do not leave a stale delivery identity. For talk delivery,
the selected public Wikimedia domain is allowlisted and the local account is
verified against that same stable CentralAuth id before activation and again
immediately before each delivery.

Email is sent with MediaWiki `action=emailuser` on Meta. Toolhub Evolved never
receives or stores the destination address; Wikimedia applies the user's email
preferences. Email subscriptions remain inactive until a seven-day signed
confirmation link is used. Every email contains a signed one-click unsubscribe
link. Talk-page subscriptions activate immediately and add a section carrying
the edition's idempotency marker.

`digest_deliver.py` repairs missing outbox rows before each bounded drain.
Transient failures back off exponentially for up to eight attempts and then
leave an operator-visible failed delivery without disabling the subscription.
A permanent recipient or identity failure suspends only that subscription,
never other channels or readers. Delivery eligibility begins at confirmation;
subscribing never backfills historical editions. Confirmation links expire in
seven days, while signed unsubscribe links remain valid for the subscription's
lifetime.

## Toolforge configuration

Configure secrets and deployment-specific values in the Toolforge environment,
not in `jobs.yaml`:

| Variable                   | Required          | Purpose                                                                                         |
| -------------------------- | ----------------- | ----------------------------------------------------------------------------------------------- |
| `DIGEST_META_BASE_TITLE`   | Yes               | Parent Meta page supplied by the operator.                                                      |
| `DIGEST_META_DOMAIN`       | No                | Defaults to `meta.wikimedia.org`.                                                               |
| `DIGEST_PUBLIC_BASE_URL`   | Yes in production | Origin used for edition and signed action links.                                                |
| `DIGEST_SIGNING_SECRET`    | Recommended       | Dedicated confirmation/unsubscribe signing key; falls back to `TOOLHUB_SECRET_KEY`.             |
| `WIKIMEDIA_ACCESS_TOKEN`   | Yes               | Bearer token allowed to edit Meta, append talk pages, and call `emailuser`.                     |
| `WIKIMEDIA_ACCOUNT_NAME`   | Yes               | Expected service-account username; writes fail closed if the token resolves to another account. |
| `WIKIMEDIA_USER_AGENT`     | Yes               | Descriptive Wikimedia-compliant user agent with contact information.                            |
| `LIFTWING_API_URL`         | Yes in production | Public Lift Wing OpenAI-compatible chat-completions endpoint.                                   |
| `LIFTWING_MODEL`           | Yes in production | Public Qwen model ID; Toolhub Digest uses `llm-qwen36-27b`.                                     |
| `LIFTWING_USER_AGENT`      | Yes in production | Descriptive contact-bearing value sent as both `User-Agent` and `Api-User-Agent`.               |
| `LIFTWING_TIMEOUT_SECONDS` | No                | Defaults to 60 seconds.                                                                         |
| `DIGEST_DELIVERY_LIMIT`    | No                | Outbox rows per five-minute run, bounded to 1–500.                                              |

Use the public OpenAI-compatible Qwen endpoint, with the same model ID in the
URL and `LIFTWING_MODEL`:

```text
LIFTWING_MODEL=llm-qwen36-27b
LIFTWING_API_URL=https://api.wikimedia.org/service/lw/inference/v1/models/llm-qwen36-27b/openai/v1/chat/completions
```

Classic Lift Wing `:predict` endpoints are deliberately rejected because public
LLMs use chat completions. No API key is required; Toolforge traffic receives Wikimedia's
known-network rate tier automatically. Other hosts, models, paths, ports,
queries, and fragments are rejected before any network call. The LLM service is
experimental and has no availability SLA, so recent deterministic fallbacks
remain an audited unhealthy condition rather than silently appearing as Qwen
output.

See the [LiftWing large-language-model documentation](https://wikitech.wikimedia.org/wiki/Machine_Learning/LiftWing/Large_Language_Models)
for the current public model catalogue and service contract.

The Wikimedia service account must be able to edit the configured Meta tree,
send email to users, and edit user talk pages on requested wikis. Users must
also allow email from other users for the email channel to work.

## Jobs and operations

- `digest-publish`: 06:15 UTC daily; generates all missed closed non-empty
  periods, publishes Meta pages, refreshes Archive, and queues delivery.
- `digest-deliver`: every five minutes; repairs and drains the outbox.
- `digest-audit`: hourly at minute 23; fails for Meta publication or Archive
  refresh failures, closed periods still ungenerated after eight hours,
  configured Qwen fallbacks, exhausted deliveries, validated editions stuck
  over two hours, or outbox rows stuck over 48 hours.

Two of those conditions are deliberately narrowed, because an alarm no action
can clear is an alarm operators learn to ignore:

- An edition Meta refuses on content grounds — currently the spam blacklist,
  which rejects a URL the rendered wikitext contains — is stored as
  `publication_blocked` rather than `publication_failed`. Republishing the same
  text always fails, so `publish_pending` no longer retries it and the audit
  reports it as `blockedPublications` instead of failing hourly forever. The
  fix is editorial: remove or replace the blacklisted link and regenerate.
  Every other failure, including a permanent authentication one an operator can
  correct, stays `publication_failed` and stays in the retry set.
- The recent-fallback check ignores `out_of_scope` editions. Retiring a
  backfilled edition leaves its generation history in place, and those rows
  never reach a reader, so their fallback says nothing about whether Lift Wing
  is serving the editions that do.

Useful checks:

```sh
toolforge jobs logs digest-publish
toolforge jobs logs digest-deliver
toolforge jobs logs digest-audit
toolforge jobs run digest-publish
toolforge jobs run digest-deliver
```

The three explicitly selected website examples can be regenerated after an
editorial or renderer change without creating a preview channel or touching
Meta, RSS, email, or talk pages. The operator command drafts and validates every
requested Qwen edition before opening its replacement transaction, preserves
the edition IDs and generation-attempt history, and refuses any edition carrying
published or delivery state. Before deployment, the read-only preflight fetches
the exact frozen public facts, exercises live LiftWing generation, validation,
and rendering, reports body sizes, and performs no database writes:

```sh
LIFTWING_MODEL=llm-qwen36-27b LIFTWING_API_URL=https://api.wikimedia.org/service/lw/inference/v1/models/llm-qwen36-27b/openai/v1/chat/completions LIFTWING_USER_AGENT='toolhub-evolved digest preflight (https://toolhub-evolved.toolforge.org/)' .venv/bin/python proxy/digest_liftwing_preflight.py --edition daily:2026-08-13 --edition weekly:2026-W32 --edition monthly:2026-07
```

After that passes and the revision is deployed, regenerate the website-only
editions:

```sh
toolforge jobs run --wait 900 --image python3.13 --filelog -o "$HOME/digest-regenerate.out" -e "$HOME/digest-regenerate.err" --command "$HOME/www/python/venv/bin/python $HOME/repo/proxy/digest_regenerate.py --edition daily:2026-08-13 --edition weekly:2026-W32 --edition monthly:2026-07" digest-regenerate
```

MariaDB stores rendered HTML, wikitext, and text as `MEDIUMTEXT`; deploy-time
migration widens older `TEXT` columns idempotently before the webservice
restart, so large complete indexes do not hit the 64 KiB `TEXT` ceiling.

The signed-in `/v1/digests/status/` endpoint gives bounded status counts. The
public `/v1/digests/` endpoint exposes website publications; RSS exposes only
editions published through the normal cross-channel process.
After correcting a job failure, reset its circuit breaker as described in
`RUNBOOK.md`, run it manually, and confirm that `digest-audit` becomes healthy.
