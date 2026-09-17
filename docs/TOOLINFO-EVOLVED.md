# Evolved toolinfo.json v1

Toolhub Evolved keeps the canonical Toolhub toolinfo.json contract intact
and adds a versioned envelope for artifacts that the canonical catalog does
not understand yet. The current envelope is:

    {
      "_schema": "/toolinfo/evolved/1.0.0",
      "type": "evolved-catalog",
      "source": {},
      "artifacts": []
    }

The normative JSON Schema is
[schemas/toolinfo-evolved-1.0.0.schema.json](../schemas/toolinfo-evolved-1.0.0.schema.json).
The examples used by the parser tests live under
[tests/proxy/fixtures/](../tests/proxy/fixtures/).

## Why the envelope is separate

The canonical Toolhub catalog describes tools. A skill is an Evolved artifact,
not a new canonical tool_type that upstream Toolhub has to understand.
Evolved reads the envelope when present and keeps it out of the canonical
Toolhub tool serializers. A repository can therefore publish ordinary tools
and several Agent Skills in the same observation without losing either type.

The artifacts array is the unit of identity, review, refresh, and publication.
The repository itself is represented once by source; it must not be used as
the identity of every skill.

## Fields

### Envelope

| Field        | Required | Meaning                                                                                                                |
| ------------ | -------- | ---------------------------------------------------------------------------------------------------------------------- |
| \_schema     | yes      | Exactly /toolinfo/evolved/1.0.0. A different major contract is not parsed as this contract.                            |
| type         | yes      | Exactly evolved-catalog.                                                                                               |
| source       | yes      | Repository and immutable observation context shared by artifacts.                                                      |
| artifacts    | yes      | Array of independently addressable tool or skill artifacts. It may contain zero entries for an empty complete catalog. |
| refresh      | no       | Run evidence. partial and failed runs must not remove a sibling's last-good snapshot.                                  |
| generated_at | no       | RFC 3339 timestamp for the envelope.                                                                                   |
| generator    | no       | Name/version of the producer. Unknown producer metadata is retained.                                                   |

### source

source.id is the stable repository identity, for example
github:example/skill-repository. source.repository is its canonical
repository URL. ref, commit, and base_path describe the observed revision and
scan root. A per-artifact source may refine the shared value, but does not
replace the artifact identity.

### artifacts

Every artifact requires:

| Field       | Meaning                                                                                                                                                                 |
| ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| id          | Stable identity within the repository, for example github:org/repo#skills/review. Two skills with the same display name remain distinct when their IDs or roots differ. |
| tool_type   | skill for an Agent Skill; other strings remain available for mixed tool/skill records.                                                                                  |
| name        | Stable human-readable artifact name.                                                                                                                                    |
| description | What the artifact does and when it is useful.                                                                                                                           |
| projects    | Optional declared Wikimedia project targets; the data layer preserves this field.                                                                                       |
| source      | Optional artifact-specific source override.                                                                                                                             |
| evolved     | Optional Evolved visibility, review, provenance, and MCP metadata.                                                                                                      |

For tool_type: skill, skill is required. Ordinary tool artifacts can carry
their existing Toolhub fields alongside the envelope and are ignored by the
Skills transport.

### skill

| Field       | Meaning                                                                                                                                  |
| ----------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| root        | Repository-relative skill directory. Nested roots such as skills/reports/weekly are valid.                                               |
| entrypoint  | Exactly SKILL.md in v1.                                                                                                                  |
| frontmatter | The Agent Skills frontmatter; name and description are required. Unknown frontmatter keys are retained.                                  |
| resources   | Either dynamic or a static manifest array. Static manifests must include the root SKILL.md, a byte size, and a lowercase SHA-256 digest. |

Resource bytes are not part of the public toolinfo.json contract. They are
stored in the Evolved snapshot/cache and are served only when already
available locally. The parser may accept inline bytes in an internal cache
record for tests and local staging, but producers must not rely on that
extension in the published envelope.

### evolved

visibility is one of private, unlisted, or public. review_status is one of
draft, pending, approved, rejected, stale, or removed. review and provenance
hold the evidence needed by the future review and snapshot lifecycle.
mcp.resource_uri may pin the externally addressable skill root URI. These
fields are Evolved metadata and do not alter the canonical Toolhub record.

## Compatibility and refresh semantics

The normative v1 shape is artifacts. The running catalog reader also accepts
the earlier internal spellings skills, skill, and a single skill record so
the deployed MCP endpoint remains backward compatible. New producers should
emit only the versioned envelope.

The parser isolates artifacts: one malformed skill is skipped without
discarding valid siblings from the same repository. A refresh.status of
partial or failed is evidence about the run, not proof that omitted siblings
were removed. Snapshot storage must retain each sibling's last-good version
until a complete observation explicitly changes its state. Unknown major
schema versions are rejected rather than guessed.

## Repository-scan discovery

Repository analysis discovers every repository-relative `SKILL.md` in the
acquired tree in sorted path order. Each entrypoint becomes one artifact whose
stable ID is `<source.id>#<skill-root>`. A repository may therefore contain
multiple skills, including a normal skill and a nested skill root. Resources
belonging to a nested root are excluded from its parent manifest and are
reported by the nested artifact instead.

The discovery result is stored alongside the existing source-analysis report:

| Report field               | Meaning                                                                                        |
| -------------------------- | ---------------------------------------------------------------------------------------------- |
| `evolvedSkills`            | The versioned Evolved catalog envelope, including source, refresh, artifacts, and provenance.  |
| `evolvedSkillsDiscovery`   | Run counters: `discovered`, `failed`, and `observedFiles`.                                     |
| `refresh.failed_artifacts` | Per-entrypoint errors with the candidate path, stable ID, bounded message, and retryable flag. |

The bounded discovery parser accepts the Agent Skills frontmatter needed by
the data layer (`name`, `description`, and declared fields such as `projects`)
and retains unknown keys. Invalid UTF-8, missing frontmatter, malformed
frontmatter, and unreadable entrypoints fail only that candidate. A run is
`complete` when all candidates succeed, `partial` when at least one succeeds
and one fails, and `failed` when every candidate fails. An empty repository
scan is a complete catalog with zero artifacts.

The scanner records immutable source evidence (`source.id`, repository URL,
and commit) plus a run ID on each artifact. Resource contents remain outside
the public envelope; the resource manifest records repository-relative paths,
byte sizes, and SHA-256 digests so a later snapshot/cache stage can serve the
skill without changing discovery semantics.

Examples:

- [toolinfo-evolved-multi-skill.json](../tests/proxy/fixtures/toolinfo-evolved-multi-skill.json):
  three skills in one repository, including a nested skill root.
- [toolinfo-evolved-mixed.json](../tests/proxy/fixtures/toolinfo-evolved-mixed.json):
  an ordinary tool and a skill in one envelope.
- [toolinfo-evolved-invalid.json](../tests/proxy/fixtures/toolinfo-evolved-invalid.json):
  an invalid skill payload.
- [toolinfo-evolved-partial-refresh.json](../tests/proxy/fixtures/toolinfo-evolved-partial-refresh.json):
  one valid sibling and one failed sibling in a partial run.
