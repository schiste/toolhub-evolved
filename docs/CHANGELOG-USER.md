<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: the-threshold-that-fell-on-the-hour -->
<!-- Release title: The Threshold That Fell On The Hour -->
<!-- Source range: c7d15ae..687bd78 (2 commits) -->

# What's New for Users

- When a background job is asked to stop, it is now always the job itself that hears the request, in every place Evolved starts one. Two steps of the deploy -- the database migration and the cache warm-up -- were starting their work behind a wrapper that received the stop request on their behalf and never passed it on, so instead of finishing the statement in hand they were cut off where they stood. A migration is the worst possible thing to interrupt mid-sentence.
- The job that keeps contributor identities consistent could get stuck for an extra hour at a time, silently. Each run leaves a marker while it works and clears it when it finishes; a run that is killed cannot clear its own marker, so the next run is allowed to remove one that is old enough to be certain nobody is still using it.
- That age threshold was set to exactly one hour, and the job runs exactly once an hour -- so the marker was always inspected at the very moment it became removable, and whichever arrived first decided the outcome. Of the twenty-four times this actually happened, the recorded ages ranged from 3,588 to 3,613 seconds: ten of them fell on the wrong side and waited another silent hour for no reason.
- The threshold is now fifty minutes, which is reached comfortably before the next run looks at it, and the job is allowed twenty-five minutes to finish rather than fifteen. Its slowest genuine run on record took just over thirteen minutes, so it now has roughly twice the room it needs instead of slightly less.
