<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: measured-not-reasoned -->
<!-- Release title: Measured, Not Reasoned -->
<!-- Source range: 2dc71230..0b0af976 (3 commits) -->

# What's New for Users

- The background job that works out which contributor is behind which tool is running again. It had stopped overnight: the site stops a job that fails three times in a row, on the assumption something is properly wrong with it, and this one had. Nothing a visitor sees was affected, and no data was lost -- the work simply did not advance while it was stopped.
- The cause was an allowance that had been guessed at twice. Each of these jobs reserves a small number of simultaneous conversations with the database, and the figure had been worked out by reading the code rather than watching it run. Reading gave two, then three; the job actually needs four, because it quietly claims a third thing partway through its work that no amount of reading the surrounding code revealed. It now gets what it was measured using.
- Three further jobs that also claim exclusive access -- the catalogue synchronizer and the two account synchronizers -- had the same allowance without ever being told they needed it, and have been corrected as well. A check now reads the code for every job that claims exclusive access, so the next one added cannot be forgotten in the way these three were.
