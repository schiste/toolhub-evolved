<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: the-descriptions-the-wikis-already-wrote -->
<!-- Release title: What the Wikis Wrote, and What the Workers Did -->
<!-- Source range: 752537d1..2eaa393a (8 commits) -->

# What's New for Users

- About fifteen thousand of the fifty-seven thousand entries in the catalogue showed no description at all. Most of that gap was one group: gadgets, the tools a wiki offers you from its preferences page. Nothing had ever tried to describe them.
- We could have asked a model to write those descriptions. We checked first, and found the wikis had already written them — nine gadgets in ten have a description their own maintainer wrote, sitting in a wiki message this catalogue was not reading. Gadgets now carry those words instead of ours.
- They appear in the language they were written in, untranslated. A French gadget reads in French. Translating would mean paraphrasing a maintainer rather than quoting one, and quoting is the better of the two.
- A gadget whose maintainer never wrote that message is left blank rather than filled in with a guess. A blank is a gap somebody can fill; an invented sentence is harder to spot and harder to correct.
- Separately: 235 user scripts had been left permanently without a description by a few bad minutes at the service that reads them, back on the 26th. Failing to reach that service was being filed as though it were an answer, so those pages were never offered to it again. They come back into the queue now, behind everything that has never been tried.
- When that service does answer but the answer is not usable, we now keep a note of what was wrong with it, rather than only that it was refused — and we keep the answer itself, so the note can be checked against what was actually said. Four thousand answers had already been turned down before we started keeping either. Those are being put once more, one time only, so their reasons become readable; almost all of them will be turned down again, and this time we will know why.
- Also in this release: every background job that keeps this catalogue current now has a page of its own. It lists that job's recent runs, how long each took, how much work it got through, and — for the jobs that measure it — how much of the catalogue they have covered so far and whether that is going up. A run that was cut short before it could say what it had done is marked as saying nothing, rather than counted as having done nothing.
