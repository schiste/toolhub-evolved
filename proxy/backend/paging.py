# SPDX-License-Identifier: GPL-3.0-or-later
"""The one page-size ceiling every read path shares.

Mirrors ``PAGE_SIZE_OPTIONS`` in ``public_html/lib/core/paging.js``: the largest
size any "how many per page" control can ask for. Every clamp in this package
rounds down silently rather than rejecting, so a ceiling below what the UI
offers is invisible from the outside -- the reader gets a short page while the
pager keeps dividing the total by the size that was requested, leaving every
page past the clamp unreachable with nothing on screen to explain it.

Two layers clamp, and both have to agree: the HTTP argument parsers
(``v1_accounts``, ``v1_people``, ``catalog_read``) and the query builders they
call (``account_directory``, ``community_search``, ``people_index``). Raising
only the outer one moves the silence rather than removing it.
"""

from __future__ import annotations

MAX_PAGE_SIZE = 144
# Deepest page any pager can reach. A page number is an OFFSET, so the cost of
# asking for page N is proportional to N, not to the page size: with
# MAX_PAGE_SIZE at 144 the previous ceiling of 100_000 let an anonymous request
# ask for OFFSET 14_399_856, which walks the whole ordered index to return
# nothing. Real page controls stop paginating well before this; 10_000 pages at
# the maximum page size already covers every population this catalog can hold.
MAX_PAGE_NUMBER = 10_000
