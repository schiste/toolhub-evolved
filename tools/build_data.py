#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build a rich, self-contained data.js from Toolhub API snapshots.

Everything rendered by the demo is real catalog data EXCEPT per-tool
`weeklyViews`, which the API does not expose. We synthesize it here
*deterministically* (hash of the tool name) so the "popular" ranking is stable
and believable across reloads rather than random noise.

Refresh inputs, then re-run this script:
    data/tools_p1.json .. tools_p3.json   (?page_size=100&page=N&ordering=name)
    data/tools_recent.json                (?page_size=12&ordering=-modified_date)
    data/lists_raw.json                    (/api/lists/?featured=true)
    data/list_<id>.json                    (/api/lists/<id>/  for each featured id)
    data/home_raw.json                     (/api/ui/home/)
"""
import glob
import hashlib
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
# Which featured list seeds the "Featured tools" strip (the richest one).
FEATURED_LIST_ID = 97  # "Wikidata Power Tools" (13 tools)


def load(name):
    with open(os.path.join(DATA, name), encoding="utf-8") as fh:
        return json.load(fh)


def stable_int(s):
    """Deterministic 0..2^32 int from a string (Python's hash() is salted)."""
    return int(hashlib.md5(s.encode("utf-8")).hexdigest()[:8], 16)


def weekly_views(name):
    """Plausible long-tailed weekly view count, stable per tool."""
    h = stable_int(name)
    bucket = h % 100
    if bucket >= 92:        # ~8% are "hot"
        return 1000 + h % 1500
    if bucket >= 70:        # ~22% medium
        return 250 + h % 750
    return 20 + h % 230     # the long tail


def status_of(tool):
    if tool.get("deprecated"):
        return {"level": "red", "label": "Deprecated"}
    if tool.get("experimental"):
        return {"level": "yellow", "label": "Experimental"}
    return {"level": "green", "label": "Healthy"}


def first_url(v):
    """Pull a single URL from a string / list-of-strings / list-of-{url} field."""
    if not v:
        return None
    if isinstance(v, str):
        return v
    if isinstance(v, list) and v:
        x = v[0]
        return x.get("url") if isinstance(x, dict) else x
    return None


def maintainer(tool):
    authors = tool.get("author") or []
    if authors and isinstance(authors[0], dict) and authors[0].get("name"):
        return authors[0]["name"]
    cb = tool.get("created_by") or {}
    return cb.get("username") or "Unknown"


def compact(tool):
    """One tool, trimmed to what the UI (cards + detail view) needs."""
    ann = tool.get("annotations") or {}
    return {
        "name": tool["name"],
        "title": tool.get("title") or tool["name"],
        "description": tool.get("description") or "",
        "url": tool.get("url") or "",
        "icon": tool.get("icon"),  # Commons File: URL (often null)
        "keywords": tool.get("keywords") or [],
        "maintainer": maintainer(tool),
        "authors": [a.get("name") for a in (tool.get("author") or []) if isinstance(a, dict) and a.get("name")],
        "toolType": tool.get("tool_type"),
        "license": tool.get("license"),
        "repository": tool.get("repository"),
        "apiUrl": tool.get("api_url"),
        "technologyUsed": tool.get("technology_used") or [],
        "audiences": ann.get("audiences") or [],
        "tasks": ann.get("tasks") or [],
        # Real, finder-relevant fields (previously unused in the UI):
        "forWikis": tool.get("for_wikis") or [],
        "uiLanguages": tool.get("available_ui_languages") or [],
        "userDocs": first_url(tool.get("user_docs_url")),
        "devDocs": first_url(tool.get("developer_docs_url")),
        "feedback": first_url(tool.get("feedback_url")),
        "bugtracker": tool.get("bugtracker_url"),
        "translate": tool.get("translate_url"),
        "deprecated": bool(tool.get("deprecated")),
        "experimental": bool(tool.get("experimental")),
        "modified": tool.get("modified_date"),
        "weeklyViews": weekly_views(tool["name"]),
        "status": status_of(tool),
    }


def main():
    # --- catalog: merge alphabetical pages, dedupe by name ------------------
    catalog = {}
    for path in sorted(glob.glob(os.path.join(DATA, "tools_p*.json"))):
        for t in json.load(open(path, encoding="utf-8")).get("results", []):
            catalog[t["name"]] = compact(t)
    by_name = dict(catalog)

    def resolve(t):
        """Prefer the full catalog entry; fall back to a list-member object."""
        return by_name.get(t["name"], compact(t))

    catalog_list = list(catalog.values())

    # --- recently updated ---------------------------------------------------
    recent_raw = load("tools_recent.json").get("results", [])
    recent = [resolve(t) for t in recent_raw][:6]

    # --- featured tools (from a real featured list) -------------------------
    feat = load(f"list_{FEATURED_LIST_ID}.json")
    featured = [resolve(t) for t in (feat.get("tools") or [])][:8]

    # --- curated lists (all featured lists, with their real members) --------
    curated = []
    for lst in load("lists_raw.json").get("results", []):
        detail = load(f"list_{lst['id']}.json")
        members = [resolve(t) for t in (detail.get("tools") or [])]
        curated.append({
            "id": lst["id"],
            "title": lst.get("title") or "Untitled list",
            "description": lst.get("description") or "",
            "toolCount": len(members),
            "tools": members,
        })
    curated.sort(key=lambda c: c["toolCount"], reverse=True)

    # --- popular this week (top of the synthetic ranking) -------------------
    popular = sorted(catalog_list, key=lambda t: t["weeklyViews"], reverse=True)[:8]

    home = load("home_raw.json")
    payload = {
        "totalTools": home.get("total_tools"),
        "lastCrawlTime": home.get("last_crawl_time"),
        "catalog": catalog_list,
        "featured": featured,
        "recent": recent,
        "popular": popular,
        "curatedLists": curated,
    }

    out = os.path.normpath(os.path.join(HERE, "..", "public_html", "data.js"))
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("// Generated by build_data.py from a live Toolhub API snapshot.\n")
        fh.write("// Real catalog data; weeklyViews is synthesized deterministically.\n")
        fh.write("window.TOOLHUB_DATA = ")
        json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
        fh.write(";\n")

    print(f"catalog: {len(catalog_list)} tools")
    print(f"featured (list {FEATURED_LIST_ID}): {len(featured)}")
    print(f"recent: {len(recent)}  popular: {len(popular)}")
    print(f"curated lists: {len(curated)} (counts: {[c['toolCount'] for c in curated]})")
    print(f"wrote {out} ({os.path.getsize(out)//1024} KB)")


if __name__ == "__main__":
    main()
