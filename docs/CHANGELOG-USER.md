<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: the-statistics-page-stops-taking-the-site-down -->
<!-- Release title: The Statistics Page Stops Taking the Site Down -->
<!-- Source range: c24a0353..ab96b917 (5 commits) -->

# What's New for Users

- The site stops failing while you are using it. Every so often a page would return an error, or simply hang, for no reason you could see -- and it was rarely the page you were on that caused it. The catalog statistics are assembled from every tool, every person and every relationship in the local copy of the catalog, and until now that assembly could happen inside somebody's request. Whoever asked first paid for it, and if the work grew large enough the whole web service was stopped and restarted underneath everybody. That is the error you were seeing on other pages.
- The statistics page answers immediately instead of building itself while you wait. The figures were being recomputed at most every six hours but advertised as good for fifteen minutes, so most visitors arrived just after they expired and were made to rebuild them -- around thirteen seconds of work, in front of a spinner, for a page that is the same for everyone. The numbers are now prepared in the background every ten minutes and simply handed over when you ask.
- When the background preparation falls behind, you get the figures anyway. Rather than making one unlucky visitor wait for a rebuild, the page shows the most recent set it has, with the time it was produced, which is already displayed on the page. Only if that set is more than six hours old -- meaning the background work has genuinely stopped -- does anyone rebuild it, because at that point the alternative is numbers nobody should trust.
- The whole catalog no longer has to fit in memory at once to be counted. Producing the figures used to gather all 16,827 tools into a single structure before counting anything, which is what pushed the server over its limit. It now reads the catalog in small batches and keeps only the running totals, so the cost stays flat as the catalog grows. The published numbers are unchanged -- every one of them is checked against a recorded copy of the previous output.
