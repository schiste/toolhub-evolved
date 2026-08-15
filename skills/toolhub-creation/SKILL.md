---
name: toolhub-creation
description: Create, migrate, review, or improve Wikimedia Toolhub core metadata in a correctly named toolinfo.json. Use for Wikimedia tools, bots, gadgets, templates, Lua modules, user scripts, and Toolforge projects when an agent needs to add structured authors, validate schema 1.2.2, fix the Toolforge identifier, or prepare a repository-authored record for Toolhub registration.
---

# Toolhub Creation

Create factual, reviewable Toolhub metadata at the source repository. Keep core
metadata, identity claims, and community annotations in their correct systems.

## Workflow

1. Determine provenance before editing.
    - If the repository already contains `toolinfo.json`, update that file.
    - If Toolhub receives the record from Toolsadmin, create a repository-owned
      file and tell the user that its raw URL must be registered and the old
      source coordinated. Do not pretend to edit Toolsadmin from the repository.
    - Never put annotation-only fields such as `audiences`, `tasks`,
      `content_types`, `subject_domains`, or `wikidata_qid` in the core file.
2. Read the repository's README, license, manifests, deployment configuration,
   documentation links, and existing metadata. Do not invent missing facts.
3. Choose the stable identifier.
    - For Toolforge, use `toolforge-$PROJECT`, where `$PROJECT` is the exact
      Toolforge project name.
    - Otherwise preserve an existing Toolhub name. Ask before changing it: name
      is the crawler deduplication identity, so a rename creates another record.
4. Describe authors as structured objects. Add `wiki_username` and
   `developer_username` only when evidence establishes those exact accounts.
   A Toolforge maintainer is not automatically a primary developer; Toolinfo
   has no maintainer field. Never convert maintainership into authorship merely
   to improve verification statistics.
5. Create the exact filename `toolinfo.json`. Use schema `/toolinfo/1.2.2`, set
   `_language` to the record language, and include the four required fields:
   `name`, `title`, `description`, and `url`.
6. Read [references/fields.md](references/fields.md) when optional fields or
   multilingual URL syntax are relevant.
7. Validate before reporting completion:

    ```bash
    python3 scripts/toolinfo.py check path/to/toolinfo.json
    python3 scripts/toolinfo.py check path/to/toolinfo.json --toolforge-project PROJECT
    ```

8. Report the file path, validated identifier, facts intentionally left blank,
   and the raw HTTPS URL that should be registered. Do not register, commit,
   push, or publish unless the user authorized that action.

## Create a starting file

Use the helper when no file exists, then enrich it from repository evidence:

```bash
python3 scripts/toolinfo.py create \
  --toolforge-project PROJECT \
  --title "Human title" \
  --description "What it does, who it helps, and when to use it." \
  --url "https://PROJECT.toolforge.org/" \
  --author-name "Public name" \
  --wiki-username "Wiki username" \
  --developer-username "Developer username" \
  --output toolinfo.json
```

The helper refuses to overwrite an existing file. Prefer editing a copied
[assets/toolinfo.example.json](assets/toolinfo.example.json) only when the
command-line inputs are inconvenient.

## Quality boundary

- Prefer omission to guesses. Optional does not mean unimportant.
- Use an SPDX identifier for `license` and the schema's exact controlled value
  for `tool_type`.
- Use Wikimedia hostnames or supported wildcards in `for_wikis`; use `*` only
  when the tool truly works on every wiki.
- Keep private email addresses out of public metadata.
- A repository-authored record can evolve through commits and pull requests.
  A Toolsadmin-generated record cannot; migrate its source first. Toolhub
  annotations always remain API-owned regardless of core provenance.
