<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: one-empty-answer-is-not-a-blank-record -->
<!-- Release title: One Empty Answer Is Not A Blank Record -->
<!-- Source range: c2635a0e..HEAD -->

# What's New for Users

- A tool that already had a description was about to lose it, and now will not. The catalogue has been going back over its records to work out who each tool is for. Where it could not tell, it was filing the whole record as "nothing could be read here" — including the description and keywords it had read perfectly well the first time.
- Nothing had disappeared from the site yet. Those records kept showing what they always showed; the loss would only have appeared the next time each page was rebuilt, which happens gradually. 1,479 records were affected and the count was growing by about 500 an hour.
- The records have been restored, and the rule corrected. A record is now judged by everything it holds rather than by the last question asked of it, so a question that comes back empty leaves the rest of it alone.
- A record that genuinely holds nothing is still marked as such. That distinction is what stops the catalogue asking the same unanswerable page over and over.
