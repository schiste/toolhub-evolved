# `[review.*]` field reference

Every table lives in `.aethyme/config.toml` at the repository root, is read
independently, and is off unless it says `enabled = true`. Unknown keys are
rejected at load rather than ignored, so a typo fails loudly.

## `[review.trigger]`

| Key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `enabled` | bool | `false` | Off means no dimension is ever eligible. |
| `schema_version` | int | current | A version newer than the broker understands is an error, never a fallback. |
| `rule` | array of tables | `[]` | See below. |
| `default_schedule` | table | 600s / 8 / false | Budget for a dimension with no entry in `schedule`. |
| `schedule.<dimension>` | table | -- | Budget for one dimension. |

### `[[review.trigger.rule]]`

A rule fires when **every** condition it names holds. A rule that names no
condition matches every change.

| Key | Type | Required | Meaning |
| --- | --- | --- | --- |
| `require` | list of strings | **yes** | Dimensions this rule demands. An empty or missing `require` is rejected at load. |
| `name` | string | no | Appears in the decision's `because`. Name every rule; the report is unreadable otherwise. |
| `on` | list | no | Lifecycle transitions. Empty means any. |
| `paths` | list of globs | no | Repository-relative. Matching any one path satisfies the condition. |
| `areas` | list | no | `Area:` values the author declared. |
| `surfaces` | list | no | `Surface:` values the author declared. |
| `min_risk` | string | no | Declared `Risk:` at or above this level. |
| `from_fork` | bool | no | Only when the change comes from a fork. |
| `first_time_contributor` | bool | no | Only when the author has not landed here before. |
| `authored_by_model` | bool | no | `true` only when a `Model:` trailer names one; `false` only when none does. |
| `models` | list | no | Only when the declared `Model:` is one of these, compared case-insensitively. |

**Globs.** `*` matches exactly one path segment. `**` matches any number of
segments including zero. Paths are repository-relative with no leading `/` or
`./`, exactly as `git diff --name-only` prints them.

**`on` values.** `pull_request_opened`, `ready_for_review`, `reopened`,
`replacement_commit` (force-push, amend, rebase), `additional_commit`,
`base_retargeted`, `review_dismissed`, `scheduled`, `manual`.

`replacement_commit` and `additional_commit` are separate on purpose: a
force-push that rewrites the same logical change and a commit stacked on top of
already-reviewed work justify different responses.

`merge_queue_entered` is **rejected at load**: nothing a tick can ask the
provider distinguishes it, so a rule waiting for it would never fire. Do not
write it.

The transition is derived by comparing the pull request against the last
observation of it, not delivered by a webhook, so it is available to any tick
and needs no inbound endpoint.

**`min_risk` ranking.** `none` < `low` < `high` = `critical`. An unrecognised
value ranks *above* `low`, so a typo in a risk trailer escalates rather than
silently downgrading.

### `[review.trigger.schedule.<dimension>]`

| Key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `debounce_seconds` | int | `600` | Minimum gap between two reviews of this dimension on one pull request. Inside the window the decision is `defer`, which a later tick reconsiders -- not `skip`, which is settled. |
| `max_per_pull_request` | int | `8` | Cap per pull request. `0` means no cap. |
| `always_on_new_head` | bool | `false` | Re-review when the head moves even past the cap. |

A dimension already reviewed at the current head is skipped before either of
these is consulted.

## `[review.routing]`

| Key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `enabled` | bool | `false` | Off means every dimension is recorded and nothing is performed. |
| `workspace_root` | string | `.aethyme/reviews` | Where a Chau7 review's workspace is created. Relative to the repository root. |
| `default_route` | table | `backend = "record"` | Route for a dimension with no entry in `route`. |
| `route.<dimension>` | table | -- | Route for one dimension. |

### `[review.routing.route.<dimension>]`

| Key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `backend` | `chau7` \| `provider_comment` \| `record` | **required** | Who performs it. |
| `mention` | string | -- | **Required for `provider_comment`.** Stored without the `@`. |
| `instructions` | string | -- | Appended to the generated Chau7 prompt. The generated part is not replaceable. |
| `max_concurrent` | int | `2` | Reviews of this dimension in flight at once, repository-wide. `0` is unbounded. |
| `stale_after_minutes` | int | `360` | Give up on an unfinished review after this long without an update, mark it `abandoned`, and ask again. Stops a dead reviewer holding a slot forever. `0` is never. |

Budgets are per dimension, so a saturated security queue does not stop a code
review being requested.

A Chau7 review whose workspace already holds a live tab is deferred rather than
started twice. The check is on the directory, not the branch: a tab that
wandered onto another branch still occupies that workspace.

## `[review.projection]`

| Key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `enabled` | bool | `false` | Off means no comment and no label. |
| `comment` | bool | `true` | Maintain one Aethyme-owned comment, found by the marker `<!-- aethyme:review -->` and edited in place. |
| `label_prefix` | string | `aethyme/` | Every label Aethyme writes starts with this. A label outside it is somebody else's and is never touched. Empty is rejected at load. |
| `label_areas` | bool | `true` | `aethyme/area:backend` |
| `label_surfaces` | bool | `true` | `aethyme/surface:auth` |
| `label_risk` | bool | `true` | `aethyme/risk:high` |
| `label_reviews` | bool | `true` | `aethyme/review:security`, while one is outstanding. |
| `reserved` | list of strings | `[]` | Label suffixes inside the prefix that Aethyme reads and never writes or removes. |
| `create_missing_labels` | bool | `true` | `gh pr edit --add-label` fails outright on an unknown label. |

`reserved` is the difference between a recomputable label and a decided one.
`aethyme/area:backend` can be deleted and rederived from a trailer still in the
commit. A human's `aethyme/skip-review` has no source to rederive from -- once
written, it *is* the source, and without `reserved` reconciliation would see an
unrecognised label under its own prefix and delete the only record of that
judgement.

## Commit trailers

| Trailer | Read by | Projected as |
| --- | --- | --- |
| `Area:` | a rule's `areas` | `aethyme/area:<value>` |
| `Surface:` | a rule's `surfaces` | `aethyme/surface:<value>` |
| `Risk:` | a rule's `min_risk` | `aethyme/risk:<value>` |
| `Review:` | nothing -- asks for a dimension directly | `aethyme/review:<value>` |
| `Model:` | a rule's `authored_by_model` and `models` | nothing -- who wrote a change is the author's to disclose |

Values are comma-separated and case-insensitive. Trailers may appear anywhere
in the body and are merged across every commit in the change: areas and
surfaces union, the highest risk wins, and the first `Model:` declared wins.

`Model:` is a declaration, not a detection. `Co-Authored-By` is deliberately not
read: it is written by convention, carries a display name rather than a stable
identifier, and appears on commits a model only helped with.

A declaration can add a review and can never remove one.

## Errors at load

| Error | Cause |
| --- | --- |
| `rule N requires no review types` | A rule with an empty `require`. |
| `rule N waits for <trigger>, which no tick can report` | `on` names `merge_queue_entered`. Remove it; the rule would never fire. |
| `unknown field` | A typo, or a field from a newer broker. |
| `schema_version N is newer than this broker understands` | Upgrade `aethyme`, or pin the policy. It refuses rather than falling back, because silently reviewing nothing is the failure this must not have. |
| `route <name> uses provider_comment without a mention` | `provider_comment` with no bot to mention. |
| `label_prefix must not be empty` | An empty prefix would make every label in the repository Aethyme's. |
