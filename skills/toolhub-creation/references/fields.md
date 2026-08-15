# Toolinfo 1.2.2 field guide

<!-- cspell:ignore openhub -->

The authoritative schema is
`https://gerrit.wikimedia.org/r/plugins/gitiles/wikimedia/toolhub/+/refs/heads/main/jsonschema/toolinfo/current.yaml`.
This compact guide is for authoring; the bundled validator remains the local
check.

## Required fields

| Field         | Shape  | Guidance                                                |
| ------------- | ------ | ------------------------------------------------------- |
| `_schema`     | string | Use `/toolinfo/1.2.2`.                                  |
| `_language`   | string | Language of this record; defaults to `en`.              |
| `name`        | string | Stable identity; Toolforge uses `toolforge-$PROJECT`.   |
| `title`       | string | Human-readable title, preferably 25 characters or less. |
| `description` | string | What the tool does, for whom, and when it is useful.    |
| `url`         | URL    | Tool, installation, or usage-instructions URL.          |

The JSON Schema requires `name`, `title`, `description`, and `url`; `_schema`
and `_language` are included here because repository records should be explicit
and reproducible.

## People and organizations

- `author`: string or array of objects. Prefer objects with required `name` and
  verified optional `wiki_username`, `developer_username`, public `email`, and
  public `url`. These are primary developers, not every maintainer.
- `sponsor`: string or array of organization names.
- `bot_username`: Wikimedia username of the bot account, without `User:`.

## Classification and compatibility

- `tool_type`: one of `web app`, `desktop app`, `bot`, `gadget`, `user script`,
  `command line tool`, `coding framework`, `lua module`, `template`, or `other`.
- `for_wikis`: hostname or array. Supported examples: `en.wikipedia.org`,
  `*.wikisource.org`, `*`.
- `available_ui_languages`: language code, array, or `*`.
- `technology_used`: string or array of languages, frameworks, or platforms.
- `license`: SPDX identifier.
- `keywords`: legacy comma-delimited string accepted by 1.2.2 but deprecated.

## Links

Simple URL fields: `repository`, `api_url`, `translate_url`, `bugtracker_url`,
`replaced_by`, and `icon`. The icon must be a Commons description URL beginning
with `https://commons.wikimedia.org/wiki/File:`.

`developer_docs_url`, `user_docs_url`, `feedback_url`, and
`privacy_policy_url` accept either one URL or an array of objects:

```json
[
	{ "language": "en", "url": "https://example.org/docs" },
	{ "language": "fr", "url": "https://example.org/fr/docs" }
]
```

`url_alternates` is an array using that same `{language, url}` shape.

Other optional fields are `subtitle`, `openhub_id`, `deprecated`,
`experimental`, and `replaced_by`. Use `replaced_by` only with `deprecated`.

## Fields that do not belong in core toolinfo

Toolhub community annotations include `audiences`, `tasks`, `content_types`,
`subject_domains`, and `wikidata_qid`. Manage those through Toolhub's annotation
API. Do not mix them into a repository's core metadata file.
