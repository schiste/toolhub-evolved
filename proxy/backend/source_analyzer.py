# SPDX-License-Identifier: GPL-3.0-or-later
"""Static source-code signals for Toolhub metadata suggestions.

The analyzer is intentionally deterministic: every suggestion is backed by
bounded, redacted evidence from the submitted source files. It does not execute
tool code, clone repositories, or store raw source.
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from backend import source_endpoints, wiki_sources
from backend.source_analysis_assessments import (
    _assessment_summary,
    _assessments,
    _health_core,
    _health_summary,
    _maintainer_activity_context,
)
from backend.source_analysis_common import (
    A11Y_SIGNAL_RE,
    ACTION_OBJECT_RE,
    ACTION_QUERY_RE,
    ACTION_RIGHTS,
    ACTIVE_REPOSITORY_DAYS,
    ANALYSIS_TOOLING_RE,
    API_RULES,
    AUTH_RULES,
    BROWSER_PERMISSION_RULES,
    CI_FILE_KINDS,
    CONFIDENCE_CAP,
    CONFIDENCE_MAX_CORROBORATING_FILES,
    CONFIDENCE_REPEAT_BOOST,
    CONFIG_SOURCE_EXTENSIONS,
    CONTEXT_RESERVE_BUDGET_DIVISOR,
    CONTEXT_RESERVE_QUOTAS,
    CONTEXT_RESERVE_SLOTS,
    CREDENTIAL_RE,
    CSS_REMOTE_REF_RE,
    CSS_SUFFIX,
    DECLARED_DEPENDENCY_SOURCE_CLASSES,
    DECLARED_TECHNOLOGY_CONFIDENCE,
    DOCUMENTATION_FILE_KINDS,
    ENDPOINT_CALLED_CONFIDENCE,
    ENDPOINT_CONFIDENCE,
    ENDPOINT_TRUSTED_SOURCE_WEIGHT,
    EVOLVED_METADATA_MIN_CONFIDENCE,
    EXACT_VERSION_RE,
    EXTENSION_ALL_HOSTS,
    EXTENSION_HOST_MATCH_RE,
    EXTENSION_MANIFEST_RE,
    FRONTEND_SOURCE_EXTENSIONS,
    GADGET_DECLARED_RIGHT_CATEGORY,
    GADGET_DECLARED_RIGHT_CONFIDENCE,
    GADGET_DEFAULT_OPTION,
    GADGET_DEFINITION_PAGE,
    GADGET_DEFINITION_PAGE_TITLE,
    GADGET_DEPENDENCIES_OPTION,
    GADGET_HIDDEN_OPTION,
    GADGET_MODULE_CATEGORY,
    GADGET_MODULE_CONFIDENCE,
    GADGET_MODULE_ECOSYSTEM,
    GADGET_RIGHT_VOCABULARY,
    GADGET_RIGHTS_OPTION,
    GADGET_SCOPE_OPTIONS,
    GEM_LOCK_RE,
    GEM_LOCK_VERSION_RE,
    GEM_RE,
    GEM_VERSION_RE,
    GO_DIRECTIVE_RE,
    GO_REQUIRE_RE,
    GO_VERSION_RE,
    HEALTH_SIGNAL_RE,
    HIGH_PROVENANCE_WEIGHT,
    IGNORED_PROJECT_DB_NAMES,
    IGNORED_SOURCE_DIRS,
    IGNORED_SOURCE_FILES,
    JS_IMPORT_RE,
    JS_SCOPED_PACKAGE_PARTS,
    JS_SOURCE_SUFFIXES,
    KNOWN_OAUTH_SCOPES,
    LANGUAGE_SUBDOMAIN_RE,
    LOCAL_IMPORT_ROOTS,
    LOCKFILE_KINDS,
    MANIFEST_FILE_KINDS,
    MAX_ASSESSMENT_SIGNALS,
    MAX_CONTEXT_LIST_ITEMS,
    MAX_DEPENDENCY_NAME_CHARS,
    MAX_EVIDENCE_PER_FINDING,
    MAX_EXCERPT_CHARS,
    MAX_FILE_BYTES,
    MAX_FILES,
    MAX_FINDINGS_PER_BUCKET,
    MAX_LINE_CHARS,
    MAX_PATH_CHARS,
    MAX_SOURCE_CLASS_ITEMS,
    MAX_TOTAL_BYTES,
    MAX_VERSION_CHARS,
    MAX_VERSION_SPECS_PER_FINDING,
    MAX_WIKI_FILE_BYTES,
    NON_VERSION_SPEC_PREFIXES,
    NON_WIKI_SUBDOMAINS,
    PHP_USE_RE,
    PROJECT_DB_RE,
    PROJECT_DOMAIN_RE,
    PROJECT_FAMILY_DB_SUFFIX,
    PROJECT_SUGGESTION_MIN_CONFIDENCE,
    PUBLICATION_TRUSTED_SOURCE_WEIGHT,
    PY_IMPORT_RE,
    QUIET_REPOSITORY_DAYS,
    READ_ACTIONS,
    REPOSITORY_CONTEXT_DECLARED_KEYS,
    REPOSITORY_CONTEXT_LIFECYCLE_KEYS,
    REPOSITORY_CONTEXT_MAINTAINER_KEYS,
    REPOSITORY_CONTEXT_REPOSITORY_KEYS,
    REQ_NAME_RE,
    REQUEST_SIGNAL_RE,
    RUBY_REQUIRE_RE,
    RUNTIME_FILE_KINDS,
    RUNTIME_SOURCE_EXTENSIONS,
    RUNTIME_TECHNOLOGY,
    SCOPE_LINE_RE,
    SCORING_MIN_CONFIDENCE,
    SOURCE_CLASS_WEIGHTS,
    SOURCE_EXTENSIONS,
    STALE_REPOSITORY_DAYS,
    TECH_BY_EXTENSION,
    TECH_RULE_SUFFIXES,
    TECH_RULES,
    TECHNOLOGY_PACKAGES,
    TECHNOLOGY_SUGGESTION_MIN_CONFIDENCE,
    UNVERSIONED_SPECS,
    USER_SCRIPT_DIRECTIVE_LABELS,
    USER_SCRIPT_DIRECTIVE_RE,
    USER_SCRIPT_SUFFIX,
    WEB_EXTENSION_PERMISSION_RE,
    WEB_EXTENSION_PERMISSIONS,
    WIKI_KIND_TOOL_TYPE,
    WIKIMEDIA_ORG_WIKIS,
    YARN_LOCK_RE,
    YARN_VERSION_RE,
    _clean_context_string,
    _has_category,
    _has_write_access,
    _int_context_value,
    _parse_iso_datetime,
    _publishable_rows,
)

if TYPE_CHECKING:
    from collections.abc import Callable


class SourceAnalysisError(ValueError):
    """Raised when submitted source-analysis input is unsafe or malformed."""


@dataclass(frozen=True)
class SourceFile:
    """One bounded source file supplied to the analyzer."""

    path: str
    content: str


@dataclass
class Finding:
    """Accumulated finding before serialization."""

    value: str
    label: str
    kind: str
    category: str
    #: The best single sighting, before corroboration. Read `confidence`.
    base_confidence: float = 0.0
    reasons: set[str] = field(default_factory=set)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    source_classes: set[str] = field(default_factory=set)
    max_source_weight: float = 0.0
    #: The best source weight seen for each distinct file carrying this finding.
    #: Corroboration is bounded by this, not by the number of sightings:
    #: _finding_rank() already counts distinct paths for the same reason.
    path_weights: dict[str, float] = field(default_factory=dict)
    #: Every constraint seen for this finding, as the manifest wrote it.
    version_specs: set[str] = field(default_factory=set)
    #: The subset of those that pin one release, normalized to the bare number.
    versions: set[str] = field(default_factory=set)

    def add(self, confidence: float, reason: str, evidence: dict[str, Any]) -> None:
        """Merge repeated evidence into one finding.

        Records the sighting and nothing more. Confidence is derived from
        everything recorded, by the `confidence` property, rather than being
        accumulated here as files arrive -- see that property for why.
        """
        source_class = str(evidence.get("sourceClass") or "unknown")
        source_weight = float(evidence.get("sourceWeight") or SOURCE_CLASS_WEIGHTS["unknown"])
        path = str(evidence.get("path") or "")
        self.base_confidence = max(self.base_confidence, min(CONFIDENCE_CAP, max(0.0, confidence) * source_weight))
        self.path_weights[path] = max(self.path_weights.get(path, 0.0), source_weight)
        self.reasons.add(reason)
        self.evidence.append(evidence)
        self.source_classes.add(source_class)
        self.max_source_weight = max(self.max_source_weight, source_weight)

    @property
    def confidence(self) -> float:
        """How much this finding is believed, as a function of all its evidence.

        Corroboration is counted per distinct file, and only for the few best.
        The boost used to apply on every sighting, unbounded until the cap, so
        ten hits in high-provenance code added about 0.29. That is the wrong
        shape: repetition is only evidence when the sightings are independent
        observations, and a rule misfiring on a common idiom produces the same
        error many times rather than many findings. Confidence therefore rose
        fastest exactly where the analyzer was most wrong -- `clean_wiki` reached
        0.82 from a 0.76 base that way -- and the publication thresholds could
        not filter what the boost had already pushed past them.

        Counting per file bounded that, but accumulating the boost inside add()
        left the total dependent on the order the files were read: with credit
        limited to a few files, whichever few arrived first decided how much
        credit there was, and their weights differ. The same repository walked
        in a different order scored differently, which is not something a
        deterministic analyzer is allowed to do. So the boost is computed here,
        from the whole set: the best-attested file is the claim, and the next
        few by weight are what agree with it.
        """
        weights = sorted(self.path_weights.values(), reverse=True)
        corroborating = [
            weight for weight in weights[1 : 1 + CONFIDENCE_MAX_CORROBORATING_FILES] if weight >= HIGH_PROVENANCE_WEIGHT
        ]
        boost = CONFIDENCE_REPEAT_BOOST * sum(corroborating)
        return min(CONFIDENCE_CAP, self.base_confidence + boost)

    def note_version(self, spec: str | None) -> None:
        """Record a declared version, keeping exact pins apart from ranges."""
        if not spec:
            return
        self.version_specs.add(spec)
        exact = _exact_version(spec)
        if exact:
            self.versions.add(exact)

    def payload(self) -> dict[str, Any]:
        """Serialize the finding for JSON responses."""
        payload = {
            "value": self.value,
            "label": self.label,
            "kind": self.kind,
            "category": self.category,
            "confidence": round(self.confidence, 2),
            "maxSourceWeight": round(self.max_source_weight, 2),
            # How many distinct files carry this finding. The evidence list is
            # capped at MAX_EVIDENCE_PER_FINDING, so it cannot be counted from
            # the payload, and _is_corroborated() needs the true figure.
            "fileCount": len(self.path_weights),
            "reasons": sorted(self.reasons),
            "sourceClasses": sorted(self.source_classes),
            "evidence": self.evidence[:MAX_EVIDENCE_PER_FINDING],
        }
        # One exact version is a fact. Two are two manifests disagreeing, and
        # picking either would be a guess dressed as a measurement, so the
        # specs carry it instead and the caller sees there is no single answer.
        if len(self.versions) == 1:
            payload["version"] = next(iter(self.versions))
        if self.version_specs:
            payload["versionSpecs"] = sorted(self.version_specs)[:MAX_VERSION_SPECS_PER_FINDING]
        return payload


def _suffix(path: str) -> str:
    match = re.search(r"(\.[A-Za-z0-9]+)$", path)
    return match.group(1).lower() if match else ""


def _clean_path(value: object) -> str:
    path = str(value or "").replace("\\", "/").strip().lstrip("/")
    path = re.sub(r"/+", "/", path)
    return path[:MAX_PATH_CHARS] if path else "source.txt"


def _is_source_path(path: str) -> bool:
    parts = {part.lower() for part in path.replace("\\", "/").split("/")}
    if parts & IGNORED_SOURCE_DIRS:
        return False
    suffix = _suffix(path)
    name = path.rsplit("/", 1)[-1].lower()
    if name in IGNORED_SOURCE_FILES:
        return False
    return suffix in SOURCE_EXTENSIONS or name in {
        "composer.json",
        "dockerfile",
        "gemfile",
        "go.mod",
        "makefile",
        "package.json",
        "pipfile",
        "requirements.txt",
    } | set(LOCKFILE_KINDS) | set(DOCUMENTATION_FILE_KINDS) | set(CI_FILE_KINDS) | set(RUNTIME_FILE_KINDS)


def is_supported_source_path(path: str) -> bool:
    """Return whether a source path should be accepted for analysis."""
    return _is_source_path(path)


def _line_excerpt(line: str) -> str:
    compact = re.sub(r"\s+", " ", line.strip())[:MAX_EXCERPT_CHARS]
    if CREDENTIAL_RE.search(compact):
        return "[redacted credential-like assignment]"
    return compact


def _manifest_kind(path: str) -> str | None:
    name = path.rsplit("/", 1)[-1].lower()
    if name.startswith("requirements") and name.endswith(".txt"):
        return "pypi"
    return MANIFEST_FILE_KINDS.get(name)


def _is_fixture_path(path: str) -> bool:
    parts = {part.lower() for part in path.replace("\\", "/").split("/")}
    name = path.rsplit("/", 1)[-1].lower()
    return bool(parts & {"__fixtures__", "fixtures", "fixture"}) or "fixture" in name


def _is_example_path(path: str) -> bool:
    parts = {part.lower() for part in path.replace("\\", "/").split("/")}
    name = path.rsplit("/", 1)[-1].lower()
    return bool(parts & {"demo", "demos", "example", "examples", "sample", "samples"}) or re.search(
        r"(?:^|[._-])(?:demo|example|sample)(?:[._-]|$)",
        name,
    )


def _source_class_from_named_file(path: str, name: str) -> str | None:
    if _manifest_kind(path):
        return "manifest"
    if name == GADGET_DEFINITION_PAGE:
        # The gadget registry is a manifest in the sense that matters here: it
        # is the wiki's own declaration of what a gadget consists of and who it
        # is served to, so one sighting on it is a statement and needs no
        # corroboration. Matched by name rather than added to
        # MANIFEST_FILE_KINDS, whose values select a dependency parser -- this
        # page declares no packages and must reach none of them.
        return "manifest"
    if name in LOCKFILE_KINDS:
        return "lockfile"
    if _ci_kind(path):
        return "ci"
    return None


def _source_class_from_low_provenance_path(path: str) -> str | None:
    if _is_fixture_path(path):
        return "fixture"
    if _test_kind(path):
        return "test"
    if path.startswith("docs/") or _documentation_kind(path):
        return "docs"
    if _is_example_path(path):
        return "example"
    if ANALYSIS_TOOLING_RE.search(path):
        return "analysis-tooling"
    return None


def _source_class_from_runtime_shape(path: str, name: str, suffix: str) -> str | None:
    if _runtime_kind(path):
        return "runtime"
    if path.startswith("public_html/") or suffix in FRONTEND_SOURCE_EXTENSIONS:
        return "frontend"
    if name == "makefile" or suffix in CONFIG_SOURCE_EXTENSIONS:
        return "config"
    if suffix in RUNTIME_SOURCE_EXTENSIONS:
        return "runtime"
    return None


def _source_class(path: str) -> str:
    normalized = path.replace("\\", "/").lower()
    name = normalized.rsplit("/", 1)[-1]
    suffix = _suffix(normalized)
    for candidate in (
        _source_class_from_named_file(normalized, name),
        _source_class_from_low_provenance_path(normalized),
        _source_class_from_runtime_shape(normalized, name, suffix),
    ):
        if candidate:
            return candidate
    return "unknown"


def _source_weight(path: str) -> float:
    return SOURCE_CLASS_WEIGHTS.get(_source_class(path), SOURCE_CLASS_WEIGHTS["unknown"])


def source_reading_rank(path: str) -> tuple[float, int, str]:
    """Rank a candidate source for reading, the one most worth reading first.

    Both readers stop at MAX_FILES, so whichever order they walk in is what
    decides the whole report. Walking in path order let the alphabet decide: on
    cli/cli the budget was spent inside `.github/` and `docs/` and never reached
    `internal/update/update.go`, where the tool's one call to api.github.com is
    written. Where a file sorts is not evidence about what it holds.

    Provenance already answers the question that needs answering here. A file's
    source class says how much of the repository's own voice is in it, and the
    file the tool is made of is the file worth spending the budget on -- so the
    first key is that weight, descending. The second is path depth, because
    within one class the shallow file is what the package presents and the deep
    one is a detail of it; taking the shallow ones first spreads a hundred slots
    across the top of a tree instead of exhausting its first branch. The path
    itself settles what is left, so two reads of the same tree read the same
    files.

    Measured over sixteen repositories this took the endpoints reported from 206
    to 270 and the dependencies from 318 to 421, and cli/cli named api.github.com
    for the first time.
    """
    normalized = path.replace("\\", "/")
    return (-_source_weight(normalized), normalized.count("/"), normalized)


def order_sources_for_reading(
    items: list[Any],
    path_of: Callable[[Any], str] = lambda item: item,
    *,
    budget: int = MAX_FILES,
) -> list[Any]:
    """Order candidates so the file budget cannot starve the context buckets.

    Returns every candidate, reordered -- the caller still stops at MAX_FILES,
    and still walks on past anything the size or decode checks reject, so this
    changes which files are reached and nothing about how they are read.

    The reserve is placed first rather than appended to the head of the
    weight-ranked run. MAX_TOTAL_BYTES cuts a large repository before MAX_FILES
    does, and a reserve that sits behind two megabytes of runtime source is a
    reserve that large repositories never reach -- which is the case this exists
    for. Ahead of it, the reserve costs the findings pool at most 20 slots of
    120 and typically a few hundred kilobytes of the two-megabyte ceiling.
    """
    slots = min(CONTEXT_RESERVE_SLOTS, budget // CONTEXT_RESERVE_BUDGET_DIVISOR)
    ranked = sorted(items, key=lambda item: source_reading_rank(path_of(item)))
    if slots <= 0:
        return ranked
    by_class: dict[str, list[Any]] = {name: [] for name, _ in CONTEXT_RESERVE_QUOTAS}
    for item in ranked:
        bucket = by_class.get(_source_class(path_of(item)))
        if bucket is not None:
            bucket.append(item)
    reserved: list[Any] = []
    taken: dict[str, int] = {}
    for name, quota in CONTEXT_RESERVE_QUOTAS:
        chosen = by_class[name][: min(quota, slots)]
        taken[name] = len(chosen)
        reserved.extend(chosen)
    # Spill: a repository with no CI should spend those slots on tests, not
    # leave them unused, so make a second pass for whatever the quotas left.
    for name, _quota in CONTEXT_RESERVE_QUOTAS:
        spare = slots - len(reserved)
        if spare <= 0:
            break
        reserved.extend(by_class[name][taken[name] : taken[name] + spare])
    reserved = reserved[:slots]
    if not reserved:
        return ranked
    held = {id(item) for item in reserved}
    return reserved + [item for item in ranked if id(item) not in held]


def _evidence(path: str, line_number: int, line: str, matched: str) -> dict[str, Any]:
    source_class = _source_class(path)
    return {
        "path": path,
        "line": line_number,
        "match": matched[:80],
        "excerpt": _line_excerpt(line),
        "sourceClass": source_class,
        "sourceWeight": SOURCE_CLASS_WEIGHTS.get(source_class, SOURCE_CLASS_WEIGHTS["unknown"]),
    }


def _line_for_text(content: str, needle: str) -> tuple[int, str]:
    for line_number, line in enumerate(content.splitlines() or [""], start=1):
        if needle in line:
            return line_number, line[:MAX_LINE_CHARS]
    return 1, (content.splitlines() or [""])[0][:MAX_LINE_CHARS]


def _normalize_source_files(files: object, *, max_file_bytes: int = MAX_FILE_BYTES) -> list[SourceFile]:
    if not isinstance(files, list) or not files:
        message = "files must be a non-empty list of {path, content}"
        raise SourceAnalysisError(message)
    if len(files) > MAX_FILES:
        message = f"files may contain at most {MAX_FILES} entries"
        raise SourceAnalysisError(message)
    total = 0
    normalized: list[SourceFile] = []
    for item in files:
        if not isinstance(item, dict):
            message = "each file entry must be an object"
            raise SourceAnalysisError(message)
        path = _clean_path(item.get("path"))
        content = item.get("content")
        if not isinstance(content, str):
            message = f"{path}: content must be text"
            raise SourceAnalysisError(message)
        encoded_size = len(content.encode("utf-8"))
        if encoded_size > max_file_bytes:
            message = f"{path}: file is larger than {max_file_bytes} bytes"
            raise SourceAnalysisError(message)
        total += encoded_size
        if total > MAX_TOTAL_BYTES:
            message = f"submitted files are larger than {MAX_TOTAL_BYTES} bytes in total"
            raise SourceAnalysisError(message)
        if _is_source_path(path):
            normalized.append(SourceFile(path=path, content=content))
    if not normalized:
        message = "no supported source files were provided"
        raise SourceAnalysisError(message)
    return normalized


def _put(  # noqa: PLR0913 - explicit finding fields avoid opaque tuple packing at every call site.
    findings: dict[tuple[str, str], Finding],
    *,
    kind: str,
    value: str,
    label: str,
    category: str,
    confidence: float,
    reason: str,
    evidence: dict[str, Any],
    version: str | None = None,
) -> None:
    key = (kind, value)
    current = findings.get(key)
    if current is None:
        current = Finding(value=value, label=label, kind=kind, category=category)
        findings[key] = current
    current.add(confidence, reason, evidence)
    current.note_version(version)


def _clean_version_spec(value: object) -> str | None:
    """Return the version a manifest declared, or None when it declared none.

    A dependency resolved from a git URL, a path, or a workspace carries a
    locator where the version would be, and `*` carries a deliberate absence.
    Both are dropped: a locator rendered as a version would be wrong, and `*`
    rendered as one would turn "unspecified" into a specification.
    """
    spec = str(value or "").strip()
    if not spec or len(spec) > MAX_VERSION_CHARS:
        return None
    if spec.lower() in UNVERSIONED_SPECS:
        return None
    if spec.lower().startswith(NON_VERSION_SPEC_PREFIXES):
        return None
    return spec


def _exact_version(spec: str) -> str | None:
    """Return the single release a constraint pins, or None when it pins a range."""
    match = EXACT_VERSION_RE.match(spec)
    return match.group(1) if match else None


def _mapping_version_spec(value: object) -> str | None:
    """Read the constraint beside a name in a dependency mapping.

    Poetry and Pipfile write a table where npm writes a string --
    `flask = {version = "^3.0", extras = [...]}` -- so the table's own
    `version` key is read before falling back to the scalar form.
    """
    if isinstance(value, dict):
        return _clean_version_spec(value.get("version"))
    if isinstance(value, str):
        return _clean_version_spec(value)
    return None


def _requirement_version(line: str) -> str | None:
    """Return the constraint in a PEP 508 requirement, such as `flask>=3.0,<4`."""
    clean = line.split("#", 1)[0].strip()
    if not clean or clean.startswith(("-", "--")) or " @ " in clean:
        return None
    body = clean.split("[", 1)[-1].split("]", 1)[-1] if "[" in clean else clean
    match = re.search(r"(?:[=!<>~^]=?|===)\s*[^\s;]+(?:\s*,\s*(?:[=!<>~^]=?|===)\s*[^\s;]+)*", body)
    return _clean_version_spec(match.group(0).replace(" ", "")) if match else None


def _clean_dependency_name(value: object) -> str | None:
    name = str(value or "").strip()
    if not name or len(name) > MAX_DEPENDENCY_NAME_CHARS:
        return None
    if name.startswith((".", "/", "http://", "https://", "git+", "file:")):
        return None
    return name


def _dependency_value(ecosystem: str, name: str) -> str:
    return f"{ecosystem}:{name.lower()}"


def _put_dependency(  # noqa: PLR0913 - explicit dependency fields keep call sites readable across ecosystems.
    findings: dict[tuple[str, str], Finding],
    *,
    ecosystem: str,
    name: str,
    category: str,
    confidence: float,
    reason: str,
    evidence: dict[str, Any],
    version: str | None = None,
) -> None:
    clean_name = _clean_dependency_name(name)
    if clean_name is None:
        return
    normalized = clean_name.lower()
    if (ecosystem == "pypi" and normalized == "python") or (
        ecosystem == "composer" and (normalized == "php" or normalized.startswith("ext-"))
    ):
        return
    _put(
        findings,
        kind="dependencies",
        value=_dependency_value(ecosystem, clean_name),
        label=f"{clean_name} ({ecosystem})",
        category=category,
        confidence=confidence,
        reason=reason,
        evidence=evidence,
        version=version,
    )
    _scan_dependency_api_signals(findings, ecosystem, clean_name, evidence)


def _scan_dependency_api_signals(
    findings: dict[tuple[str, str], Finding], ecosystem: str, name: str, evidence: dict[str, Any]
) -> None:
    normalized = name.lower()
    mediawiki_clients = {
        "mediawiki-api",
        "mediawiki",
        # The ResourceLoader spelling. It is the Action API client 61 of the 487
        # measured gadgets pull in, and the exact-name test above would miss it
        # -- no gadget depends on a module called plainly `mediawiki`.
        "mediawiki.api",
        "mw-api",
        "mwclient",
        "pywikibot",
    }
    wikibase_clients = {
        "wikibase-sdk",
        "wikibase-edit",
        "wikidata-sdk",
        "wikidata-sdk-rdf",
    }
    if normalized in mediawiki_clients or normalized.endswith("/mediawiki-api"):
        _put(
            findings,
            kind="apis",
            value="mediawiki-action-api",
            label="MediaWiki Action API",
            category="detected",
            confidence=0.86,
            reason=f"{ecosystem} dependency suggests MediaWiki Action API usage.",
            evidence=evidence,
        )
    if normalized in wikibase_clients or "wikibase" in normalized or "wikidata" in normalized:
        _put(
            findings,
            kind="apis",
            value="wikibase-api",
            label="Wikibase API",
            category="detected",
            confidence=0.82,
            reason=f"{ecosystem} dependency suggests Wikibase API usage.",
            evidence=evidence,
        )


def _scan_mapping_dependencies(  # noqa: PLR0913 - manifest source, ecosystem, and confidence are independent.
    findings: dict[tuple[str, str], Finding],
    *,
    path: str,
    content: str,
    ecosystem: str,
    mapping: object,
    category: str,
    reason: str,
    confidence: float,
) -> None:
    if not isinstance(mapping, dict):
        return
    for name, spec in mapping.items():
        clean_name = _clean_dependency_name(name)
        if clean_name is None:
            continue
        line_number, line = _line_for_text(content, str(name))
        _put_dependency(
            findings,
            ecosystem=ecosystem,
            name=clean_name,
            category=category,
            confidence=confidence,
            reason=reason,
            evidence=_evidence(path, line_number, line, clean_name),
            version=_mapping_version_spec(spec),
        )


def _put_runtime(  # noqa: PLR0913 - the manifest, the key, and the anchor are independent.
    findings: dict[tuple[str, str], Finding],
    *,
    runtime: str,
    spec: object,
    path: str,
    content: str,
    anchor: str,
    reason: str,
) -> None:
    """Record the runtime a manifest declares, with the version it pins to it."""
    value = RUNTIME_TECHNOLOGY.get(runtime)
    version = _clean_version_spec(spec)
    if value is None or version is None:
        return
    line_number, line = _line_for_text(content, anchor)
    _put(
        findings,
        kind="technology",
        value=value,
        label=value,
        category="language",
        confidence=0.88,
        reason=reason,
        evidence=_evidence(path, line_number, line, anchor),
        version=version,
    )


def _scan_package_json(findings: dict[tuple[str, str], Finding], source_file: SourceFile) -> None:
    try:
        data = json.loads(source_file.content)
    except json.JSONDecodeError:
        return
    groups = {
        "dependencies": ("runtime", "Declared npm runtime dependency.", 0.98),
        "optionalDependencies": ("optional", "Declared npm optional dependency.", 0.9),
        "peerDependencies": ("peer", "Declared npm peer dependency.", 0.88),
        "devDependencies": ("development", "Declared npm development dependency.", 0.78),
    }
    for key, (category, reason, confidence) in groups.items():
        _scan_mapping_dependencies(
            findings,
            path=source_file.path,
            content=source_file.content,
            ecosystem="npm",
            mapping=data.get(key) if isinstance(data, dict) else None,
            category=category,
            reason=reason,
            confidence=confidence,
        )
    engines = data.get("engines") if isinstance(data, dict) else None
    if isinstance(engines, dict):
        _put_runtime(
            findings,
            runtime="node",
            spec=engines.get("node"),
            path=source_file.path,
            content=source_file.content,
            anchor="engines",
            reason="Declared Node.js engine requirement.",
        )


def _requirement_name(line: str) -> str | None:
    clean = line.split("#", 1)[0].strip()
    if not clean or clean.startswith(("-", "--")):
        return None
    if " @ " in clean:
        clean = clean.split(" @ ", 1)[0].strip()
    match = REQ_NAME_RE.match(clean.split("[", 1)[0])
    return match.group(1) if match else None


def _scan_requirements_txt(findings: dict[tuple[str, str], Finding], source_file: SourceFile) -> None:
    for line_number, raw_line in enumerate(source_file.content.splitlines() or [""], start=1):
        name = _requirement_name(raw_line)
        if name is None:
            continue
        _put_dependency(
            findings,
            ecosystem="pypi",
            name=name,
            category="runtime",
            confidence=0.94,
            reason="Declared Python requirement.",
            evidence=_evidence(source_file.path, line_number, raw_line, name),
            version=_requirement_version(raw_line),
        )


def _scan_pyproject_toml(findings: dict[tuple[str, str], Finding], source_file: SourceFile) -> None:
    try:
        data = tomllib.loads(source_file.content)
    except tomllib.TOMLDecodeError:
        return
    project = data.get("project") if isinstance(data, dict) else {}
    if isinstance(project, dict):
        for requirement in project.get("dependencies") or []:
            name = _requirement_name(str(requirement))
            if name:
                line_number, line = _line_for_text(source_file.content, name)
                _put_dependency(
                    findings,
                    ecosystem="pypi",
                    name=name,
                    category="runtime",
                    confidence=0.92,
                    reason="Declared Python project dependency.",
                    evidence=_evidence(source_file.path, line_number, line, name),
                    version=_requirement_version(str(requirement)),
                )
        optional = project.get("optional-dependencies")
        if isinstance(optional, dict):
            for requirements in optional.values():
                for requirement in requirements if isinstance(requirements, list) else []:
                    name = _requirement_name(str(requirement))
                    if name:
                        line_number, line = _line_for_text(source_file.content, name)
                        _put_dependency(
                            findings,
                            ecosystem="pypi",
                            name=name,
                            category="optional",
                            confidence=0.82,
                            reason="Declared Python optional dependency.",
                            evidence=_evidence(source_file.path, line_number, line, name),
                            version=_requirement_version(str(requirement)),
                        )
        _put_runtime(
            findings,
            runtime="python",
            spec=project.get("requires-python"),
            path=source_file.path,
            content=source_file.content,
            anchor="requires-python",
            reason="Declared Python version requirement.",
        )
    poetry = data.get("tool", {}).get("poetry", {}) if isinstance(data.get("tool"), dict) else {}
    if isinstance(poetry, dict):
        _scan_mapping_dependencies(
            findings,
            path=source_file.path,
            content=source_file.content,
            ecosystem="pypi",
            mapping=poetry.get("dependencies"),
            category="runtime",
            reason="Declared Poetry runtime dependency.",
            confidence=0.9,
        )
        _scan_mapping_dependencies(
            findings,
            path=source_file.path,
            content=source_file.content,
            ecosystem="pypi",
            mapping=poetry.get("group", {}).get("dev", {}).get("dependencies")
            if isinstance(poetry.get("group"), dict)
            else None,
            category="development",
            reason="Declared Poetry development dependency.",
            confidence=0.76,
        )
    _scan_mapping_dependencies(
        findings,
        path=source_file.path,
        content=source_file.content,
        ecosystem="cargo",
        mapping=data.get("dependencies") if isinstance(data, dict) else None,
        category="runtime",
        reason="Declared Cargo runtime dependency.",
        confidence=0.92,
    )
    _scan_mapping_dependencies(
        findings,
        path=source_file.path,
        content=source_file.content,
        ecosystem="cargo",
        mapping=data.get("dev-dependencies") if isinstance(data, dict) else None,
        category="development",
        reason="Declared Cargo development dependency.",
        confidence=0.78,
    )


def _scan_pipfile(findings: dict[tuple[str, str], Finding], source_file: SourceFile) -> None:
    try:
        data = tomllib.loads(source_file.content)
    except tomllib.TOMLDecodeError:
        return
    _scan_mapping_dependencies(
        findings,
        path=source_file.path,
        content=source_file.content,
        ecosystem="pypi",
        mapping=data.get("packages") if isinstance(data, dict) else None,
        category="runtime",
        reason="Declared Pipfile runtime dependency.",
        confidence=0.9,
    )
    _scan_mapping_dependencies(
        findings,
        path=source_file.path,
        content=source_file.content,
        ecosystem="pypi",
        mapping=data.get("dev-packages") if isinstance(data, dict) else None,
        category="development",
        reason="Declared Pipfile development dependency.",
        confidence=0.76,
    )


def _scan_composer_json(findings: dict[tuple[str, str], Finding], source_file: SourceFile) -> None:
    try:
        data = json.loads(source_file.content)
    except json.JSONDecodeError:
        return
    _scan_mapping_dependencies(
        findings,
        path=source_file.path,
        content=source_file.content,
        ecosystem="composer",
        mapping=data.get("require") if isinstance(data, dict) else None,
        category="runtime",
        reason="Declared Composer runtime dependency.",
        confidence=0.94,
    )
    _scan_mapping_dependencies(
        findings,
        path=source_file.path,
        content=source_file.content,
        ecosystem="composer",
        mapping=data.get("require-dev") if isinstance(data, dict) else None,
        category="development",
        reason="Declared Composer development dependency.",
        confidence=0.78,
    )
    require = data.get("require") if isinstance(data, dict) else None
    if isinstance(require, dict):
        _put_runtime(
            findings,
            runtime="php",
            spec=require.get("php"),
            path=source_file.path,
            content=source_file.content,
            anchor="php",
            reason="Declared PHP version requirement.",
        )


def _scan_go_mod(findings: dict[tuple[str, str], Finding], source_file: SourceFile) -> None:
    for line_number, raw_line in enumerate(source_file.content.splitlines() or [""], start=1):
        clean = raw_line.split("//", 1)[0].strip()
        go_directive = GO_DIRECTIVE_RE.match(clean)
        if go_directive:
            _put_runtime(
                findings,
                runtime="go",
                spec=go_directive.group(1),
                path=source_file.path,
                content=source_file.content,
                anchor=clean,
                reason="Declared Go language version.",
            )
            continue
        if clean.startswith("require "):
            clean = clean.removeprefix("require ").strip()
        match = GO_REQUIRE_RE.match(clean)
        if not match:
            continue
        name = match.group(1)
        version_match = GO_VERSION_RE.match(clean)
        _put_dependency(
            findings,
            ecosystem="go",
            name=name,
            category="runtime",
            confidence=0.93,
            reason="Declared Go module dependency.",
            evidence=_evidence(source_file.path, line_number, raw_line, name),
            version=_clean_version_spec(version_match.group(1)) if version_match else None,
        )


def _scan_gemfile(findings: dict[tuple[str, str], Finding], source_file: SourceFile) -> None:
    for line_number, raw_line in enumerate(source_file.content.splitlines() or [""], start=1):
        match = GEM_RE.match(raw_line)
        if not match:
            continue
        name = match.group(1)
        version_match = GEM_VERSION_RE.match(raw_line)
        _put_dependency(
            findings,
            ecosystem="rubygems",
            name=name,
            category="runtime",
            confidence=0.92,
            reason="Declared Ruby gem dependency.",
            evidence=_evidence(source_file.path, line_number, raw_line, name),
            version=_clean_version_spec(version_match.group(1)) if version_match else None,
        )


def _scan_package_lock(findings: dict[tuple[str, str], Finding], source_file: SourceFile) -> None:
    try:
        data = json.loads(source_file.content)
    except json.JSONDecodeError:
        return
    if not isinstance(data, dict):
        return
    packages = data.get("packages")
    if isinstance(packages, dict):
        for package_path in packages:
            if not str(package_path).startswith("node_modules/"):
                continue
            name = str(package_path).removeprefix("node_modules/")
            entry = packages.get(package_path)
            line_number, line = _line_for_text(source_file.content, str(package_path))
            _put_dependency(
                findings,
                ecosystem="npm",
                name=name,
                category="locked",
                confidence=0.84,
                reason="Locked npm dependency.",
                evidence=_evidence(source_file.path, line_number, line, name),
                version=_mapping_version_spec(entry),
            )
    dependencies = data.get("dependencies")
    _scan_mapping_dependencies(
        findings,
        path=source_file.path,
        content=source_file.content,
        ecosystem="npm",
        mapping=dependencies if isinstance(dependencies, dict) else None,
        category="locked",
        reason="Locked npm dependency.",
        confidence=0.84,
    )


def _scan_pipfile_lock(findings: dict[tuple[str, str], Finding], source_file: SourceFile) -> None:
    try:
        data = json.loads(source_file.content)
    except json.JSONDecodeError:
        return
    if not isinstance(data, dict):
        return
    _scan_mapping_dependencies(
        findings,
        path=source_file.path,
        content=source_file.content,
        ecosystem="pypi",
        mapping=data.get("default"),
        category="locked",
        reason="Locked Pipfile dependency.",
        confidence=0.84,
    )
    _scan_mapping_dependencies(
        findings,
        path=source_file.path,
        content=source_file.content,
        ecosystem="pypi",
        mapping=data.get("develop"),
        category="development",
        reason="Locked Pipfile development dependency.",
        confidence=0.72,
    )


def _scan_poetry_lock(findings: dict[tuple[str, str], Finding], source_file: SourceFile) -> None:
    try:
        data = tomllib.loads(source_file.content)
    except tomllib.TOMLDecodeError:
        return
    packages = data.get("package") if isinstance(data, dict) else None
    for package in packages if isinstance(packages, list) else []:
        if not isinstance(package, dict):
            continue
        name = _clean_dependency_name(package.get("name"))
        if name is None:
            continue
        line_number, line = _line_for_text(source_file.content, str(name))
        _put_dependency(
            findings,
            ecosystem="pypi",
            name=name,
            category="locked",
            confidence=0.84,
            reason="Locked Poetry dependency.",
            evidence=_evidence(source_file.path, line_number, line, name),
            version=_mapping_version_spec(package),
        )


def _scan_composer_lock(findings: dict[tuple[str, str], Finding], source_file: SourceFile) -> None:
    try:
        data = json.loads(source_file.content)
    except json.JSONDecodeError:
        return
    if not isinstance(data, dict):
        return
    for section, category, confidence in (("packages", "locked", 0.86), ("packages-dev", "development", 0.72)):
        packages = data.get(section)
        for package in packages if isinstance(packages, list) else []:
            if not isinstance(package, dict):
                continue
            name = _clean_dependency_name(package.get("name"))
            if name is None:
                continue
            line_number, line = _line_for_text(source_file.content, str(name))
            _put_dependency(
                findings,
                ecosystem="composer",
                name=name,
                category=category,
                confidence=confidence,
                reason="Locked Composer dependency.",
                evidence=_evidence(source_file.path, line_number, line, name),
                version=_mapping_version_spec(package),
            )


def _scan_cargo_lock(findings: dict[tuple[str, str], Finding], source_file: SourceFile) -> None:
    try:
        data = tomllib.loads(source_file.content)
    except tomllib.TOMLDecodeError:
        return
    packages = data.get("package") if isinstance(data, dict) else None
    for package in packages if isinstance(packages, list) else []:
        if not isinstance(package, dict):
            continue
        name = _clean_dependency_name(package.get("name"))
        if name is None:
            continue
        line_number, line = _line_for_text(source_file.content, str(name))
        _put_dependency(
            findings,
            ecosystem="cargo",
            name=name,
            category="locked",
            confidence=0.84,
            reason="Locked Cargo dependency.",
            evidence=_evidence(source_file.path, line_number, line, name),
            version=_mapping_version_spec(package),
        )


def _scan_gemfile_lock(findings: dict[tuple[str, str], Finding], source_file: SourceFile) -> None:
    for line_number, raw_line in enumerate(source_file.content.splitlines() or [""], start=1):
        match = GEM_LOCK_RE.match(raw_line)
        if not match:
            continue
        name = match.group(1)
        version_match = GEM_LOCK_VERSION_RE.match(raw_line)
        _put_dependency(
            findings,
            ecosystem="rubygems",
            name=name,
            category="locked",
            confidence=0.82,
            reason="Locked Ruby gem dependency.",
            evidence=_evidence(source_file.path, line_number, raw_line, name),
            version=_clean_version_spec(version_match.group(1)) if version_match else None,
        )


def _lock_package_from_locator(locator: str) -> str | None:
    clean = locator.strip().strip("\"'")
    if clean.startswith((".", "/")):
        return None
    if clean.startswith("@"):
        parts = clean.split("@")
        return f"@{parts[1]}" if len(parts) > 1 else None
    return clean.split("@", 1)[0]


def _scan_yarn_lock(findings: dict[tuple[str, str], Finding], source_file: SourceFile) -> None:
    """Read locked npm packages out of a yarn.lock or pnpm-lock.yaml.

    Unlike every other lockfile, these write the resolved version on its own
    line *below* the locator, so a locator is held back until that line
    arrives. A locator followed by another locator declared no version we can
    read, and is emitted without one rather than borrowing the next entry's.
    """
    pending: tuple[str, int, str] | None = None

    def emit(entry: tuple[str, int, str] | None, version: str | None) -> None:
        if entry is None:
            return
        name, line_number, raw_line = entry
        _put_dependency(
            findings,
            ecosystem="npm",
            name=name,
            category="locked",
            confidence=0.78,
            reason="Locked Yarn dependency.",
            evidence=_evidence(source_file.path, line_number, raw_line, name),
            version=version,
        )

    for line_number, raw_line in enumerate(source_file.content.splitlines() or [""], start=1):
        match = YARN_LOCK_RE.match(raw_line)
        if match:
            emit(pending, None)
            name = _lock_package_from_locator(match.group(1))
            pending = None if name is None else (name, line_number, raw_line)
            continue
        version_match = YARN_VERSION_RE.match(raw_line)
        if version_match and pending is not None:
            emit(pending, _clean_version_spec(version_match.group(1)))
            pending = None
    emit(pending, None)


def _scan_lockfile_dependencies(findings: dict[tuple[str, str], Finding], source_file: SourceFile) -> None:
    name = source_file.path.rsplit("/", 1)[-1].lower()
    if name in {"package-lock.json", "npm-shrinkwrap.json"}:
        _scan_package_lock(findings, source_file)
    elif name == "pipfile.lock":
        _scan_pipfile_lock(findings, source_file)
    elif name == "poetry.lock":
        _scan_poetry_lock(findings, source_file)
    elif name == "composer.lock":
        _scan_composer_lock(findings, source_file)
    elif name == "cargo.lock":
        _scan_cargo_lock(findings, source_file)
    elif name == "gemfile.lock":
        _scan_gemfile_lock(findings, source_file)
    elif name in {"yarn.lock", "pnpm-lock.yaml"}:
        _scan_yarn_lock(findings, source_file)


def _external_js_package(value: str) -> str | None:
    if value.startswith((".", "/", "http://", "https://")):
        return None
    parts = value.split("/")
    if value.startswith("@") and len(parts) >= JS_SCOPED_PACKAGE_PARTS:
        return "/".join(parts[:JS_SCOPED_PACKAGE_PARTS])
    return parts[0]


def _scan_js_import_dependencies(
    findings: dict[tuple[str, str], Finding], path: str, line_number: int, line: str
) -> None:
    for match in JS_IMPORT_RE.finditer(line):
        name = _external_js_package(match.group("from") or match.group("call") or "")
        if name:
            _put_dependency(
                findings,
                ecosystem="npm",
                name=name,
                category="imported",
                confidence=0.7,
                reason="Imported JavaScript package.",
                evidence=_evidence(path, line_number, line, name),
            )


def _scan_python_import_dependencies(
    findings: dict[tuple[str, str], Finding],
    path: str,
    line_number: int,
    line: str,
    local_python_roots: set[str],
) -> None:
    match = PY_IMPORT_RE.match(line)
    if not match:
        return
    name = (match.group(1) or match.group(2) or "").split(".", 1)[0]
    if name and name not in sys.stdlib_module_names and name not in local_python_roots:
        _put_dependency(
            findings,
            ecosystem="pypi",
            name=name,
            category="imported",
            confidence=0.68,
            reason="Imported Python module; verify whether it is external.",
            evidence=_evidence(path, line_number, line, name),
        )


def _scan_php_import_dependencies(
    findings: dict[tuple[str, str], Finding], path: str, line_number: int, line: str
) -> None:
    match = PHP_USE_RE.match(line)
    if not match:
        return
    name = match.group(1).split("\\", 1)[0]
    _put_dependency(
        findings,
        ecosystem="composer",
        name=name,
        category="imported",
        confidence=0.62,
        reason="Imported PHP namespace; verify whether it is external.",
        evidence=_evidence(path, line_number, line, name),
    )


def _scan_ruby_import_dependencies(
    findings: dict[tuple[str, str], Finding], path: str, line_number: int, line: str
) -> None:
    match = RUBY_REQUIRE_RE.match(line)
    if not match:
        return
    name = match.group(1)
    _put_dependency(
        findings,
        ecosystem="rubygems",
        name=name,
        category="imported",
        confidence=0.62,
        reason="Required Ruby library; verify whether it is external.",
        evidence=_evidence(path, line_number, line, name),
    )


def _scan_import_dependencies(
    findings: dict[tuple[str, str], Finding],
    path: str,
    line_number: int,
    line: str,
    local_python_roots: set[str],
) -> None:
    suffix = _suffix(path)
    if suffix in JS_SOURCE_SUFFIXES:
        _scan_js_import_dependencies(findings, path, line_number, line)
    elif suffix == ".py":
        _scan_python_import_dependencies(findings, path, line_number, line, local_python_roots)
    elif suffix == ".php":
        _scan_php_import_dependencies(findings, path, line_number, line)
    elif suffix == ".rb":
        _scan_ruby_import_dependencies(findings, path, line_number, line)


def _scan_manifest_dependencies(findings: dict[tuple[str, str], Finding], source_file: SourceFile) -> None:
    name = source_file.path.rsplit("/", 1)[-1].lower()
    if name == "package.json":
        _scan_package_json(findings, source_file)
    elif name.startswith("requirements") and name.endswith(".txt"):
        _scan_requirements_txt(findings, source_file)
    elif name in {"pyproject.toml", "cargo.toml"}:
        _scan_pyproject_toml(findings, source_file)
    elif name == "pipfile":
        _scan_pipfile(findings, source_file)
    elif name == "composer.json":
        _scan_composer_json(findings, source_file)
    elif name == "go.mod":
        _scan_go_mod(findings, source_file)
    elif name == "gemfile":
        _scan_gemfile(findings, source_file)
    elif name in LOCKFILE_KINDS:
        _scan_lockfile_dependencies(findings, source_file)


def _declared_evidence(dependency: Finding) -> dict[str, Any] | None:
    """Return the first evidence for a dependency somebody wrote down."""
    for item in dependency.evidence:
        if str(item.get("sourceClass") or "") in DECLARED_DEPENDENCY_SOURCE_CLASSES:
            return item
    return None


def _reconcile_technology_packages(findings: dict[tuple[str, str], Finding]) -> None:
    """Join each technology to the package that carries its name and version.

    Both directions. A package the tool declares -- in a manifest, or by
    importing it from its own code -- is evidence the tool is built with that
    technology, so it can name one no source file reached. A package a lockfile
    resolved is not, because a lockfile names every transitive dependency a
    build would fetch and the tool chose almost none of them. Either way the
    constraint travels onto the technology, because the manifest naming the
    version and the source proving the usage are rarely the same file.
    """
    for technology, (package, category) in TECHNOLOGY_PACKAGES.items():
        dependency = findings.get(("dependencies", package))
        if dependency is None:
            continue
        key = ("technology", technology)
        if key not in findings:
            evidence = _declared_evidence(dependency)
            if evidence is None:
                continue
            _put(
                findings,
                kind="technology",
                value=technology,
                label=technology,
                category=category,
                confidence=DECLARED_TECHNOLOGY_CONFIDENCE,
                reason="Declared dependency on this technology's package.",
                evidence=evidence,
            )
        for spec in dependency.version_specs:
            findings[key].note_version(spec)


def _local_python_import_roots(files: list[SourceFile]) -> set[str]:
    roots = set(LOCAL_IMPORT_ROOTS)
    for source_file in files:
        if _suffix(source_file.path) != ".py":
            continue
        parts = source_file.path.split("/")
        name = parts[-1]
        if name == "__init__.py" and len(parts) > 1:
            roots.add(parts[-2])
        elif name.endswith(".py"):
            roots.add(name[:-3])
    return roots


def _project_from_host(host: str, sub: str, family: str) -> tuple[str, str, float] | None:
    """Map a Wikimedia hostname to (database name, label, confidence), or None.

    None means "this hostname is not a wiki", and it is the important return.
    The fallthrough here used to be `host, host, 0.78` -- above every
    publication threshold -- so gerrit.wikimedia.org, phabricator.wikimedia.org,
    upload.wikimedia.org and toolsadmin.wikimedia.org were all published as
    wikis a tool works on, under their raw hostnames.

    Mapping every content family, rather than wikipedia alone, also fixes an
    asymmetry that made the output look arbitrary: fr.wikipedia.org became
    `frwiki` while fr.wiktionary.org stayed the literal string
    "fr.wiktionary.org".
    """
    if host in {"wikidata.org", "www.wikidata.org", "query.wikidata.org"}:
        return "wikidatawiki", "Wikidata", 0.94
    if host in {"mediawiki.org", "www.mediawiki.org"}:
        return "mediawikiwiki", "MediaWiki.org", 0.92
    if family == "wikimedia":
        known = WIKIMEDIA_ORG_WIKIS.get(sub)
        return (known[0], known[1], 0.94) if known else None
    suffix = PROJECT_FAMILY_DB_SUFFIX.get(family)
    if suffix is None or not sub or sub == "www" or sub in NON_WIKI_SUBDOMAINS:
        return None
    if not LANGUAGE_SUBDOMAIN_RE.fullmatch(sub):
        return None
    return f"{sub.replace('-', '_')}{suffix}", host, 0.9


def _bounded_line(raw: str) -> str:
    """Return the line cut to budget, without splitting the token at the cut.

    A contributor table in a README is one very long line of URLs, and cutting
    it at a fixed width left `https://avatars.githubusercon` behind -- a name
    that parses as a hostname, resolves nowhere, and reads in a report as a
    real service the tool contacts. Dropping the partial token at the cut
    costs at most one hit and invents none.

    A line with no whitespace in it at all -- minified JavaScript, a long data
    URI -- has no token boundary to cut back to and is left as it was.
    """
    if len(raw) <= MAX_LINE_CHARS:
        return raw
    head, space, _ = raw[:MAX_LINE_CHARS].rpartition(" ")
    return head if space else raw[:MAX_LINE_CHARS]


def _external_endpoint_count(endpoints: list[dict[str, Any]]) -> int:
    return sum(1 for item in endpoints if item["category"] == source_endpoints.FAMILY_EXTERNAL)


def _scan_endpoints(
    findings: dict[tuple[str, str], Finding],
    path: str,
    line_number: int,
    line: str,
    *,
    require_call: bool,
) -> None:
    """Record the concrete addresses this line names, host and path and action.

    Complements the apis bucket rather than duplicating it. API_RULES says a
    tool speaks the Action API; this says it speaks it to commons.wikimedia.org
    with action=upload, which is the difference between a reader and a writer,
    and it is the only scanner that sees a service Wikimedia does not run.
    """
    # The signal has to be looked for around the URL, not inside it. A path
    # like /creating-a-pull-request-from-a-fork carries the word `request`, and
    # reading that as a call promoted a line of prose in CONTRIBUTING.md to the
    # same confidence as a fetch.
    called = bool(REQUEST_SIGNAL_RE.search(source_endpoints.URL_RE.sub(" ", line)))
    if require_call and not called:
        return
    for endpoint in source_endpoints.endpoints(line):
        _put(
            findings,
            kind="endpoints",
            value=endpoint.value,
            label=endpoint.label,
            category=endpoint.family,
            confidence=ENDPOINT_CALLED_CONFIDENCE if called else ENDPOINT_CONFIDENCE,
            reason=("Request to this endpoint." if called else "Endpoint address in source."),
            evidence=_evidence(path, line_number, line, endpoint.value),
        )


def _scan_projects(findings: dict[tuple[str, str], Finding], path: str, line_number: int, line: str) -> None:
    for match in PROJECT_DOMAIN_RE.finditer(line):
        host = match.group(0).lower()
        resolved = _project_from_host(host, (match.group("sub") or "").lower(), match.group("family").lower())
        if resolved is None:
            continue
        value, label, confidence = resolved
        _put(
            findings,
            kind="projects",
            value=value,
            label=label,
            category="wiki",
            confidence=confidence,
            reason="Wikimedia project hostname detected.",
            evidence=_evidence(path, line_number, line, host),
        )
    for match in PROJECT_DB_RE.finditer(line):
        value = match.group(0).lower()
        if value in IGNORED_PROJECT_DB_NAMES or value.endswith("mediawiki"):
            continue
        _put(
            findings,
            kind="projects",
            value=value,
            label=value,
            category="wiki",
            confidence=0.76,
            reason="Wikimedia database name detected.",
            evidence=_evidence(path, line_number, line, value),
        )


def _scan_rules(  # noqa: PLR0913 - scan context plus rule table is clearer as named parameters.
    findings: dict[tuple[str, str], Finding],
    path: str,
    line_number: int,
    line: str,
    rules: tuple[tuple[str, str, re.Pattern[str], float, str], ...],
    *,
    kind: str,
    category: str = "detected",
) -> None:
    for value, label, pattern, confidence, reason in rules:
        match = pattern.search(line)
        if match:
            _put(
                findings,
                kind=kind,
                value=value,
                label=label,
                category=category,
                confidence=confidence,
                reason=reason,
                evidence=_evidence(path, line_number, line, match.group(0)),
            )


def _scan_technology(findings: dict[tuple[str, str], Finding], path: str, line_number: int, line: str) -> None:
    suffix = _suffix(path)
    if line_number == 1 and suffix in TECH_BY_EXTENSION:
        value = TECH_BY_EXTENSION[suffix]
        _put(
            findings,
            kind="technology",
            value=value,
            label=value,
            category="language",
            confidence=0.64,
            reason="Source file extension detected.",
            evidence=_evidence(path, line_number, line, suffix),
        )
    if line_number == 1 and path.casefold().endswith(USER_SCRIPT_SUFFIX):
        _put(
            findings,
            kind="technology",
            value="MediaWiki JavaScript",
            label="MediaWiki JavaScript",
            category="framework",
            confidence=0.9,
            reason="File named as a wiki user script.",
            evidence=_evidence(path, line_number, line, USER_SCRIPT_SUFFIX),
        )
    for value, pattern, confidence in TECH_RULES:
        allowed = TECH_RULE_SUFFIXES.get(value)
        if allowed is not None and suffix not in allowed:
            continue
        match = pattern.search(line)
        if match:
            _put(
                findings,
                kind="technology",
                value=value,
                label=value,
                category="framework",
                confidence=confidence,
                reason="Framework or library usage detected.",
                evidence=_evidence(path, line_number, line, match.group(0)),
            )


def _scan_actions(findings: dict[tuple[str, str], Finding], path: str, line_number: int, line: str) -> None:
    actions = [match.group(1).lower() for match in ACTION_QUERY_RE.finditer(line)]
    actions.extend(match.group(1).lower() for match in ACTION_OBJECT_RE.finditer(line))
    for action in actions:
        _put(
            findings,
            kind="apis",
            value="mediawiki-action-api",
            label="MediaWiki Action API",
            category="detected",
            confidence=0.9,
            reason=f"MediaWiki action={action} request detected.",
            evidence=_evidence(path, line_number, line, action),
        )
        if action in READ_ACTIONS:
            _put(
                findings,
                kind="accessRights",
                value="read-public",
                label="Read public wiki data",
                category="read",
                confidence=0.66,
                reason=f"Read-only action={action} request detected.",
                evidence=_evidence(path, line_number, line, action),
            )
        for value, label, category, confidence in ACTION_RIGHTS.get(action, ()):
            _put(
                findings,
                kind="accessRights",
                value=value,
                label=label,
                category=category,
                confidence=confidence,
                reason=f"MediaWiki action={action} usually requires {label.lower()}.",
                evidence=_evidence(path, line_number, line, action),
            )


def _gadget_right_row(right: str) -> tuple[str, str, bool]:
    """Return the value, label, and whether the vocabulary describes this right.

    An unmeasured right keeps its own name rather than being dropped. The five
    definition pages this vocabulary was built from are not every wiki, and a
    gadget limited to a right never seen before is the one a reader most needs
    told about -- reporting it under its raw name is a smaller error than
    silence.

    The third value exists because that fallback used to be invisible. A right
    the table describes and a right it has never seen produced findings of the
    same shape, so the only difference a reader saw was that one label read as
    jargon; and nothing counted how often it happened. Both halves are fixed
    from this flag: the finding says plainly that the analyzer cannot describe
    the right, and the report records the rate -- see `_wiki_page_row`.
    """
    row = GADGET_RIGHT_VOCABULARY.get(right)
    return (*row, True) if row is not None else (right, right, False)


def _scan_gadget_declaration(
    findings: dict[tuple[str, str], Finding],
    declaration: wiki_sources.GadgetDeclaration,
) -> None:
    """Record what `MediaWiki:Gadgets-definition` declares about this gadget.

    Read after the source files rather than before them, and deliberately. A
    right that code was also seen exercising keeps the category that observation
    gave it -- `_put` sets a category once, on the first sighting -- so an
    `action=rollback` call still reads as moderation rather than being relabelled
    as a restriction by a line that only says who the gadget is served to.

    `dependencies=` is the only dependency manifest a gadget has -- there is no
    package.json on a wiki page -- so its modules are reported as dependencies
    in their own `resourceloader` ecosystem. They route through `_put_dependency`
    rather than straight to `_put` so a module that names an API client is read
    as one by the same rule that reads npm and pypi clients, instead of by a
    second copy of that rule that could drift from it.

    `default`, `hidden` and the scope options are not rights and are not
    reported as ones. They say how far the gadget reaches -- who gets it without
    asking, who can refuse it, and where it loads -- which changes how much
    every right here matters without being a right itself. They travel on the
    wikiPage row and as a neutral signal, where they can inform a reader without
    being scored as permissions.
    """
    entry = declaration.entry
    evidence_line = declaration.line
    for raw in entry.values(GADGET_DEPENDENCIES_OPTION):
        module = raw.strip()
        if not module:
            continue
        _put_dependency(
            findings,
            ecosystem=GADGET_MODULE_ECOSYSTEM,
            name=module,
            category=GADGET_MODULE_CATEGORY,
            confidence=GADGET_MODULE_CONFIDENCE,
            reason="MediaWiki:Gadgets-definition loads this ResourceLoader module before the gadget runs.",
            evidence=_evidence(GADGET_DEFINITION_PAGE_TITLE, declaration.line_number, evidence_line, module),
        )
    for raw in entry.values(GADGET_RIGHTS_OPTION):
        right = raw.strip().lower()
        if not right:
            continue
        value, label, described = _gadget_right_row(right)
        reason = f"MediaWiki:Gadgets-definition serves this gadget only to users with the {right} right."
        if not described:
            # Confidence is unchanged: the wiki declared this gate as plainly as
            # any other, and what is missing is this analyzer's description of
            # it, not evidence. Saying so is the honest reading -- the raw name
            # on its own looks like a label a reader failed to understand.
            reason += " This analyzer has no description for that right."
        _put(
            findings,
            kind="accessRights",
            value=value,
            label=label,
            category=GADGET_DECLARED_RIGHT_CATEGORY,
            confidence=GADGET_DECLARED_RIGHT_CONFIDENCE,
            reason=reason,
            evidence=_evidence(GADGET_DEFINITION_PAGE_TITLE, declaration.line_number, evidence_line, right),
        )


def _scan_oauth_scopes(findings: dict[tuple[str, str], Finding], path: str, line_number: int, line: str) -> None:
    if not SCOPE_LINE_RE.search(line):
        return
    lower = line.lower()
    for scope, (label, confidence) in KNOWN_OAUTH_SCOPES.items():
        if re.search(rf"\b{re.escape(scope)}\b", lower):
            _put(
                findings,
                kind="oauthScopes",
                value=scope,
                label=label,
                category="scope",
                confidence=confidence,
                reason="OAuth scope string detected.",
                evidence=_evidence(path, line_number, line, scope),
            )


def _is_extension_manifest(source_file: SourceFile) -> bool:
    """Report whether a file is a WebExtension manifest.

    Three different files are called manifest.json -- a WebExtension manifest, a
    web app manifest, and whatever a project chose to name that way -- and only
    the first holds permissions. `manifest_version` is required in it and absent
    from the others, which is why the name alone is not enough: a web app
    manifest carrying `"display": "standalone"` would otherwise be read for
    permission strings it does not have.
    """
    if source_file.path.rsplit("/", 1)[-1].casefold() != "manifest.json":
        return False
    return bool(EXTENSION_MANIFEST_RE.search(source_file.content))


def _scan_browser_permissions(
    findings: dict[tuple[str, str], Finding],
    path: str,
    line_number: int,
    line: str,
    *,
    extension_manifest: bool,
) -> None:
    """Collect what the code asks the reader's browser for.

    Separate from `accessRights` and `oauthScopes`, which are about what a tool
    asks the *wiki* for. A gadget granted `editpage` has the community's answer
    to a question the community asked; a gadget calling `getUserMedia` has an
    answer only the individual reader can give, and gets asked for it at the
    moment the gadget runs. Both belong in a report about permissions, and
    folding them together would put a wiki right and a camera prompt under one
    heading where neither reads correctly.

    The manifest family is gated on the file, because its evidence is bare
    strings: `"tabs"` means a permission inside a WebExtension manifest and
    means nothing anywhere else.
    """
    _scan_rules(
        findings, path, line_number, line, BROWSER_PERMISSION_RULES, kind="browserPermissions", category="web-api"
    )
    directive = USER_SCRIPT_DIRECTIVE_RE.match(line)
    if directive:
        name, requested = directive.group(1), directive.group(2)
        # `@grant none` is the directive that asks for nothing. Recording it as
        # a permission would invert what the script said about itself.
        if requested.casefold() != "none":
            label, confidence, reason = USER_SCRIPT_DIRECTIVE_LABELS[name]
            _put(
                findings,
                kind="browserPermissions",
                value=f"{name}:{requested}",
                label=f"{label}: {requested}",
                category="user-script",
                confidence=confidence,
                reason=reason,
                evidence=_evidence(path, line_number, line, directive.group(0).strip()),
            )
    if not extension_manifest:
        return
    for name in WEB_EXTENSION_PERMISSION_RE.findall(line):
        label, confidence = WEB_EXTENSION_PERMISSIONS[name]
        _put(
            findings,
            kind="browserPermissions",
            value=f"extension:{name}",
            label=label,
            category="extension",
            confidence=confidence,
            reason=f"WebExtension manifest declares the {name} permission.",
            evidence=_evidence(path, line_number, line, name),
        )
    for host in EXTENSION_HOST_MATCH_RE.findall(line):
        every_site = host in EXTENSION_ALL_HOSTS
        _put(
            findings,
            kind="browserPermissions",
            value=f"host:{host}",
            label="Runs on every site" if every_site else f"Runs on {host}",
            category="extension",
            confidence=0.9 if every_site else 0.8,
            reason="WebExtension manifest declares a host match pattern.",
            evidence=_evidence(path, line_number, line, host),
        )


def _css_remote_host(reference: str) -> str:
    """Return the host a stylesheet reference points at, or "" if it names none."""
    _scheme, _slashes, rest = reference.partition("//")
    host = rest.split("/", 1)[0].split("@")[-1].split(":", 1)[0].strip().lower()
    return host if source_endpoints.HOSTNAME_RE.match(host) else ""


def _scan_stylesheet(findings: dict[tuple[str, str], Finding], path: str, line_number: int, line: str) -> None:
    """Record the third-party hosts one line of CSS makes the reader's browser fetch.

    A warning rather than an endpoint, and deliberately. The endpoint bucket
    answers "what does this tool talk to", and its static-asset filter keeps
    interface icons out of that answer for good reason. This asks something
    else: whose server learns a reader's address because a page they opened
    happened to load this stylesheet. No script runs, nobody clicked, and on a
    gadget declared `default` it happens for every reader on every page.

    Wikimedia hosts are silent. upload.wikimedia.org and the CDN are the same
    estate the reader is already on, so naming them would bury the one host
    that is not.
    """
    for match in CSS_REMOTE_REF_RE.finditer(line):
        host = _css_remote_host(match.group(1))
        if not host or source_endpoints.family(host) != source_endpoints.FAMILY_EXTERNAL:
            continue
        _put(
            findings,
            kind="warnings",
            value="stylesheet-third-party-request",
            label="Stylesheet loads resources from a third-party host",
            category="privacy",
            confidence=0.85,
            reason=f"A stylesheet fetches from {host}, so every reader's address reaches it without a script running.",
            evidence=_evidence(path, line_number, line, host),
        )


def _scan_warnings(findings: dict[tuple[str, str], Finding], path: str, line_number: int, line: str) -> None:
    match = CREDENTIAL_RE.search(line)
    if match:
        _put(
            findings,
            kind="warnings",
            value="credential-like-source",
            label="Credential-looking value in source",
            category="privacy",
            confidence=0.8,
            reason="A credential-like assignment was detected and redacted from evidence.",
            evidence=_evidence(path, line_number, line, match.group(0).split("=", 1)[0]),
        )


def _finding_rank(finding: Finding) -> tuple[float, int, int, tuple[float, int, str], str]:
    """Rank a finding for the per-bucket cap, the one most worth keeping first.

    Confidence decides first, and on most repositories it decides everything. But
    confidence is computed from a small set of ingredients, so a repository that
    names many addresses the same way produces a long block of findings that score
    identically -- on pageviews, thirty of them at 0.74 -- and the cap of forty falls
    inside that block. Sorting the block by label let the alphabet choose which half
    survived, and it chose badly: the tool's own API surface, the
    `wikimedia.org/api/rest_v1/metrics/*` calls its charts are built from, sorted
    below self-referential `pageviews.*` links copied out of the landing pages, and
    was cut.

    So the block is ordered by what is known about each finding beyond its score.
    First how many separate files said it, then how many times in total: a finding
    two files agree on is better attested than one a single generated table repeats.
    What settles the rest is where the best sighting came from, by the same reading
    rank that decided which files were worth opening at all. A finding read out of
    the code the tool is made of outranks one read out of a page describing the tool,
    and the ranking that chose the files now also chooses among what they said. The
    label remains the last resort, so two runs over one tree agree.

    The rank reads the finding rather than its payload because the payload rounds
    confidence to two places and keeps only the first few pieces of evidence. Ranking
    the rounded form invents ties that do not exist, and then breaks them without the
    evidence that would have settled them.
    """
    paths = {str(evidence["path"]) for evidence in finding.evidence}
    return (
        -finding.confidence,
        -len(paths),
        -len(finding.evidence),
        min(source_reading_rank(path) for path in paths),
        finding.label,
    )


def _serialized(findings: dict[tuple[str, str], Finding], kind: str) -> list[dict[str, Any]]:
    ranked = sorted(
        (finding for (finding_kind, _), finding in findings.items() if finding_kind == kind),
        key=_finding_rank,
    )
    return [finding.payload() for finding in ranked[:MAX_FINDINGS_PER_BUCKET]]


def _is_corroborated(item: dict[str, Any]) -> bool:
    """Whether one finding has enough support to leave the report.

    Confidence alone was the only gate on the publication boundary, and
    confidence is a property of how a rule fired rather than of how much of the
    repository agrees. A rule misfiring on a common idiom produced findings that
    cleared the threshold comfortably -- every one of the seven non-wikis this
    analyzer used to publish sat above it.

    Two ways to qualify. Either the finding is written in a file whose class
    makes it a declaration about the tool -- a manifest, a lockfile, or the
    tool's own runtime, frontend or config source -- in which case one sighting
    is a statement and needs no second opinion. Or it appears in more than one
    file, which is what agreement looks like for the softer classes where a
    single mention may be prose, a comment or an example.

    This gates the suggestion boundary only. The findings buckets keep
    everything they found, with their evidence, and the assessments keep scoring
    from the full set -- a caller reading the report still sees the single
    mention, it just does not become a value on their catalogue record.
    """
    if float(item.get("maxSourceWeight") or 0) >= PUBLICATION_TRUSTED_SOURCE_WEIGHT:
        return True
    return int(item.get("fileCount") or 1) > 1


def _corroborated_rows(
    rows: list[dict[str, Any]], min_confidence: float = EVOLVED_METADATA_MIN_CONFIDENCE
) -> list[dict[str, Any]]:
    return [row for row in _publishable_rows(rows, min_confidence) if _is_corroborated(row)]


def _tool_type_suggestion(
    technology: list[dict[str, Any]],
    apis: list[dict[str, Any]],
    source_label: str = "",
    wiki_kind: str = "",
) -> str | None:
    """Suggest a toolinfo tool type from what the source is, then what it uses.

    Neither wiki type is inferred from code here, because neither has to be.
    A user script is settled by its namespace -- `User:Someone/foo.js` is one,
    and nothing can disagree. A gadget is settled by `MediaWiki:Gadgets-definition`
    listing its files, which is a lookup rather than a judgement. Where a fact
    is on file somewhere, this reads it instead of estimating it.

    The corollary is what fixed the first bug here: a checkout that is not one
    of those pages cannot be either type, however much MediaWiki JavaScript it
    contains. A gadget is code a wiki serves; a git repository is not a wiki.

    `wiki_kind` is that lookup's answer, supplied by whoever fetched the
    definition page. Without it a gadget-namespace URL is only KIND_GADGET_PAGE,
    which has no toolinfo term -- the second bug here, and the reason the
    parameter exists: the title spells a gadget's convention, not its
    registration, and a retired gadget keeps the title it was retired under.

    Either way a wiki page returns whatever its kind maps to and stops. It never
    falls through to the technology heuristics below, which read a checkout: a
    page that is not a gadget is a wiki page of unestablished kind, not a Flask
    application that happens to live in the MediaWiki namespace.
    """
    page = wiki_sources.wiki_source(source_label)
    if wiki_kind or page is not None:
        return WIKI_KIND_TOOL_TYPE.get(wiki_kind or (page.kind if page else ""))
    tech_values = {str(item.get("value")) for item in technology}
    api_values = {str(item.get("value")) for item in apis}
    if tech_values & {"Flask", "Django", "React", "Node.js", "Vue"}:
        return "web app"
    if "Pywikibot" in tech_values and api_values & {"mediawiki-action-api", "wikibase-api"}:
        return "bot"
    return None


def _add_cross_file_warnings(findings: dict[tuple[str, str], Finding], report: dict[str, Any]) -> None:
    access = report["accessRights"]
    auth = report["authentication"]
    warning_evidence = {
        "path": "analysis",
        "line": 0,
        "match": "cross-file",
        "excerpt": "Derived from aggregated source-analysis findings.",
    }
    if _has_category(access, "administrator", SCORING_MIN_CONFIDENCE):
        _put(
            findings,
            kind="warnings",
            value="administrator-actions",
            label="Administrator or suppressive actions detected",
            category="review",
            confidence=0.86,
            reason="Source references actions that usually require elevated wiki rights.",
            evidence=warning_evidence,
        )
    if _has_write_access(access, SCORING_MIN_CONFIDENCE) and not _publishable_rows(auth, SCORING_MIN_CONFIDENCE):
        _put(
            findings,
            kind="warnings",
            value="write-without-auth-signal",
            label="Write actions without an authentication signal",
            category="review",
            confidence=0.74,
            reason="Write actions were detected, but OAuth, bot-password, or token handling was not.",
            evidence=warning_evidence,
        )


def _clean_context_list(value: object) -> list[str]:
    rows = value if isinstance(value, list | tuple | set) else [value]
    cleaned = [_clean_context_string(item) for item in rows]
    return sorted({item for item in cleaned if item})[:MAX_CONTEXT_LIST_ITEMS]


def _clean_context_value(value: object) -> str | int | bool | list[str] | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, list | tuple | set):
        return _clean_context_list(value)
    return _clean_context_string(value)


def _clean_context_object(value: object, allowed_keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    cleaned: dict[str, Any] = {}
    for key in sorted(allowed_keys):
        cleaned_value = _clean_context_value(value.get(key))
        if cleaned_value not in (None, [], ""):
            cleaned[key] = cleaned_value
    return cleaned


def _normalize_repository_context(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        message = "repositoryContext must be an object"
        raise SourceAnalysisError(message)
    repository = _clean_context_object(value.get("repository"), REPOSITORY_CONTEXT_REPOSITORY_KEYS)
    declared = _clean_context_object(value.get("declared"), REPOSITORY_CONTEXT_DECLARED_KEYS)
    maintainers = _clean_context_object(value.get("maintainers"), REPOSITORY_CONTEXT_MAINTAINER_KEYS)
    lifecycle = _clean_context_object(value.get("lifecycle"), REPOSITORY_CONTEXT_LIFECYCLE_KEYS)
    result: dict[str, Any] = {}
    if repository:
        result["repository"] = repository
    if declared:
        result["declared"] = declared
    if maintainers:
        result["maintainers"] = maintainers
    if lifecycle:
        result["lifecycle"] = lifecycle
    return result


def _context_item(kind: str, path: str) -> dict[str, str]:
    return {"kind": kind, "path": path, "sourceClass": _source_class(path)}


def _documentation_kind(path: str) -> str | None:
    name = path.rsplit("/", 1)[-1].lower()
    if name in DOCUMENTATION_FILE_KINDS:
        return DOCUMENTATION_FILE_KINDS[name]
    if name.startswith("readme."):
        return "readme"
    if name.startswith("license."):
        return "license"
    return None


def _ci_kind(path: str) -> str | None:
    normalized = path.lower()
    name = normalized.rsplit("/", 1)[-1]
    if normalized.startswith(".github/workflows/") and _suffix(normalized) in {".yaml", ".yml"}:
        return "github-actions"
    return CI_FILE_KINDS.get(normalized) or CI_FILE_KINDS.get(name)


def _runtime_kind(path: str) -> str | None:
    normalized = path.lower()
    name = normalized.rsplit("/", 1)[-1]
    if normalized.startswith(".toolforge/") or "/.toolforge/" in normalized:
        return "toolforge"
    return RUNTIME_FILE_KINDS.get(name)


def _test_kind(path: str) -> str | None:
    normalized = path.lower()
    name = normalized.rsplit("/", 1)[-1]
    if normalized.startswith("tests/") or "/tests/" in normalized:
        return "test-suite"
    if re.search(r"(?:^test_|_test\.|\.test\.|\.spec\.)", name):
        return "test-file"
    return None


def _line_match_item(kind: str, source_file: SourceFile, pattern: re.Pattern[str]) -> dict[str, Any] | None:
    for line_number, line in enumerate(source_file.content.splitlines() or [""], start=1):
        match = pattern.search(line)
        if match:
            source_class = _source_class(source_file.path)
            return {
                "kind": kind,
                "path": source_file.path,
                "line": line_number,
                "match": match.group(0)[:80],
                "sourceClass": source_class,
                "sourceWeight": SOURCE_CLASS_WEIGHTS.get(source_class, SOURCE_CLASS_WEIGHTS["unknown"]),
            }
    return None


def _sorted_context_items(index: dict[tuple[str, str], dict[str, Any]]) -> list[dict[str, Any]]:
    return [index[key] for key in sorted(index)[:MAX_CONTEXT_LIST_ITEMS]]


def _extension_counts(files: list[SourceFile]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for source_file in files:
        extension = _suffix(source_file.path) or source_file.path.rsplit("/", 1)[-1].lower()
        counts[extension] = counts.get(extension, 0) + 1
    return [{"extension": key, "count": counts[key]} for key in sorted(counts)]


def _top_level_directories(files: list[SourceFile]) -> list[str]:
    roots = {source_file.path.split("/", 1)[0] for source_file in files if "/" in source_file.path}
    return sorted(roots)[:MAX_CONTEXT_LIST_ITEMS]


def _source_class_counts(files: list[SourceFile]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for source_file in files:
        source_class = _source_class(source_file.path)
        counts[source_class] = counts.get(source_class, 0) + 1
    return [
        {"class": key, "count": counts[key], "weight": SOURCE_CLASS_WEIGHTS.get(key, SOURCE_CLASS_WEIGHTS["unknown"])}
        for key in sorted(counts)[:MAX_SOURCE_CLASS_ITEMS]
    ]


def _dependency_source_context(report: dict[str, Any]) -> dict[str, Any]:
    categories: dict[str, int] = {}
    ecosystems: set[str] = set()
    for item in report["dependencies"]:
        category = str(item.get("category") or "detected")
        categories[category] = categories.get(category, 0) + 1
        value = str(item.get("value") or "")
        if ":" in value:
            ecosystems.add(value.split(":", 1)[0])
    return {
        "count": len(report["dependencies"]),
        "ecosystems": sorted(ecosystems),
        "categories": [{"category": key, "count": categories[key]} for key in sorted(categories)],
    }


def _file_context_items(source_file: SourceFile) -> list[tuple[str, str, dict[str, Any]]]:
    path = source_file.path
    name = path.rsplit("/", 1)[-1].lower()
    direct_items = (
        ("documentation", _documentation_kind(path)),
        ("manifests", _manifest_kind(path)),
        ("lockfiles", LOCKFILE_KINDS.get(name)),
        ("ci", _ci_kind(path)),
        ("runtime", _runtime_kind(path)),
        ("tests", _test_kind(path)),
    )
    rows = [(section, str(kind), _context_item(str(kind), path)) for section, kind in direct_items if kind is not None]
    matched_items = (
        ("health", _line_match_item("health-endpoint", source_file, HEALTH_SIGNAL_RE)),
        ("accessibility", _line_match_item("accessibility-signal", source_file, A11Y_SIGNAL_RE)),
    )
    rows.extend((section, str(item["kind"]), item) for section, item in matched_items if item is not None)
    return rows


def _empty_repository_context_indexes() -> dict[str, dict[tuple[str, str], dict[str, Any]]]:
    return {
        key: {}
        for key in ("documentation", "manifests", "lockfiles", "ci", "runtime", "tests", "health", "accessibility")
    }


def _repository_context_from_files(
    files: list[SourceFile], report: dict[str, Any], repository_context: object
) -> dict[str, Any]:
    external = _normalize_repository_context(repository_context)
    indexes = _empty_repository_context_indexes()
    for source_file in files:
        for section, kind, item in _file_context_items(source_file):
            indexes[section][(kind, source_file.path)] = item
    context: dict[str, Any] = {
        "schemaVersion": 1,
        "inventory": {
            "filesAnalyzed": len(files),
            "byExtension": _extension_counts(files),
            "bySourceClass": _source_class_counts(files),
            "topLevelDirectories": _top_level_directories(files),
        },
        "documentation": _sorted_context_items(indexes["documentation"]),
        "manifests": _sorted_context_items(indexes["manifests"]),
        "lockfiles": _sorted_context_items(indexes["lockfiles"]),
        "ci": _sorted_context_items(indexes["ci"]),
        "runtime": _sorted_context_items(indexes["runtime"]),
        "tests": _sorted_context_items(indexes["tests"]),
        "health": _sorted_context_items(indexes["health"]),
        "accessibility": _sorted_context_items(indexes["accessibility"]),
        "dependencySources": _dependency_source_context(report),
    }
    context.update(external)
    maintenance = _repository_maintenance_context(context.get("repository"))
    if maintenance:
        context["maintenance"] = maintenance
    maintainer_activity = _maintainer_activity_context(context.get("maintainers"), context.get("repository"))
    if maintainer_activity:
        context["maintainerActivity"] = maintainer_activity
    return context


def _last_commit_age_days(repository: dict[str, Any]) -> int | None:
    provided_age = _int_context_value(repository.get("lastCommitAgeDays"))
    if provided_age is not None:
        return max(0, provided_age)
    last_commit = _parse_iso_datetime(repository.get("lastCommitAt"))
    analyzed_at = _parse_iso_datetime(repository.get("analyzedAt"))
    if last_commit is None or analyzed_at is None:
        return None
    return max(0, (analyzed_at - last_commit).days)


def _activity_status(age_days: int | None, *, archived: bool = False) -> str:
    # Archived outranks age and is terminal. An archived repository is
    # read-only, so its commit age measures the archive flag rather than
    # neglect -- running the recency ladder on it would score our own
    # observation. Only repositories have this; _maintainer_status describes a
    # person, and a person cannot be archived.
    if archived:
        return "archived"
    if age_days is None:
        return "unknown"
    if age_days <= ACTIVE_REPOSITORY_DAYS:
        return "active"
    if age_days <= QUIET_REPOSITORY_DAYS:
        return "quiet"
    if age_days <= STALE_REPOSITORY_DAYS:
        return "stale"
    return "dormant"


def _repository_maintenance_context(repository: object) -> dict[str, Any]:
    if not isinstance(repository, dict) or not repository:
        return {}
    age_days = _last_commit_age_days(repository)
    archived = repository.get("archived") is True
    status = _activity_status(age_days, archived=archived)
    contributor_count = _int_context_value(repository.get("contributorCount"))
    commit_count = _int_context_value(repository.get("commitCount"))
    signals: list[dict[str, Any]] = []
    # First, because it is the fact that decides the status and the signal list
    # is truncated to MAX_ASSESSMENT_SIGNALS.
    if archived:
        signals.append({"kind": "archived", "value": True})
    if age_days is not None:
        signals.append({"kind": "last-commit-age", "value": age_days, "unit": "days"})
    if contributor_count is not None:
        signals.append({"kind": "contributor-count", "value": contributor_count})
    if commit_count is not None:
        signals.append({"kind": "commit-count", "value": commit_count})
    if repository.get("dirty") is True:
        signals.append({"kind": "dirty-checkout", "value": True})
    return {
        "status": status,
        # Archived is deliberately not stale. Stale means work was expected and
        # did not arrive; archived means no work is expected at all, so the
        # outreach paths keyed on this flag must not fire.
        "stale": status in {"stale", "dormant"},
        "archived": archived,
        "lastCommitAgeDays": age_days,
        "contributorCount": contributor_count,
        "commitCount": commit_count,
        "signals": signals[:MAX_ASSESSMENT_SIGNALS],
    }


def _suggestions(report: dict[str, Any]) -> dict[str, Any]:
    projects = [item["value"] for item in _corroborated_rows(report["projects"], PROJECT_SUGGESTION_MIN_CONFIDENCE)]
    technology_rows = _corroborated_rows(report["technology"], TECHNOLOGY_SUGGESTION_MIN_CONFIDENCE)
    technology = [item["value"] for item in technology_rows]
    apis = _corroborated_rows(report["apis"])
    wiki_page = report.get("wikiPage")
    wiki_kind = str(wiki_page.get("kind") or "") if isinstance(wiki_page, dict) else ""
    tool_type = _tool_type_suggestion(technology_rows, apis, str(report.get("sourceLabel") or ""), wiki_kind)
    access_rights = _corroborated_rows(report["accessRights"])
    dependencies = _corroborated_rows(report["dependencies"])
    oauth_scopes = _corroborated_rows(report["oauthScopes"])
    warnings = _corroborated_rows(report["warnings"])
    toolinfo_patch: dict[str, Any] = {}
    if projects:
        toolinfo_patch["for_wikis"] = projects[:50]
    if technology:
        toolinfo_patch["technology_used"] = technology[:20]
    if tool_type:
        toolinfo_patch["tool_type"] = tool_type
    return {
        "toolinfoPatch": toolinfo_patch,
        "evolvedMetadata": {
            "apis": [item["value"] for item in apis],
            "access_rights": [item["value"] for item in access_rights],
            "assessment_scores": {item["key"]: item["score"] for item in report.get("assessments", [])},
            "dependencies": [item["value"] for item in dependencies],
            "health_core": report.get("healthCore", {}),
            "health_score": report.get("summary", {}).get("healthScore", 0),
            "health_confidence": report.get("summary", {}).get("healthConfidence", 0),
            "maintainer_status": report.get("summary", {}).get("maintainerStatus", "unknown"),
            "maintenance_status": report.get("summary", {}).get("maintenanceStatus", "unknown"),
            "stewardship_status": report.get("summary", {}).get("stewardshipStatus", "needs-context"),
            "oauth_scopes": [item["value"] for item in oauth_scopes],
            "warnings": [item["value"] for item in warnings],
        },
    }


def _gadget_scope_options(entry: wiki_sources.GadgetEntry) -> list[str]:
    """Return the declared options that narrow where this gadget loads.

    Option names rather than their values, because the values are namespace
    numbers and skin keys that mean nothing outside the wiki, while the fact
    that a limit exists at all is what stops `default` from being read as
    "every reader". Reported in the vocabulary's order so two gadgets with the
    same limits produce the same list.
    """
    return [option for option in GADGET_SCOPE_OPTIONS if entry.has(option)]


def _declared_rights(entry: wiki_sources.GadgetEntry) -> list[str]:
    """Return the rights `rights=` names, lowercased, deduplicated, in order."""
    named = (raw.strip().lower() for raw in entry.values(GADGET_RIGHTS_OPTION))
    return list(dict.fromkeys(right for right in named if right))


def _unknown_declared_rights(entry: wiki_sources.GadgetEntry) -> list[str]:
    """Return the declared rights GADGET_RIGHT_VOCABULARY has never seen.

    GADGET_RIGHT_VOCABULARY is a measurement -- twenty-one rights, read off five
    definition pages on one day -- and wikis add rights and gadgets change what
    they gate on. Nothing re-measured it, so its accuracy could only decay
    silently. This is the number that says when: every entry here is a right
    the table was built without, so a rate that used to be zero and is not any
    more says the pages have moved on and the vocabulary should be read again.
    """
    return [right for right in _declared_rights(entry) if right not in GADGET_RIGHT_VOCABULARY]


def _wiki_page_row(
    page: wiki_sources.WikiSource | None,
    declaration: wiki_sources.GadgetDeclaration | None = None,
) -> dict[str, object]:
    """Render the resolved source page for the report, or {} when there is none.

    The three gadget fields ride here rather than in a findings bucket because
    none of them is a permission: together they say how far the gadget reaches,
    which changes how much every other finding matters without being one itself.
    `gadgetDefault` is whether readers get it without asking, `gadgetHidden`
    whether they can turn it off in preferences, and `gadgetScope` the limits
    that keep `default` from meaning the whole wiki.

    `gadgetRights` and `gadgetUnknownRights` are here for a different reason:
    they are this report's contribution to a measurement about the analyzer
    rather than about the tool. The rights are already reported as findings, but
    a finding cannot say what share of the declared rights the vocabulary could
    describe, and that share is the only signal that GADGET_RIGHT_VOCABULARY has
    fallen behind the wikis. Both lists carry raw names, because a name the
    table cannot translate is exactly what has to be read back.

    Every field is absent rather than false or empty when no definition line was
    read, so "not measured" and "declared opt-in" stay distinguishable.
    """
    if page is None:
        return {}
    row: dict[str, object] = {"domain": page.domain, "title": page.title, "kind": page.kind}
    if declaration is not None:
        row["gadgetDefault"] = declaration.entry.has(GADGET_DEFAULT_OPTION)
        row["gadgetHidden"] = declaration.entry.has(GADGET_HIDDEN_OPTION)
        row["gadgetScope"] = _gadget_scope_options(declaration.entry)
        row["gadgetRights"] = _declared_rights(declaration.entry)
        row["gadgetUnknownRights"] = _unknown_declared_rights(declaration.entry)
    return row


def _wiki_page_strings(row: object, key: str) -> list[str]:
    """Return one list of names off the wikiPage row, or [] when it has none."""
    if not isinstance(row, dict):
        return []
    values = row.get(key)
    return [str(item) for item in values] if isinstance(values, list) else []


def analyze_source_files(  # noqa: PLR0913 - each argument is a separate thing the caller knows;
    # bundling them into one object would make every call site build a record to pass through.
    files: object,
    *,
    tool_name: str | None = None,
    source_label: str | None = None,
    wiki_page: wiki_sources.WikiSource | None = None,
    gadget_declaration: wiki_sources.GadgetDeclaration | None = None,
    repository_context: object = None,
) -> dict[str, Any]:
    """Analyze source files and return metadata suggestions with evidence.

    `wiki_page` is the source page as the fetcher resolved it, and matters for
    one thing: whether a `MediaWiki:Gadget-*` page was found in the definition
    page. Callers that did not fetch one omit it, and get no gadget suggestion
    rather than one taken from the title.

    `gadget_declaration` is the definition line that registered it, when there
    was one. It is passed rather than re-derived because acquisition is the only
    step that reads the definition page, and asking for it again here would be a
    second fetch of a document already in hand.
    """
    # The wider ceiling is keyed on wiki_page rather than on a caller-supplied
    # limit so it cannot be asked for: only _acquire_wiki sets it, and the HTTP
    # route and the CLI both omit it, leaving them on the checkout cap.
    normalized = _normalize_source_files(files, max_file_bytes=MAX_WIKI_FILE_BYTES if wiki_page else MAX_FILE_BYTES)
    findings: dict[tuple[str, str], Finding] = {}
    local_python_roots = _local_python_import_roots(normalized)
    for source_file in normalized:
        _scan_manifest_dependencies(findings, source_file)
        # A lockfile is a resolved dependency graph with a registry URL on
        # nearly every line. Those registries belong to the package manager,
        # not to the tool, and the dependency scanner has already read this
        # same file for the part of it that is about the tool. Its 0.95 weight
        # would otherwise make npmjs.org one of the loudest endpoints found.
        source_class = _source_class(source_file.path)
        # A lockfile is a list of registry mirrors and the tool calls none of
        # them, so it is skipped outright. Anywhere else the addresses are worth
        # reading; whether they are worth believing on their own depends on the
        # file, and that decision is per file rather than per line.
        wants_endpoints = source_class != "lockfile"
        endpoints_need_a_call = SOURCE_CLASS_WEIGHTS[source_class] < ENDPOINT_TRUSTED_SOURCE_WEIGHT
        extension_manifest = _is_extension_manifest(source_file)
        stylesheet = source_file.path.lower().endswith(CSS_SUFFIX)
        for line_number, raw_line in enumerate(source_file.content.splitlines() or [""], start=1):
            line = _bounded_line(raw_line)
            if wants_endpoints:
                _scan_endpoints(findings, source_file.path, line_number, line, require_call=endpoints_need_a_call)
            _scan_projects(findings, source_file.path, line_number, line)
            _scan_rules(findings, source_file.path, line_number, line, API_RULES, kind="apis")
            _scan_rules(findings, source_file.path, line_number, line, AUTH_RULES, kind="authentication")
            _scan_technology(findings, source_file.path, line_number, line)
            _scan_import_dependencies(findings, source_file.path, line_number, line, local_python_roots)
            _scan_actions(findings, source_file.path, line_number, line)
            _scan_oauth_scopes(findings, source_file.path, line_number, line)
            _scan_browser_permissions(
                findings, source_file.path, line_number, line, extension_manifest=extension_manifest
            )
            _scan_warnings(findings, source_file.path, line_number, line)
            if stylesheet:
                _scan_stylesheet(findings, source_file.path, line_number, line)
    if gadget_declaration is not None:
        _scan_gadget_declaration(findings, gadget_declaration)
    _reconcile_technology_packages(findings)
    report: dict[str, Any] = {
        "toolName": tool_name or "",
        "sourceLabel": source_label or "",
        # Recorded, not just consumed: the type suggestion below turns on it,
        # and a stored report should show what that decision was made from.
        "wikiPage": _wiki_page_row(wiki_page, gadget_declaration),
        "filesAnalyzed": len(normalized),
        "projects": _serialized(findings, "projects"),
        "apis": _serialized(findings, "apis"),
        "accessRights": _serialized(findings, "accessRights"),
        "authentication": _serialized(findings, "authentication"),
        "dependencies": _serialized(findings, "dependencies"),
        "endpoints": _serialized(findings, "endpoints"),
        "oauthScopes": _serialized(findings, "oauthScopes"),
        "browserPermissions": _serialized(findings, "browserPermissions"),
        "technology": _serialized(findings, "technology"),
        "warnings": _serialized(findings, "warnings"),
    }
    _add_cross_file_warnings(findings, report)
    report["warnings"] = _serialized(findings, "warnings")
    report["repositoryContext"] = _repository_context_from_files(normalized, report, repository_context)
    report["assessments"] = _assessments(report, report["repositoryContext"])
    report["healthCore"] = _health_core(report["assessments"], report["repositoryContext"])
    report["summary"] = {
        "filesAnalyzed": len(normalized),
        "projectCount": len(report["projects"]),
        "apiCount": len(report["apis"]),
        "accessRightCount": len(report["accessRights"]),
        "dependencyCount": len(report["dependencies"]),
        "endpointCount": len(report["endpoints"]),
        # Split out because the two halves answer different questions. Wikimedia
        # endpoints describe what a tool does; a third-party one is a dependency
        # on something nobody in the movement operates, which is the number a
        # reviewer is actually looking for.
        "externalEndpointCount": _external_endpoint_count(report["endpoints"]),
        "oauthScopeCount": len(report["oauthScopes"]),
        "browserPermissionCount": len(report["browserPermissions"]),
        "technologyCount": len(report["technology"]),
        "warningCount": len(report["warnings"]),
        "writeActionsDetected": _has_write_access(report["accessRights"], SCORING_MIN_CONFIDENCE),
        # A count and its denominator, not a verdict on this tool. Stored on
        # every report so the share of declared rights this analyzer cannot
        # describe is one query away, instead of a re-reading of the five
        # definition pages nobody schedules.
        "declaredRightCount": len(_wiki_page_strings(report["wikiPage"], "gadgetRights")),
        "unknownDeclaredRightCount": len(_wiki_page_strings(report["wikiPage"], "gadgetUnknownRights")),
        **_assessment_summary(report["assessments"]),
        **_health_summary(report["healthCore"]),
    }
    report["suggestions"] = _suggestions(report)
    return report
