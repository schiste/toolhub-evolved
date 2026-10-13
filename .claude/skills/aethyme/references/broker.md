## Broker Coordination (multi-agent repository)

This repository coordinates concurrent agent sessions through the Aethyme
broker. Other agents may be working in sibling worktrees right now. The
`aethyme` router and its engine sibling are installed once for the user;
check the paired runtime with `aethyme --version` and
`aethyme-engine-cli --version`.
Follow this protocol:

When `aethyme broker advanced hooks install` is active (or its pre-commit command is
wired into an existing hook manager), Git enforces the session boundary on
protected branches: local broker state requires the exact worktree to belong
to a live session, and fetched upstream divergence blocks the commit before
Git writes it. Staged changes remain intact and the refusal prints a valid
adoption or reconciliation command. This enforcement is local-only; without a
local broker database, contributors who have not deployed Aethyme are not
blocked.

1. **Broker entry point, before editing**: check current activity, create an
   isolated broker worktree, and work from that checkout:

   ```bash
   aethyme broker status --json    # who is working on what
   aethyme broker start --task "<your task>" --short-name "<short name>" --path <planned-path>
   ```

   `cd` into the reported worktree before editing. If you are already in a
   dedicated worktree, use
   `aethyme broker start --adopt --task "<your task>" --short-name "<short name>" --path <planned-path>` instead.
   Repeat `--path` for every file or trailing-slash directory known up front.
   The broker validates the whole set first, then creates the session plus
   explicit leases atomically. Omit `--path` only when no target is known yet.
   If `status` shows another session holding leases on the files you plan
   to change, prefer working elsewhere first or say so in your report —
   overlapping edits will conflict at merge time.
   When you edit a file another live session is changing, the broker tells you
   in context who, where and whether Git would conflict, never blocking the
   edit; `aethyme broker advanced note send --to-session <id>` reaches that
   agent, and its notes reach you at your next turn.

2. **Lease additional shared files before the diff exists**. Prefer the
   atomic `start --path` / `start --adopt --path` declaration above for initial intent. If the
   session already exists and scope expands, claim the new path explicitly:

   ```bash
   aethyme broker advanced leases claim <path> --session <your-session-id>
   aethyme broker advanced leases release <path> --session <your-session-id>
   ```

   Use a trailing `/` for directory leases. Implicit leases refresh from
   changed files, but explicit leases are clearer for planned shared edits.
   A claim is refused only by another explicit lease whose holder is actively
   working, and never in a `verify-only` repository; every other overlap comes
   back as a warning naming the holder, with the `note send` command to
   coordinate.

   Orchestration with no path -- a release, a merge chain -- is claimed by
   name instead: `aethyme broker advanced ownership claim "release v1.2.0"
   --session <your-session-id> --reason "<why>"`. `status` shows every claim,
   its holder and when the holder last acted; a claim is refused only while
   its holder is working, and a quiet holder's claim is taken over.

3. **Guard broad rewrite commands**. For formatters, code generators, or any
   command likely to touch many files, run through the broker guard:

   ```bash
   aethyme broker advanced exec --session <your-session-id> -- <command>
   ```

   The guard fails if the command leaves dirty paths outside your explicit
   leases or in files that were untracked before your session began.

4. **While working**: commit early and small. Only committed work can be
   verified and integrated. Never switch branches inside someone else's
   worktree; never edit files outside your own worktree.

   **If `.aethyme/config.toml`, as committed on the default branch, sets
   `[delivery] push_session_branches = true`, push your session branch as you
   go.** Work that exists only in a worktree
   is lost with it, and nobody can review what was never pushed. After each
   commit:

   ```bash
   aethyme broker push --session <your-session-id>
   ```

   This pushes your own session branch (`agent/<slug>`) to the default
   branch's remote and touches no other ref. A fast-forward is pushed plainly;
   a branch you rewrote (for example after a rebase) is pushed only under a
   lease on the commit the broker last pushed for your session. Uncommitted
   files are reported, not pushed, so commit before you push. Once there is a first meaningful commit, open a draft
   pull request, and keep pushing to it until it is ready for review:

   ```bash
   aethyme broker push --session <your-session-id> --pr
   ```

   `--pr` opens a draft PR, or reports the one already open. The policy is
   the authorization for exactly these two things -- pushing your own session
   branch and opening a draft PR -- and nothing more: it does not authorize
   merging, marking a PR ready, or pushing any other ref. `broker status` and
   `broker doctor` report sessions with unpushed commits, and
   `aethyme broker finish` refuses to close a session while its commits are
   unpushed. If the work should genuinely not be kept, say so explicitly with
   `aethyme broker finish --session <id> --abandon --reason "<why>"`.
   Each push also fetches the default branch and reports how far your branch
   is behind it and whether merging would conflict, with the command to catch
   up; `broker status` shows the same as `session.behind-main`. Catch up with
   `aethyme broker sync --session <id>` when it warns, before the pull request
   reports the conflict: it rebases an unpublished branch or merges the default
   branch into a published one, and changes nothing if that would conflict.
   Sync is local only: it never pushes, so run `aethyme broker push --session
   <id>` afterwards to publish the caught-up branch.
   `broker start` and `start --reuse` refresh the default branch first, so a
   new worktree starts from the latest fetched tip. In a repository
   with `[promote] mode = "verify-only"`, `broker submit` is a pre-flight
   against the current default branch; the integration branch is not used.
   When `broker status` shows `coordination.land-shared-edit-first`, another
   session changes the same lines or symbol as yours: follow it -- the named
   session lands only the shared edit as its own small PR, then both rebase
   on the default branch -- rather than waiting or building on the other
   session's unmerged branch.
   Without the policy, pushing stays a separately authorized action (step 9).

5. **Gate resources are per worker**. Broker gate runs take path-scoped owner
   locks and export `AETHYME_GATE_WORKER_ID` plus `AETHYME_TEST_DB_SUFFIX`.
   Gate commands that need a test database, cache namespace, or similar
   external state should suffix it with that value instead of sharing one
   fixed name.

   If this repository declares committed graph fragments authoritative in
   `.aethyme/config.toml`, graph freshness is an enforced deployment-integrity
   check, not a semantic gate suggestion. Session gates, full-tree CI,
   repository pre-push, and submit verify the exact tree in a disposable
   checkout and refuse stale or wrong-version fragments without rewriting your
   worktree. Run `aethyme graph status --repo .`, review
   `aethyme graph refresh plan --repo . --diff`, and authorize only its full
   digest with `aethyme graph refresh execute --repo . --confirm <plan-sha256>`.
   Never rebuild committed fragments with an unpinned binary. If execution was
   interrupted, use the exact `graph refresh recover --plan <plan-sha256>`
   handoff; do not retry blindly.

   Graph support is repository opt-in. Explore never generates graph state.
   If Explore reports `graph_store_missing`, continue with its bounded manual
   verification steps, or materialize the verified committed fragments for
   this worktree with `aethyme graph materialize --repo .`. Do not enable graph
   authority merely to silence a degraded response.

6. **When your task is complete**, use verified broker integration by
   default instead of manually combining concurrent session branches:

   ```bash
   aethyme broker submit --session <your-session-id>
   ```

   This simulates the merge and runs only the checks your diff affects.
   Submit replays session-owned commits as an ordered, single-parent patch
   series. If your session contains an owned merge commit, submission refuses
   safely and prints the accepted checkpoint plus an exact recovery sequence.
   Follow it in order: preserve the current HEAD on the named recovery branch
   before flattening the reviewed tree change. Never reset first.
   `broker submit` promotes to the local integration branch; it does not
   publish a remote branch, create a pull request, or push a release tag.
   Publication is a separate, explicitly authorized operator action. When
   publication is authorized, review the exact promoted prefix first, then
   confirm the plan's full publication SHA:

   ```bash
   aethyme broker advanced ship plan --entry <promoted-entry-id>
   aethyme broker advanced ship execute --entry <promoted-entry-id> --confirm <full-publication-sha>
   ```

   By default, the selected entry is a prefix boundary: every earlier
   promoted-but-unpublished entry ships with it. In promote-mode repositories,
   `--only` can publish one independent entry without changing that default:

   ```bash
   aethyme broker advanced ship plan --entry <promoted-entry-id> --only
   aethyme broker advanced ship execute --entry <promoted-entry-id> --only --confirm <full-publication-sha> --plan <sha256>
   ```

   The plan refuses when an earlier unshipped entry is required by ancestry,
   changed-path overlap, or a declared `Depends-On` trailer. Otherwise it gates
   the exact tree made from the remote default branch plus only the selected
   entry. Planning does not move refs, though it may record gate results in the
   local cache; execution requires the reviewed plan digest. After publication,
   the broker rebases the remaining pending entries onto the published commit
   in integration and re-runs gates only for replayed trees that changed.
   Review that reconciliation report. If it refuses or cannot apply safely,
   use `aethyme broker advanced integration reconcile --upstream <published-sha> --dry-run`
   and follow its reviewed apply plan. `broker main reconcile plan/apply` remains
   the separate operation for advancing the local default checkout from
   integration; independent publication does not mark the other queue entries
   shipped or change their promotion order.

   Prefer this reviewed broker ship workflow over a raw push. Never infer
   publication authority from permission to edit, submit, or promote.
   Without publication authority, stop after submit and report the promoted
   entry. Under `push_session_branches` (step 4), your pushed session branch
   and its draft PR are the delivery: report the PR rather than a promoted
   entry. Repositories that deliver through pull requests usually also set
   `[promote] mode = "verify-only"`, so verified work does not pile up
   unpublished on the local integration branch.
   Report the outcome (verified / rejected / conflict) in your summary.
   Afterwards, finish the session with
   `aethyme broker finish --session <id>`, or point it at a follow-up task
   with `aethyme broker start --reuse --task "..." --short-name "<short name>"`. `finish` closes broker
   state but deliberately leaves the worktree available for review or reuse.
   When it reports cleanup is safe, reclaim that exact worktree with
   `aethyme broker finish cleanup <id>`. Operators can periodically review all
   retained broker-owned worktrees with
   `aethyme broker finish cleanup --all-cleaned` and apply the unchanged plan
   explicitly with `aethyme broker finish cleanup --all-cleaned --apply`.

7. **If a file named `.aethyme/broker-action-required.md` appears in your
   worktree**, read it immediately: your submission conflicted. It names
   the conflicting files, the blocking session, and the exact rebase
   steps. Resolve, commit, and resubmit.

8. **Treat broker advisories as delivered work context, not as blockers.**
   The broker surfaces outstanding session advisories after post-commit,
   before expensive gates, and on common broker commands. When a notice
   appears—or after rebasing or reusing a worktree—inspect
   `aethyme broker status --json` before continuing on the named paths.

   `.aethyme/broker-advisory.md` is a gitignored persistence projection; it
   is not automatically visible to agents and the broker database remains
   authoritative. Read it when a delivery surface points to it. Directory
   leases cover descendants, and repeated overlaps are deduplicated and
   deterministically ordered. Acknowledging a notice stops repeat delivery
   but does not clear the queue entry's unpublished path exposure. Session
   close and rebase do not clear it either. Only verified publication or
   confirmed external reconciliation resolves an exposure; publishing a
   selected integration prefix clears only entries contained in the verified
   remote tip. Advisories never expand gate selection or block submit,
   promotion, or shipping.

9. **Git operations remain available to agents.** The broker coordinates
   concurrent work; it does not remove Git capabilities. When the user's
   request or the repository's documented workflow authorizes the resulting
   local or remote state change, agents may perform every required Git
   operation, including clone, fetch, pull, switch, branch, add, commit,
   stash, merge, cherry-pick, rebase, revert, reset, tag, push (including
   force-push when explicitly authorized), and deletion of an exact ref.

   Operations that require coordination **must go through the broker**. Use a
   dedicated broker workflow when one exists (for example `broker submit` for
   verified integration). Run other coordinated Git operations through the
   durable Git operation coordinator:

   ```bash
   aethyme broker advanced git --session <your-session-id> \
     [--repo <owner/name>] --reason "<authorization>" -- <git-args> ...
   ```

   Read-only GitHub CLI inspection and explicitly authorized local `gh auth`
   setup may run directly. Every GitHub repository or account mutation
   (pull requests, issues, comments, workflows, releases, settings, secrets,
   or non-GET API calls) must use the GitHub operation coordinator:

   ```bash
   aethyme broker advanced gh --session <your-session-id> \
     --repo <owner/name> --reason "<authorization>" -- <gh-args> ...
   ```

   The broker classifies known commands and fails closed on ambiguity. Add
   `--effect write|destructive --scope <resource>` before `--` for an
   unrecognized command. Destructive operations also require `--destructive`.
   Every coordinated write requires a concise `--reason` identifying the user
   request or documented workflow that authorized it.
   If a crashed command leaves an unknown outcome, inspect external state and
   use `aethyme broker advanced operations reconcile`; do not retry blindly.

   Direct Git is limited to read-only inspection and operations confined to
   the isolated session worktree and session branch that cannot affect other
   sessions. Direct `gh` is limited to read-only inspection and local
   authentication setup. Any command that
   can move shared refs, the default branch,
   `aethyme/integration`, remote-tracking refs, tags, or remote state is
   coordinated and must not run outside the broker. For destructive or remote
   operations, resolve the exact repository and refs first, preserve unrelated
   work, and require the authorization that operation normally needs.
   Do not infer permission to publish merely from permission to edit or submit.
   An explicitly authorized operator or release workflow may merge, tag, push,
   force-push, or delete refs through the broker; authorization does not permit
   bypassing coordination.