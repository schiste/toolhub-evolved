---
name: aethyme-review-rule-maker
description: Write or tune this repository's Aethyme review rules -- which
  changes need which reviews, who performs them, and what appears on the pull
  request. Use when asked to set up, enable, debug, or change review routing,
  review triggers, PR labels, or the `[review.*]` tables in
  `.aethyme/config.toml`.
---

# Aethyme Review Rule Maker

Three tables in `.aethyme/config.toml` decide which reviews a change needs
(`[review.trigger]`), who performs them (`[review.routing]`), and what the pull
request shows (`[review.projection]`). All three are off by default. This skill
is the procedure for writing them against a real repository instead of from
imagination.

Full field grammar: [`references/review-rules.md`](references/review-rules.md).
Load it when you need a field's exact name, type, or default.

## The one rule that shapes everything else

**A rule is a floor an author cannot lower.** Eligibility is the union of what
the repository requires and what the author declared in commit trailers, never
the intersection. So the cost of a rule that is too broad is wasted reviews,
and the cost of one that is too narrow is a missed review. Write the narrow
guards first and widen them with evidence.

## Procedure

### 1. Read the current state before changing anything

```bash
aethyme broker advanced review plan --base <default-branch> --pr 0
```

It performs nothing. `trigger_enabled`, `routing_enabled`,
`projection_enabled` tell you what is already on; `changed_paths` and
`classification` tell you whether the command is reading the tree you expect.
If `changed_paths` is 0 against a branch with work on it, you are standing in
the wrong worktree -- compare `policy_root` and `change_root` in the report.

### 2. Find the paths that must never miss a review

Do not guess, and do not ask the user to guess. Look, then propose a list for
them to cut down. Search for the places where a change can grant itself
authority or move money:

```bash
# CI that can mint credentials, and anything that edits it
ls .github/workflows/ .gitlab-ci.yml 2>/dev/null
# authentication, authorization, secrets, crypto
rg -l --files-with-matches -i 'authenticat|authoriz|\bjwt\b|secret|credential|private_key' --glob '!**/test*' | head -30
# money and data destruction
rg -l -i 'stripe|payment|charge|refund|DROP TABLE|delete_all' --glob '!**/test*' | head -20
# schema migrations
fd -t d -d 3 'migrations?' 2>/dev/null | head
```

Present the candidates and say which you would keep. A list of three to six
paths is a working guard; a list of forty is a repository-wide review under
another name, and the schedule will end up silently dropping most of it.

### 3. Name the dimensions

`require = [...]` takes free strings, not an enum. Pick names the repository
would use in conversation -- `code`, `security`, `performance`, `data`,
`accessibility`, `i18n`. Each name is separately routed and separately
budgeted, so a dimension is worth creating exactly when it would go to a
different reviewer or deserve a different quota. Two dimensions that always
go to the same place with the same budget should be one.

### 4. Write the trigger table only, and leave the rest off

```toml
[review.trigger]
enabled = true

[[review.trigger.rule]]
name = "always-code-review"
require = ["code"]

[[review.trigger.rule]]
name = "security-sensitive-paths"
require = ["security"]
paths = [".github/workflows/**", "src/auth/**"]
```

Routing and projection stay off through this step. A wrong rule now costs a
line in a JSON report; a wrong rule with projection on costs a label on
somebody's pull request.

### 5. Replay it against real history

This is the step that separates a rule that works from one that reads well.
Take branches that actually merged and check what the policy would have said:

```bash
for base in HEAD~1 HEAD~5 HEAD~20; do
  echo "=== $base ==="
  aethyme broker advanced review plan --base "$base" --pr 0 \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print([ (e["review_type"], e["because"]) for e in d["eligible"] ])'
done
```

Read the `because` array, not just the dimension: it names the rule that
fired. A dimension appearing with a rule you did not expect is the rule to fix.

Two failure shapes to look for specifically:

- **Every change eligible for everything.** Usually a rule with no conditions
  that was meant to have one, or `paths` written with a leading `/` or a
  `./` prefix -- paths are repository-relative, exactly as `git diff
  --name-only` prints them.
- **A guarded path producing nothing.** Check the glob: `*` matches one
  segment and `**` matches any number including zero, so `src/*/auth.rs` does
  not match `src/a/b/auth.rs` but `src/**/auth.rs` does.

### 6. Set the budget before turning on a backend

Rules decide what a change deserves. `schedule` decides what it gets, and it
is the half that keeps an active branch from spending forty security reviews.

```toml
[review.trigger.default_schedule]
debounce_seconds = 600
max_per_pull_request = 8

[review.trigger.schedule.security]
debounce_seconds = 0
max_per_pull_request = 0
```

Ask the concrete question rather than the abstract one: *on the busiest pull
request this repository had last month, how many reviews of each dimension
would have been acceptable?* That number is `max_per_pull_request`. Exempt a
dimension from the cap only when a missed one is worse than a wasted one --
which is usually true of `security` and usually false of everything else.

### 7. Turn on projection, then routing

In that order. Projection writes a comment and labels, which a human can read
and delete. Routing starts agents and mentions bots, which a human cannot
un-start.

```toml
[review.projection]
enabled = true
label_prefix = "aethyme/"
reserved = ["skip-review"]
```

`label_prefix` is the whole safety mechanism: Aethyme never touches a label
outside it. `reserved` names labels inside it that Aethyme reads and never
writes -- that is where a human parks a decision the broker must not
recompute away.

```toml
[review.routing]
enabled = true

[review.routing.default_route]
backend = "record"

[review.routing.route.security]
backend = "chau7"
max_concurrent = 1
```

Keep `default_route` on `record`. A dimension someone adds later then gets
written down rather than silently starting an agent nobody budgeted for.

## Asking the coder for classification

Rules can read what the author declared. Trailers cost a coding agent nothing
-- it is already writing a commit message and already knows what it changed:

```
Area: backend
Surface: auth
Risk: high
Review: security
```

To get them written, add the instruction to `.aethyme/overrides/agents.json`
and rerun `aethyme deploy --repo "$PWD"`. Do not rely on them for a
guard: a trailer is one line of unverified text, which is exactly why it can
escalate a review and can never waive one.

## What to hand back

A diff of `.aethyme/config.toml`, plus the `review plan` output for two or
three real changes showing what the new rules decide. Do not report a policy as
working on the strength of it parsing.
