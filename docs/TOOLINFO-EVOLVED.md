# Toolhub Evolved record contract

## Goal and compatibility boundary

Toolhub Evolved keeps the Wikimedia Toolhub 1.2.2 Toolinfo schema as its canonical base. Evolved adds typed metadata under the top-level `evolved` property. It does not replace the Toolinfo record, alter canonical required fields, or add values to canonical `tool_type`.

A canonical record remains a Toolinfo record. The required canonical fields are `name`, `title`, `description`, and `url`; all other canonical constraints, including the `tool_type` enum, remain authoritative. A canonical consumer must continue to validate and project a record without depending on `evolved`.

The vendored canonical schema is `schemas/toolinfo-1.2.2.schema.json`. Its upstream source is [Wikimedia Toolhub 1.2.2](https://raw.githubusercontent.com/wikimedia/wikimedia-toolhub/main/jsonschema/toolinfo/1.2.2.json), whose schema identifier is `/toolinfo/1.2.2`. Evolved's additive schema is `schemas/toolinfo-evolved-extension-1.0.0.schema.json`; it composes with the canonical schema instead of redefining canonical fields. Runtime validation uses the vendored canonical copy and does not fetch schemas over the network.

The earlier root-level Evolved envelope described by `schemas/toolinfo-evolved-1.0.0.schema.json` is a transitional input format only. It is not the target record shape. Readers may keep compatibility handling while data is migrated; new records use the canonical Toolinfo shape with an optional `evolved` namespace.

## Evolved namespace

An enriched record has this high-level form:

```json
{
  "_schema": "/toolinfo/1.2.2",
  "name": "example-skill",
  "title": "Example Skill",
  "description": "A short description.",
  "url": "https://example.org/skills/example",
  "evolved": {
    "schema_version": "1.0.0",
    "artifact_type": "skill",
    "artifact_id": "skill:example:example-skill",
    "source": {
      "id": "github:example/skills",
      "repository": "https://github.com/example/skills",
      "commit": "<immutable revision>"
    },
    "revision": "<immutable revision>",
    "content_sha256": "sha256:<64 lowercase hexadecimal characters>",
    "provenance": {
      "run_id": "<discovery run identifier>"
    },
    "visibility": "private",
    "review_status": "pending",
    "skill": {
      "root": "skills/example-skill",
      "entrypoint": "SKILL.md",
      "resources": []
    }
  }
}
```

The example uses placeholders and is explanatory, not a validator fixture. A discovered artifact defaults to private visibility and pending review. `revision` and `content_sha256` bind the record to the exact source snapshot; analysis metadata, when present, must identify the same revision and content hash. Resource hashes are computed over the raw resource bytes, including binary content when the source reader provides those bytes.

`artifact_type` is the discriminator for Evolved payloads. The initial types are:

- `skill`: manifest entrypoint, parsed frontmatter, and a resource inventory.
- `mcp_server`: a descriptive server registration, with transport, endpoint or package reference, protocol version, capabilities, and authentication requirements.
- `user_script`: a typed occurrence of a wiki user script. Consolidated identity and cross-wiki views must preserve each occurrence, owner, source page, license, and revision rather than merging on names alone.

A record has at most one matching typed payload. For example, `artifact_type: "mcp_server"` requires `evolved.mcp_server` and forbids `evolved.skill` and `evolved.user_script`. No artifact type is encoded by extending canonical `tool_type`.

## MCP descriptor safety

An MCP descriptor describes a server; it is not an instruction to execute it. Validation and catalog ingestion must not launch a process, make a network probe, or infer trust from a successful connection. The descriptor has no credential field. It records only whether authentication is required and the declared methods or permissions; unknown fields, including token/password fields, are rejected. URI-valued metadata and URI-shaped package references reject user-info credentials. Never put credential values in a package reference or endpoint.

Transport-specific requirements are validated: `stdio` uses a package reference, while `streamable-http` and `sse` use an endpoint. Registration, review, catalog publication, and later MCP delivery remain separate operations with their own authorization and safety checks.

## Validation and consumers

`proxy/backend/toolinfo_extension.py` validates the canonical schema and, when present, the Evolved extension schema. It also checks cross-field bindings that JSON Schema alone cannot express, including the artifact discriminator/payload match and analysis-to-source revision/hash match. Canonical-only records remain valid. An enriched record may be projected to its unchanged canonical fields without carrying Evolved-specific requirements into canonical readers.

The Skill discovery path now emits canonical Toolinfo records with `evolved.artifact_type="skill"`; the Skill catalog reads the typed payload and retains a transitional reader for the former envelope. MCP descriptors can be represented and validated by the same contract, but this does not by itself register or publish them.

## Current implementation boundary

This work establishes the additive schema and a local Skill discovery/validation slice. It is not yet the complete Skills/MCP registration lifecycle:

1. Discovery currently places canonical Skill records in the repository analysis report. A dedicated immutable artifact snapshot/content store and a publishable catalog path are still required.
2. MCP records have a typed schema and validator, but the MCP registry ingestion, review, public catalogue, and serving path are not implemented by this slice. No MCP server is executed or probed.
3. Repository source acquisition remains bounded and source-oriented. The Skill parser preserves raw bytes when they are supplied, but the current repository tree reader filters to supported source paths and UTF-8 text. Binary assets and a complete resource manifest are therefore not yet proven end to end.
4. The root-level legacy envelope is migration input only. All producers and consumers still need to be checked for canonical enriched records before removing compatibility code.
5. UserScript family consolidation and cross-wiki views remain governed by the existing #196 work; the common identity contract belongs to #215. Continue using the existing issues rather than creating parallel tickets.

Related implementation work is tracked by the existing #214, #215, #196 and their downstream discovery, snapshot, analysis, catalogue, and MCP delivery issues. Do not treat schema validation or a discovery report as proof of persistence or publication.

## Verification

The focused proxy checks for the additive schema, Skill catalog, Skill discovery, and repository scan can be run with:

```sh
uv run --no-project --with-requirements proxy/requirements.txt --with pytest --python 3.11 env PYTHONPATH=proxy pytest \
  tests/proxy/test_toolinfo_evolved.py \
  tests/proxy/test_skill_catalog.py \
  tests/proxy/test_skill_discovery.py \
  tests/proxy/test_repository_scan.py -q
```
