<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: every-wiki-in-turn -->
<!-- Release title: Every Wiki, In Turn -->
<!-- Source range: 055fdc8b..63afb6b6 (7 commits) -->

# What's New for Users

- The gadgets and user scripts this site catalogs are no longer only the ones written on French Wikipedia, Meta and English Wikipedia. Discovery now reaches every Wikimedia wiki that can be read from the outside -- 1,028 of them, in some three hundred languages -- so a script maintained on Wikisource, on a small Wikipedia, or on a project nobody thinks to look at is catalogued, dated and ranked on the same terms as one written on the largest wiki there is.
- The wikis take turns rather than all going at once. Each run works through the wikis most overdue for a look and stops when its time is up; whoever it did not reach is simply first in line next time. Nothing is dropped and nothing is rushed, which is what keeps a thousand wikis from turning into a queue that never drains or a load the shared Wikimedia databases would have to absorb in one go.
- How often a wiki is revisited is now decided by that wiki. One whose scripts change every day is looked at more often; one where nothing has moved in years drifts to a monthly check and eventually a quarterly one, and wikis that are closed for editing settle at the slowest rate of all. The effort follows the activity instead of being spread evenly over projects that do not need it.
- One wiki having a bad afternoon no longer holds up the others. Previously a single unreachable wiki -- or one page that the databases could not answer for -- ended the whole run, and because the wikis were worked through in a fixed order, whichever project happened to come later stopped being updated at all. Now a wiki that fails is noted, given a rest, and left behind while the rest of the run continues.
- The list of wikis maintains itself. It is read from Wikimedia's own register of its projects, refreshed weekly, so a newly created wiki starts being covered without anyone editing a configuration file, and a wiki that closes is marked as closed rather than silently disappearing.
- Nothing about how any of this appears has changed: the same catalog, the same dates, the same sorting. What changes is how much of the movement is in it.
