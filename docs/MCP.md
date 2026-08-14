<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Using the Toolhub Evolved MCP server

Toolhub Evolved publishes catalog discovery over the
[Model Context Protocol](https://modelcontextprotocol.io/) so that an LLM
assistant can answer the question every new Wikimedia tool should start with:
**does this already exist, and what do similar tools build on?**

The endpoint is:

```
https://toolhub-evolved.toolforge.org/mcp
```

It is read-only, needs no account, no API key, and no OAuth grant. Everything it
returns is public catalog data — the same records the website shows.

This page is for people who want to _use_ it from a client. For deployment and
conformance testing, see [`deploy-toolforge.md`](deploy-toolforge.md); for the
implementation, see `proxy/backend/mcp_server.py`.

## 1. Connect a client

### Claude Code

```bash
claude mcp add --transport http toolhub-discovery https://toolhub-evolved.toolforge.org/mcp
```

The four tools then appear as `toolhub-discovery` tools, and the prior-art
review shows up as the `/mcp__toolhub-discovery__prior-art-review` slash
command.

### Claude Desktop / claude.ai

Add a **custom connector** in settings, paste the URL above, and leave
authentication empty. The server issues no tokens and keeps no sessions, so
nothing else needs configuring.

### Cursor, VS Code, and other `mcp.json` clients

```json
{
	"mcpServers": {
		"toolhub-discovery": {
			"type": "http",
			"url": "https://toolhub-evolved.toolforge.org/mcp"
		}
	}
}
```

Clients that only speak the older stdio transport need a bridge such as
`mcp-remote`; the endpoint itself is HTTP-only.

### Anything else

The endpoint is one `POST` that speaks JSON-RPC 2.0 and answers with plain JSON,
so `curl` is a legitimate client:

```bash
curl -sS -X POST https://toolhub-evolved.toolforge.org/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Supported methods: `initialize`, `server/discover`, `ping`, `tools/list`,
`tools/call`, `prompts/list`, `prompts/get`. Notifications are accepted and
answered with `202`.

### Check it worked

Ask the assistant to list the tools it has, or run the official inspector:

```bash
npx @modelcontextprotocol/inspector --cli --transport http \
  --method tools/list https://toolhub-evolved.toolforge.org/mcp
```

You should see `search_tools`, `facet_tools`, `list_facet_values`, and
`get_tool`.

## 2. The fastest path: the prior-art review

Most people want one thing from this server, and there is a prompt that does it
end to end. `prior-art-review` takes a `project_description` — an idea in a
sentence or three — and returns a review in three sections: **build / reuse /
differentiate**, **adjacent tools**, and a **recommended stack** ranked by how
many existing tools already use each library.

In Claude Code:

```
/mcp__toolhub-discovery__prior-art-review a bot that flags unsourced statements on Wikipedia
```

Other clients expose prompts differently — as a slash command, a "prompt"
picker, or via `prompts/get`. The methodology lives in the prompt rather than in
any one client's configuration, so every client gets the same review, and
corrections to it reach everyone at once.

If you would rather drive the search yourself, the four tools below are what the
prompt is made of.

## 3. The tools

All four are read-only. Every response is JSON, returned both as text and as
`structuredContent`.

### `search_tools(query, limit=10)`

Relevance-ranked search across the full ~4,500-tool catalog, served by Toolhub's
own Elasticsearch index.

Keep queries **short and distinctive — two or three content words**. Terms are
matched and scored independently, so padding a query with common words
(`wikipedia`, `tool`, `check`) pulls in unrelated results and pushes the good
ones down. Several narrow queries with different vocabulary beat one long
descriptive sentence. `limit` accepts 1–50 and defaults to 10.

Returns `{"tools": [...], "returned": n}`. `returned` is the size of this page,
deliberately not a catalog-wide total — a capped number labeled "total" reads as
"only n tools exist."

Each entry in `tools` has the same shape everywhere in this API:

| Field         | Meaning                                                     |
| ------------- | ----------------------------------------------------------- |
| `name`        | Exact Toolhub name — the key `get_tool` takes               |
| `title`       | Human-readable title                                        |
| `description` | Catalog description                                         |
| `url`         | Where the tool runs                                         |
| `tool_type`   | Declared type (`bot`, `web app`, `gadget`, `library`, …)    |
| `repository`  | Source repository, or `null` when none is declared          |
| `deprecated`  | Boolean — deprecated tools are still prior art, see §4      |
| `keywords`    | Declared keywords                                           |
| `matched`     | Which facets matched, for facet queries (empty from search) |

### `facet_tools(...)`

Find tools by signal rather than by words. Filters **AND** across parameters and
**OR** within one parameter's list, and `limit` accepts 1–50 (default 25).

**Detected from scanned source code** — accurate, but only covers tools with a
scanned repository:

- `dependency` — package name, optionally ecosystem-prefixed
  (`pywikibot` or `pypi:pywikibot`)
- `api` — one of `mediawiki-action-api`, `wikibase-api`,
  `wikidata-query-service`, `mediawiki-rest-api`, `toolforge`, `commons-upload`
- `technology` — a language detected in the source, e.g. `python`

**Declared in catalog metadata** — covers every tool, but only as well as
maintainers filled it in:

- `tool_type`, `keyword`, `wiki`, `license`
- `task` and `audience` — the only fields that say what a tool is _for_ rather
  than what it is built from, and filled in for a small minority of tools

```json
{ "dependency": ["pywikibot"], "api": ["wikidata-query-service"], "limit": 10 }
```

Returns `{"tools": [...], "total": n, "coverage": {...}}`, where `total` is the
true match count before `limit` and every tool's `matched` array names the
facets that matched, with a confidence between 0 and 1:

```json
{ "facet": "dependency", "value": "pypi:pywikibot", "confidence": 0.95 }
```

An unknown value is a filter that matches nothing rather than an error — asking
for `dependency: ["not-a-real-package"]` returns zero tools, not a complaint.

### `list_facet_values(type)`

The distinct values of one facet type, ranked by how many tools carry each —
the ecosystem's actual adoption ranking, and the answer to "what should I build
this in?" Call it before `facet_tools` to learn what values exist.

Types: `dependency`, `wikimedia_api`, `detected_technology` (detected);
`tool_type`, `keywords`, `wiki`, `license`, `tasks`, `audiences` (declared).
Note that these are the facet _type_ names, which differ slightly from the
`facet_tools` parameter names.

Returns `{"type": ..., "values": [{"value": ..., "toolCount": n}], "totalValues": n, "coverage": {...}}`.
`values` is the top 100 by adoption; `totalValues` tells you how much was left
off.

### `get_tool(name)`

One tool's full canonical Toolhub record, by **exact, case-sensitive** name —
the `name` field from a search or facet result, not the title. Returns the
cached canonical payload: the upstream record under `record`, plus
`sourceUrl`, `fetchedAt`, and staleness metadata. Unknown names return an error
rather than an empty record, so a typo can never read as "that tool doesn't
exist."

## 4. Reading the answers honestly

These are the judgment calls the tool descriptions can't make for you, and they
are the difference between a discovery pass that prevents duplicated work and
one that causes it.

- **One phrasing is not a search.** Vocabulary in Toolhub is inconsistent.
  Searching `bluesky` returns nothing, while `mastodon` returns fediverse tools
  and `cross-post` surfaces a bot that already posts wiki content to social
  platforms — the actual prior art for a Bluesky bot.
- **Absence is weak evidence.** Search matches text, not behavior, and plenty of
  real tools are unregistered or live only as on-wiki scripts. "I didn't find
  one" is honest; "there isn't one" is not.
- **Two facet families, one caveat.** `coverage` reports `scannedTools` against
  `totalTools`. That ratio applies to `dependency`, `api`, and `technology`
  only, so phrase gaps there as "no _scanned_ tool matches." The declared
  filters cover the whole catalog and don't carry the scan caveat — but `task`
  and `audience` are sparse enough that they should narrow a search, never
  settle it.
- **Deprecated tools are still prior art.** Flag the status, don't drop the
  tool: a dead tool that did the idea is evidence about the idea.
- **Adoption is not quality.** "14 of 20 scanned tools use X" means X fits the
  ecosystem, not that X is the best choice for you.
- **If search fails, say so.** `search_tools` has no local fallback by design —
  a weak substitute answer is worse than none, because you act on it and build
  the tool that already exists. When it reports being unavailable, `facet_tools`
  and `get_tool` still work, but the review is half-done and should be labeled
  that way.

## 5. Optional: the Claude skill

[`skills/toolhub-discovery/`](../skills/toolhub-discovery/) adds the one thing a
prompt can't do — it fires on its own when you start describing a tool idea,
instead of waiting for you to remember to check. Copy the directory into
`~/.claude/skills/` and configure the MCP server first; the skill performs no
HTTP of its own.

## 6. Limits and etiquette

- **Rate limit:** 60 requests per rolling minute per client IP. Over it, the
  endpoint answers `429` with `rate limited, retry later`.
- **Read-only and anonymous.** No writes, no auth, no cookies, no sessions —
  nothing you send is associated with a Toolhub account.
- **Freshness:** catalog data follows the 15-minute sync cadence, and clients
  are told tool and prompt listings stay valid for 7 minutes.
- **One request per POST.** JSON-RPC batches are rejected with `400`.
- **Please don't bypass it.** The server carries the User-Agent, caching, and
  rate-limit obligations for upstream Wikimedia traffic. A client that scrapes
  Toolhub directly instead generates uncredited load on Wikimedia
  infrastructure.

## 7. Troubleshooting

| Symptom                                   | Cause and fix                                                                                               |
| ----------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `405 Method Not Allowed`                  | The endpoint is `POST` only; a browser visit to the URL will always fail.                                   |
| `403 origin not allowed`                  | A browser-based client sent an `Origin` header we don't allow. Programmatic clients send none and are fine. |
| `429 rate limited, retry later`           | Over 60 requests/minute from your IP. Wait out the minute; batch fewer speculative facet calls.             |
| `Toolhub search is unavailable right now` | Upstream Toolhub search is down. Retry shortly; facets and `get_tool` still work meanwhile.                 |
| `no canonical tool named …`               | Names are exact and case-sensitive. Take the `name` from a `search_tools` result, not the displayed title.  |
| `supply at least one filter`              | `facet_tools` was called with no filters. Add at least one; `list_facet_values` shows what values exist.    |
| Empty facet results                       | Check `coverage` — for detected facets this may mean "not scanned," not "doesn't exist." Confirm by search. |
| Tools never appear in the client          | Confirm the transport is HTTP (not stdio) and that `tools/list` works via `curl` or the inspector.          |
