#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Say how many catalogue records a projected field actually reaches today.

Twice in two days a change shipped correct and unreachable. The inferred
keyword floor was sound and moved exactly one tool, because the tools with a
short keyword list and the tools with a usable reading were almost disjoint
sets. `audiences` was sound and reached 140 records an hour out of 51,266,
because a stored answer looked current to a window that only compares source
fingerprints. Both were found afterwards, by counting in production what should
have been counted before shipping.

The question that would have caught both is the same one, and it is cheap:
*how many records does this actually reach today?* This answers it as a command
rather than as a probe written from scratch each time, which is what it was the
first eight times.

    TOOLHUB_DB_URL=... python3 tools/field_reach.py
    TOOLHUB_DB_URL=... python3 tools/field_reach.py --field audiences --json

Read the `empty` column before shipping something that fills a field, and the
`by source` breakdown after: the first is the population a change can reach,
the second is who is actually answering for it. Neither is what a test can tell
you, because both are facts about the catalogue rather than about the code.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "proxy"))

from sqlalchemy import select  # noqa: E402

from backend import db  # noqa: E402
from backend.catalog_projection import PROJECTED_FIELDS  # noqa: E402
from backend.models import CatalogToolProjection  # noqa: E402

#: How a tool name says what kind of record it is. Reach is rarely uniform
#: across them -- `audiences` was at 3.6% on Toolhub tools and 0% on both wiki
#: lanes -- and an average over all three hides exactly the gap worth seeing.
KINDS = (("userscript-", "user script"), ("gadget-", "gadget"))


def kind_of(name: str) -> str:
    """Return which lane produced a record, from its catalogue name."""
    for prefix, label in KINDS:
        if name.startswith(prefix):
            return label
    return "toolhub tool"


def survey(fields: tuple[str, ...]) -> dict[str, dict]:
    """Return, per field, how many records carry it and who answered for it.

    One pass over the projection rather than one query per field: the table is
    tens of thousands of rows and the interesting output is every field at once,
    so a query each would read it fourteen times to say the same thing.
    """
    filled: dict[str, Counter] = {field: Counter() for field in fields}
    sources: dict[str, Counter] = {field: Counter() for field in fields}
    totals: Counter = Counter()
    with db.session_scope() as session:
        rows = session.execute(
            select(
                CatalogToolProjection.tool_name,
                CatalogToolProjection.effective_record,
                CatalogToolProjection.provenance,
            )
        ).yield_per(1000)
        for name, record, provenance in rows:
            kind = kind_of(name)
            totals[kind] += 1
            for field in fields:
                if not (record or {}).get(field):
                    continue
                filled[field][kind] += 1
                entries = (provenance or {}).get(field) or []
                winner = next((e for e in entries if isinstance(e, dict) and e.get("effective")), None)
                if winner is None and entries and isinstance(entries[0], dict):
                    winner = entries[0]
                sources[field][str((winner or {}).get("source") or "unrecorded")] += 1
    return {
        field: {
            "filled": dict(filled[field]),
            "empty": {kind: totals[kind] - filled[field][kind] for kind in totals},
            "by source": dict(sources[field].most_common()),
        }
        for field in fields
    }


def render(report: dict[str, dict]) -> str:
    """Return the report as a table, widest gap first."""
    lines = []
    for field, data in sorted(report.items(), key=lambda item: -sum(item[1]["empty"].values())):
        total_filled = sum(data["filled"].values())
        total_empty = sum(data["empty"].values())
        share = total_filled / (total_filled + total_empty) if total_filled + total_empty else 0
        lines.append(f"\n{field}  --  {total_filled} filled, {total_empty} empty ({share:.1%} covered)")
        for kind in sorted(data["empty"]):
            lines.append(f"    {kind:14} filled {data['filled'].get(kind, 0):6d}   empty {data['empty'][kind]:6d}")
        if data["by source"]:
            named = "  ".join(f"{source}={count}" for source, count in data["by source"].items())
            lines.append(f"    answered by: {named}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--field", action="append", help="limit to one field; repeatable")
    parser.add_argument("--json", action="store_true", help="emit the report as JSON")
    args = parser.parse_args(argv)

    # Arguments before environment: a misspelled field is wrong wherever it is
    # run, and reporting the missing database first would hide it behind a
    # setup problem the reader then fixes only to be told the real one.
    unknown = [field for field in (args.field or []) if field not in PROJECTED_FIELDS]
    if unknown:
        sys.stderr.write(f"field_reach: not projected fields: {', '.join(unknown)}\n")
        return 2
    url = os.environ.get("TOOLHUB_DB_URL")
    if not url:
        sys.stderr.write("field_reach: TOOLHUB_DB_URL is not set, so there is no catalogue to count\n")
        return 2

    db.configure(url)
    report = survey(tuple(args.field) if args.field else PROJECTED_FIELDS)
    print(json.dumps(report, indent=2, sort_keys=True) if args.json else render(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
