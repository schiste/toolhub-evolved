<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: the-copy-you-already-had -->
<!-- Release title: The Copy You Already Had -->
<!-- Source range: 79c9aa3b..c53f5a9a (2 commits) -->

# What's New for Users

- The user script directory no longer stalls while the wiki census is running. The page asks for its wiki list before it draws anything, and that request was queuing behind the hourly sweep that rebuilds the list — so during a sweep the page sat waiting for a copy the service already had. It now hands over the stored copy immediately and only waits when there is genuinely nothing to hand over.
- The tool relationship graph no longer makes an unlucky visitor wait for it to be rebuilt. Whenever background work changed a tool's facets, the saved graph was thrown away, and the next person to open the page paid for the whole rebuild — close to four seconds — while looking at it. The saved copy is now kept and marked for refresh instead, so that person gets the graph at once and the new one arrives behind them.
- The trade is that the graph can briefly be a few minutes behind a facet change. That is the same small delay the service already accepted elsewhere, and in exchange nobody waits.
- Background maintenance jobs stopped colliding with each other. An hourly reconciliation pass was holding a database table for the length of its whole run, which made the continuous repository scan wait fifty seconds and give up. It now works through the same backlog in small committed steps, so the two no longer block each other.
