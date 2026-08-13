# Toolhub Discovery Implementation Plan — Phase 1: Facet Index

> **For Claude:** REQUIRED SUB-SKILL: Use ed3d-plan-and-execute:executing-an-implementation-plan to implement this plan task-by-task.

**Goal:** Make the analyzer signals already collected in `SourceAnalysisReport` JSON (dependencies, Wikimedia APIs, detected technologies) queryable via a `ToolSignalFacet` table.

**Architecture:** New `tool_signal_facets` table; pure extraction functions in a new `proxy/backend/tool_facets.py`; idempotent backfill wired into `proxy/migrate.py`; incremental updates hooked into the hourly `proxy/repository_scan.py` job. Declared metadata (`tool_type`, keywords, license…) is deliberately NOT stored here — `catalog_facet_values` already indexes it from the effective merged record.

**Tech Stack:** Python 3.11+/3.13, Flask 3, SQLAlchemy 2 (Mapped/mapped_column style), pytest with in-memory SQLite (`db.configure("sqlite://")`, `db.init_schema()`).

**Scope:** Phase 1 of 5 from `docs/design-plans/2026-08-13-toolhub-discovery.md`.

**Codebase verified:** 2026-08-13 (two codebase-investigator passes + targeted reads).

---

## Verified facts this phase relies on

(Repeated here because the executor must not re-derive them wrong.)

- `SourceAnalysisReport` is at `proxy/backend/models.py:1056-1071`; the `report` JSON column's shape is built at `proxy/backend/source_analyzer.py:2801-2832`. Relevant top-level keys: `"dependencies"`, `"apis"`, `"technology"` — each a list of finding payloads with keys `value`, `label`, `kind`, `category`, `confidence`, `maxSourceWeight`, `reasons`, `sourceClasses`, `evidence`.
- Dependency `value` format is `"{ecosystem}:{name.lower()}"`; ecosystems emitted: `npm`, `pypi`, `composer`, `cargo`, `go`, `rubygems`.
- API detector `value` strings (complete list, from `API_RULES` at `source_analyzer.py:339-382`): `mediawiki-action-api`, `wikibase-api`, `wikidata-query-service`, `mediawiki-rest-api`, `toolforge`, `commons-upload`.
- Technology findings: `value` is the technology name (e.g. `"Python"`); `category` is `"language"` or `"framework"`.
- `CanonicalToolCache` (`proxy/backend/models.py:123-156`): PK `tool_name`, JSON `record`.
- **`CatalogFacetValue` already exists and owns all DECLARED-metadata facets** (`models.py:333-346`, populated by `catalog_projection._replace_facets` at `catalog_projection.py:355-378`, refreshed by the hourly `catalog-projection` job in `jobs.yaml:110-116`; verified populated in production 2026-08-13). Schema `(tool_name, field, value)` unique, `value` casefolded, `label` original, plus `provenance` and `confidence_basis_points`. Its `FACET_FIELDS` (`catalog_projection.py:79-88`) cover `tool_type`, `keywords`, `wiki`, `technology` (from declared `technology_used`), `tasks`, `audiences`, `ui_language`, `license` — and it projects the **effective merged** record, including curation patches.
  **Design decision (2026-08-13, plan owner):** `ToolSignalFacet` therefore holds ONLY analyzer-derived signals that have no existing home — `dependency`, `wikimedia_api`, `detected_technology`. It does NOT store `tool_type`; discovery queries read that from `catalog_facet_values`, which has strictly better provenance. Our detected-language facet is named `detected_technology` precisely so it never collides with `CatalogFacetValue.field == "technology"`, which means something different (declared, not detected).

  **Why a second table rather than extending `catalog_facet_values`** (asked and answered 2026-08-13; the two schemas are near-identical, so this is not obvious from shape alone):
  1. **The projection is human-gated; discovery must not be.** `catalog_projection._latest_reports` (`catalog_projection.py:187-199`) consumes only reports with `review_status == REVIEW_APPROVED`, and only their `suggestions.toolinfoPatch` (`:180-184`). The hourly auto-scan writes UNREVIEWED reports. Routing discovery through the projection would silently narrow coverage from "has a scanned repo" to "has a scanned repo AND an approved report" — and the coverage number the skill quotes to users would then be wrong.
  2. **Shared writes would be clobbered.** `_replace_facets` (`catalog_projection.py:353-354`) deletes ALL rows for a tool and rebuilds from the effective record; anything we wrote there disappears on the next hourly refresh. Co-tenancy would mean field-scoping that delete — a change to a core pipeline whose failure mode is silent loss of the discovery index.
  3. **`confidence` would carry two meanings.** `confidence_basis_points` encodes SOURCE AUTHORITY (`SOURCE_CONFIDENCE`, `catalog_projection.py:89-95`: canonical 100, crawler 95, repository 75). Ours encodes DETECTION CERTAINTY (0.64 for a file-extension guess, 0.94 for a WDQS URL match). One column, two semantics, is a trap for any future `ORDER BY confidence`. Structurally too: dependencies and API usage are not toolinfo fields, and the projection's product is an effective toolinfo record.

  Accepted cost: the cross-table `INTERSECT` in Task 3b and two vocabularies to document. Both tables key on `tool_name`, so it is a set intersection, not a join.
  Note the two technology facets are complementary, not redundant: analyzer-detected technology can still reach declared `technology_used` through the existing approved-patch path, while `detected_technology` is the ungated discovery-time view.
- Schema management: SQLAlchemy `create_all` via `db.init_schema()` (schema setup plus cheap idempotent upgrades, runs per worker at startup); **row-count-proportional work must go in `proxy/migrate.py`** (see its module docstring), which `tools/deploy.sh:81` runs per deploy. Migration functions there return `int` row counts; `run_once()` (`migrate.py:70-85`) wraps them in `MigrationResult`.
- Reports are persisted in `proxy/repository_scan.py:283-295` (created + flushed; `report.id` linked to `RepositoryAnalysisState` at line 301) — the incremental hook point.
- Tests: `PYTHONPATH=proxy pytest tests/proxy -q --cov --cov-report=term-missing`; coverage ratchet `fail-under=91.7` (pyproject.toml); ruff `select = ALL` and `ruff format` are CI-enforced, so new files need SPDX header, module/class/function docstrings, and full type annotations. Match the commenting style of `models.py` (comments explain *why*, not *what*).

---

### Task 1: `ToolSignalFacet` model

**Files:**
- Modify: `proxy/backend/models.py` (add model near `SourceAnalysisReport`, ~line 1071)
- Test: `tests/proxy/test_tool_facets.py` (create)

**Step 1: Write the failing test**

Create `tests/proxy/test_tool_facets.py`:

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""Facet extraction, storage, and query behavior for tool signal facets."""

import pytest
from sqlalchemy.exc import IntegrityError

from backend import db
from backend.models import ToolSignalFacet, User, utcnow


@pytest.fixture(autouse=True)
def database():
    db.configure("sqlite://")
    db.init_schema()


def test_tool_signal_facet_roundtrip_and_uniqueness():
    with db.session_scope() as s:
        s.add(
            ToolSignalFacet(
                tool_name="sfedits",
                facet_type="dependency",
                value="pypi:pywikibot",
                confidence=0.9,
                source_report_id=1,
                updated_at=utcnow(),
            )
        )
    with db.session_scope() as s:
        row = s.query(ToolSignalFacet).one()
        assert row.tool_name == "sfedits"
        assert row.value == "pypi:pywikibot"
    with pytest.raises(IntegrityError), db.session_scope() as s:
        s.add(
            ToolSignalFacet(
                tool_name="sfedits",
                facet_type="dependency",
                value="pypi:pywikibot",
            )
        )
```

Note: mirror the fixture idiom of `tests/proxy/test_identity_graph.py:28-31`. `db.session_scope()` re-raises the original exception unwrapped (`proxy/backend/db.py:366`), so `IntegrityError` is the correct assertion.

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=proxy pytest tests/proxy/test_tool_facets.py -q`
Expected: FAIL — `ImportError: cannot import name 'ToolSignalFacet'`

**Step 3: Write minimal implementation**

In `proxy/backend/models.py`, immediately after the `SourceAnalysisReport` class (~line 1071), add:

```python
# Facet vocabulary for ToolSignalFacet.facet_type: analyzer-DERIVED signals
# only, all rebuilt per tool from its latest SourceAnalysisReport. Declared
# metadata (tool_type, keywords, license, declared technology_used, …) is not
# here — catalog_facet_values already indexes it from the effective merged
# record, so duplicating it would create two copies that diverge on curation.
# "detected_technology" is named apart from CatalogFacetValue's "technology"
# because they mean different things: detected from source vs declared.
FACET_DEPENDENCY = "dependency"
FACET_WIKIMEDIA_API = "wikimedia_api"
FACET_DETECTED_TECHNOLOGY = "detected_technology"
FACET_TYPES = (FACET_DEPENDENCY, FACET_WIKIMEDIA_API, FACET_DETECTED_TECHNOLOGY)
# Retained name for "every type this table stores", now that they are all
# analyzer-derived; kept so call sites reading either name stay honest.
ANALYZER_FACET_TYPES = FACET_TYPES


class ToolSignalFacet(Base):
    """One queryable signal about one tool.

    SourceAnalysisReport stores the analyzer's findings as one JSON blob per
    report, which nothing can filter on in SQL. This table denormalizes the
    few finding kinds discovery queries need ("which tools depend on X", 
    "which tools call API Y") into indexed rows, one per (tool, type, value).
    """

    __tablename__ = "tool_signal_facets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tool_name: Mapped[str] = mapped_column(String(255), index=True)
    facet_type: Mapped[str] = mapped_column(String(32))
    # Normalized, casefolded value: "pypi:pywikibot", "wikidata-query-service",
    # "python", "web app". Casefolded on write so lookups never need LOWER().
    value: Mapped[str] = mapped_column(String(255))
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    # Provenance: the analysis report this row came from.
    source_report_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("tool_name", "facet_type", "value", name="uq_tool_signal_facet"),
        Index("ix_tool_signal_facets_type_value", "facet_type", "value"),
    )
```

Add `Float`, `UniqueConstraint`, and `Index` to the existing `sqlalchemy` import block at the top of `models.py` (skip any of the three already present).

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=proxy pytest tests/proxy/test_tool_facets.py -q`
Expected: PASS

**Step 5: Lint and commit**

```bash
ruff check proxy && ruff format proxy
git add proxy/backend/models.py tests/proxy/test_tool_facets.py
git commit -m "feat: add ToolSignalFacet model for queryable tool signals"
```

---

### Task 2: Facet extraction from analyzer reports

**Files:**
- Create: `proxy/backend/tool_facets.py`
- Test: `tests/proxy/test_tool_facets.py` (extend)

**Step 1: Write the failing tests**

Append to `tests/proxy/test_tool_facets.py`:

```python
from backend import tool_facets

# Shape mirrors source_analyzer.py:2801-2832 finding payloads; only the keys
# extraction reads are included.
SAMPLE_REPORT = {
    "toolName": "sfedits",
    "dependencies": [
        {"value": "pypi:pywikibot", "label": "pywikibot (pypi)", "confidence": 0.95},
        {"value": "npm:vue", "label": "vue (npm)", "confidence": 0.9},
        {"value": "pypi:pywikibot", "label": "pywikibot (pypi)", "confidence": 0.5},
    ],
    "apis": [
        {"value": "wikidata-query-service", "label": "Wikidata Query Service", "confidence": 0.94},
        {"value": "", "label": "broken", "confidence": 0.9},
    ],
    "technology": [
        {"value": "Python", "label": "Python", "confidence": 0.64},
    ],
    "warnings": [{"value": "ignored-kind", "confidence": 1.0}],
}


def test_extract_facets_normalizes_and_dedupes():
    facets = tool_facets.extract_facets(SAMPLE_REPORT)
    assert ("dependency", "pypi:pywikibot", 0.95) in facets
    assert ("dependency", "npm:vue", 0.9) in facets
    assert ("wikimedia_api", "wikidata-query-service", 0.94) in facets
    assert ("technology", "python", 0.64) in facets
    # Duplicate value keeps the highest confidence; empty values are dropped;
    # kinds outside the facet vocabulary are ignored.
    assert len([f for f in facets if f[1] == "pypi:pywikibot"]) == 1
    assert all(value for _, value, _ in facets)
    assert not [f for f in facets if f[0] == "warnings"]


def test_extract_facets_tolerates_malformed_report():
    assert tool_facets.extract_facets({}) == []
    assert tool_facets.extract_facets({"dependencies": "nope", "apis": [None, 7]}) == []
```

**Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=proxy pytest tests/proxy/test_tool_facets.py -q`
Expected: FAIL — `ImportError` (no `tool_facets` module)

**Step 3: Write the implementation**

Create `proxy/backend/tool_facets.py`:

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""Extract and maintain queryable signal facets from analysis reports.

SourceAnalysisReport.report is one JSON blob per scan; this module flattens
the finding kinds discovery needs into ToolSignalFacet rows. Extraction is a
pure function so it can be exercised without a database; storage helpers are
idempotent (replace-per-tool) so re-running any producer converges.
"""

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.models import (
    ANALYZER_FACET_TYPES,
    FACET_DEPENDENCY,
    FACET_TECHNOLOGY,
    FACET_DETECTED_TECHNOLOGY,
    FACET_WIKIMEDIA_API,
    ToolSignalFacet,
    utcnow,
)

# Report top-level key -> facet_type. Finding payload shape is defined by
# source_analyzer.py finding payloads: {"value", "confidence", ...}.
_REPORT_SECTIONS = (
    ("dependencies", FACET_DEPENDENCY),
    ("apis", FACET_WIKIMEDIA_API),
    ("technology", FACET_DETECTED_TECHNOLOGY),
)

Facet = tuple[str, str, float]


def extract_facets(report: dict[str, Any] | None) -> list[Facet]:
    """Return normalized (facet_type, value, confidence) rows for one report.

    Values are casefolded so SQL equality never needs LOWER(); duplicate
    values keep their highest confidence, since the analyzer may emit one
    finding per evidence source.
    """
    best: dict[tuple[str, str], float] = {}
    source = report if isinstance(report, dict) else {}
    for section, facet_type in _REPORT_SECTIONS:
        entries = source.get(section)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            value = str(entry.get("value") or "").strip().casefold()[:255]
            if not value:
                continue
            try:
                confidence = float(entry.get("confidence") or 0.0)
            except (TypeError, ValueError):
                confidence = 0.0
            key = (facet_type, value)
            best[key] = max(best[key], confidence) if key in best else confidence
    return [(facet_type, value, confidence) for (facet_type, value), confidence in sorted(best.items())]


def replace_analyzer_facets(
    s: Session,
    tool_name: str,
    report: dict[str, Any] | None,
    *,
    source_report_id: int | None,
) -> int:
    """Replace one tool's analyzer-derived facets with those from `report`.

    Delete-then-insert rather than diffing: a scan is the complete current
    truth for its tool, and the row count per tool is small.
    """
    clean = str(tool_name or "").strip()
    if not clean:
        return 0
    s.execute(
        delete(ToolSignalFacet).where(
            ToolSignalFacet.tool_name == clean,
            ToolSignalFacet.facet_type.in_(ANALYZER_FACET_TYPES),
        )
    )
    now = utcnow()
    facets = extract_facets(report)
    s.add_all(
        ToolSignalFacet(
            tool_name=clean,
            facet_type=facet_type,
            value=value,
            confidence=confidence,
            source_report_id=source_report_id,
            updated_at=now,
        )
        for facet_type, value, confidence in facets
    )
    return len(facets)


```

**No `set_tool_type_facet`.** An earlier draft of this plan had one; it was removed on 2026-08-13 after review found `catalog_facet_values` already stores `tool_type` from the effective merged record (see Verified facts above). Declared metadata is not this table's job.

**Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=proxy pytest tests/proxy/test_tool_facets.py -q`
Expected: PASS

**Step 5: Add storage tests, run, commit**

Append tests covering `replace_analyzer_facets` (twice with changed report → old rows gone, new present; empty tool name → 0). Then:

```bash
PYTHONPATH=proxy pytest tests/proxy/test_tool_facets.py -q
ruff check proxy && ruff format proxy
git add proxy/backend/tool_facets.py tests/proxy/test_tool_facets.py
git commit -m "feat: extract analyzer findings into tool signal facets"
```

---

### Task 3: Facet query helpers

**Files:**
- Modify: `proxy/backend/tool_facets.py`
- Test: `tests/proxy/test_tool_facets.py` (extend)

These helpers are the single query surface Phases 3 and 4 build on.

**Step 1: Write the failing tests**

```python
def _report_user(s):
    """SourceAnalysisReport.user_id is NOT NULL (models.py:1061); seed a user.

    Same pattern as tests/proxy/test_graph_enrichment.py:72-79.
    """
    user = User(wm_sub="42", username="Seeder")
    s.add(user)
    s.flush()
    return user.id


def _seed_facets():
    with db.session_scope() as s:
        # Coverage is defined as "tools with at least one analysis report",
        # so the reports themselves must exist, not just derived facets.
        uid = _report_user(s)
        s.add(SourceAnalysisReport(tool_name="sfedits", report=SAMPLE_REPORT, user_id=uid))
        s.add(
            SourceAnalysisReport(
                tool_name="cite-checker",
                report={"dependencies": [{"value": "pypi:pywikibot", "confidence": 0.8}]},
                user_id=uid,
            )
        )
        tool_facets.replace_analyzer_facets(
            s, "sfedits", SAMPLE_REPORT, source_report_id=1
        )
        tool_facets.replace_analyzer_facets(
            s,
            "cite-checker",
            {"dependencies": [{"value": "pypi:pywikibot", "confidence": 0.8}]},
            source_report_id=2,
        )


def test_tools_matching_facets_intersects_filters():
    _seed_facets()
    with db.session_scope() as s:
        both = tool_facets.tools_matching_facets(
            s, {"dependency": ["pypi:pywikibot"]}, limit=10
        )
        assert sorted(m.tool_name for m in both) == ["cite-checker", "sfedits"]
        narrowed = tool_facets.tools_matching_facets(
            s,
            {"dependency": ["pypi:pywikibot"], "wikimedia_api": ["wikidata-query-service"]},
            limit=10,
        )
        assert [m.tool_name for m in narrowed] == ["sfedits"]
        # Matched facet detail rides along for the API layer.
        assert {"facet": "dependency", "value": "pypi:pywikibot", "confidence": 0.95} in narrowed[0].matched


def test_facet_value_counts_and_coverage():
    _seed_facets()
    with db.session_scope() as s:
        counts = tool_facets.facet_value_counts(s, "dependency")
        assert counts[0] == {"value": "pypi:pywikibot", "toolCount": 2}
        assert tool_facets.facet_value_counts(s, "dependency", limit=1) == counts[:1]
        assert tool_facets.count_facet_values(s, "dependency") == len(counts)
        assert tool_facets.scanned_tool_count(s) == 2


def test_count_matching_reports_true_total():
    _seed_facets()
    with db.session_scope() as s:
        filters = {"dependency": ["pypi:pywikibot"]}
        assert tool_facets.count_matching(s, filters) == 2
        limited = tool_facets.tools_matching_facets(s, filters, limit=1)
        assert len(limited) == 1  # page smaller than the true total
        # One tool matching TWO values of one type is still one tool:
        # sfedits carries both pypi:pywikibot and npm:vue.
        both_values = {"dependency": ["pypi:pywikibot", "npm:vue"]}
        assert tool_facets.count_matching(s, both_values) == 2
        # Two-type INTERSECT path: only sfedits has the API facet too.
        two_types = {"dependency": ["pypi:pywikibot"], "wikimedia_api": ["wikidata-query-service"]}
        assert tool_facets.count_matching(s, two_types) == 1
        # An asked-for-but-empty filter must empty the result, not widen it.
        widened = {"dependency": [], "wikimedia_api": ["wikidata-query-service"]}
        assert tool_facets.count_matching(s, widened) == 0
        assert tool_facets.tools_matching_facets(s, widened, limit=10) == []
```

**Step 2: Run to verify failure** — `AttributeError` on the new names.

**Step 3: Implement**

Append to `proxy/backend/tool_facets.py`:

```python
from dataclasses import dataclass, field

from sqlalchemy import and_, func, or_, select

from backend.models import SourceAnalysisReport

MAX_FACET_RESULTS = 100


@dataclass(frozen=True)
class FacetMatch:
    """One tool matching a facet query, with the rows that matched."""

    tool_name: str
    matched: list[dict[str, Any]] = field(default_factory=list)


def tools_matching_facets(
    s: Session, filters: dict[str, list[str]], *, limit: int = MAX_FACET_RESULTS
) -> list[FacetMatch]:
    """Return tools having at least one matching value for EVERY filter type.

    Filters AND across facet types and OR within one type's value list,
    which is the "tools like mine" question: uses this library AND that API.
    """
    clean: dict[str, list[str]] = {}
    for facet_type, values in (filters or {}).items():
        wanted = sorted({str(v or "").strip().casefold() for v in values if str(v or "").strip()})
        if not wanted:
            # A filter the caller asked for that carries no known value
            # matches nothing; dropping it instead would silently widen
            # the AND across types to the remaining filters.
            return []
        clean[facet_type] = wanted
    if not clean:
        return []
    capped = max(1, min(MAX_FACET_RESULTS, int(limit or MAX_FACET_RESULTS)))

    matching = None
    for facet_type, values in clean.items():
        names = select(ToolSignalFacet.tool_name).where(
            ToolSignalFacet.facet_type == facet_type,
            ToolSignalFacet.value.in_(values),
        )
        matching = names if matching is None else matching.intersect(names)

    # Rank by the confidence of the facets that actually matched the filters,
    # not the tool's best unrelated signal.
    matched_condition = or_(
        *(
            and_(ToolSignalFacet.facet_type == facet_type, ToolSignalFacet.value.in_(values))
            for facet_type, values in clean.items()
        )
    )
    names_in_order = list(
        s.execute(
            select(ToolSignalFacet.tool_name)
            .where(ToolSignalFacet.tool_name.in_(matching), matched_condition)
            .group_by(ToolSignalFacet.tool_name)
            .order_by(func.max(ToolSignalFacet.confidence).desc(), ToolSignalFacet.tool_name)
            .limit(capped)
        ).scalars()
    )
    if not names_in_order:
        return []
    rows = s.execute(
        select(ToolSignalFacet).where(ToolSignalFacet.tool_name.in_(names_in_order), matched_condition)
    ).scalars()
    matched_by_tool: dict[str, list[dict[str, Any]]] = {name: [] for name in names_in_order}
    for row in rows:
        matched_by_tool[row.tool_name].append(
            {"facet": row.facet_type, "value": row.value, "confidence": row.confidence}
        )
    return [FacetMatch(tool_name=name, matched=sorted(matched_by_tool[name], key=str)) for name in names_in_order]


MAX_VALUE_RESULTS = 500
DEFAULT_VALUE_RESULTS = 100


def facet_value_counts(
    s: Session, facet_type: str, *, limit: int = DEFAULT_VALUE_RESULTS
) -> list[dict[str, Any]]:
    """Top values of one facet type by tool adoption.

    Bounded: `dependency` alone spans every package across six ecosystems,
    and this feeds unauthenticated responses and LLM context windows. Callers
    display "top N by adoption"; count_facet_values reports the true total.
    """
    capped = max(1, min(MAX_VALUE_RESULTS, int(limit or DEFAULT_VALUE_RESULTS)))
    rows = s.execute(
        select(ToolSignalFacet.value, func.count(func.distinct(ToolSignalFacet.tool_name)))
        .where(ToolSignalFacet.facet_type == str(facet_type or "").strip().casefold())
        .group_by(ToolSignalFacet.value)
        .order_by(func.count(func.distinct(ToolSignalFacet.tool_name)).desc(), ToolSignalFacet.value)
        .limit(capped)
    ).all()
    return [{"value": value, "toolCount": count} for value, count in rows]


def count_facet_values(s: Session, facet_type: str) -> int:
    """True number of distinct values for one facet type (for truncation info)."""
    return int(
        s.execute(
            select(func.count(func.distinct(ToolSignalFacet.value))).where(
                ToolSignalFacet.facet_type == str(facet_type or "").strip().casefold()
            )
        ).scalar()
        or 0
    )


def count_matching(s: Session, filters: dict[str, list[str]]) -> int:
    """True number of tools matching the filters, independent of page size."""
    clean: dict[str, list[str]] = {}
    for facet_type, values in (filters or {}).items():
        wanted = sorted({str(v or "").strip().casefold() for v in values if str(v or "").strip()})
        if not wanted:
            # Mirror tools_matching_facets: an asked-for filter with no
            # known value matches nothing, it does not vanish from the AND.
            return 0
        clean[facet_type] = wanted
    if not clean:
        return 0
    matching = None
    for facet_type, values in clean.items():
        names = select(ToolSignalFacet.tool_name).where(
            ToolSignalFacet.facet_type == facet_type,
            ToolSignalFacet.value.in_(values),
        )
        matching = names if matching is None else matching.intersect(names)
    # COUNT(DISTINCT ...): a tool matching two values of one type is one
    # tool. (INTERSECT dedupes on its own, but the single-filter path has no
    # INTERSECT — without DISTINCT it counts rows, not tools.)
    sub = matching.subquery()
    return int(s.execute(select(func.count(func.distinct(sub.c.tool_name)))).scalar() or 0)


def scanned_tool_count(s: Session) -> int:
    """Count tools with at least one stored analysis report (coverage basis).

    Counts reports, not facets: a scanned repository that yielded zero
    findings is still scanned, and the coverage number is what discovery
    clients repeat to users — it must not silently undercount.
    """
    return int(
        s.execute(select(func.count(func.distinct(SourceAnalysisReport.tool_name)))).scalar() or 0
    )
```

Consolidate imports at the top of the file (ruff will flag mid-file imports; move the dataclass/select imports up).

**Step 4: Run tests** — expect PASS. (`ToolSignalFacet.tool_name.in_(matching)` relies on SQLAlchemy 2.0's automatic coercion of a select into a subquery — the installed pin is `SQLAlchemy>=2.0.36`, where this is supported.) The Task 3 test block needs `SourceAnalysisReport` added to its `backend.models` import.

**Step 5: Lint and commit**

```bash
ruff check proxy && ruff format proxy
git add proxy/backend/tool_facets.py tests/proxy/test_tool_facets.py
git commit -m "feat: add facet query helpers for tool discovery"
```

---

### Task 3b: Declared-facet filters (cross-table)

**Added 2026-08-13** with the decision to keep declared metadata in `catalog_facet_values`. Discovery still has to answer "Python bots that use pywikibot", so the helpers must intersect both tables.

**Files:** `proxy/backend/tool_facets.py`, `tests/proxy/test_tool_facets.py`

**Contract:** both query helpers gain an optional keyword argument:

```python
def tools_matching_facets(
    s: Session,
    filters: dict[str, list[str]],
    *,
    declared_filters: dict[str, list[str]] | None = None,
    limit: int = MAX_FACET_RESULTS,
) -> list[FacetMatch]: ...

def count_matching(
    s: Session,
    filters: dict[str, list[str]],
    *,
    declared_filters: dict[str, list[str]] | None = None,
) -> int: ...
```

`declared_filters` keys are `CatalogFacetValue.field` values (`tool_type`, `keywords`, `wiki`, `technology`, `license`, …); values are compared against `CatalogFacetValue.value`, which is already casefolded on write (`catalog_projection.py:358-370`).

**Rules (identical semantics to the analyzer filters):**
- Declared filters AND with the analyzer filters and with each other; values within one field OR.
- The same fail-closed rule: an asked-for declared filter whose cleaned value list is empty returns `[]`/`0` immediately.
- Filtering on declared facets ALONE (no analyzer filters) is valid — "every tool typed `bot`" is a legitimate discovery query and must not require a scanned repository.
- A declared match appears in `FacetMatch.matched` as `{"facet": "<field>", "value": …, "confidence": confidence_basis_points / 10000}`, so callers cannot tell which table a match came from — that is deliberate, the provenance distinction is ours, not the caller's.
- Ranking is unchanged (max confidence among matched facets, then tool name); declared-only matches rank by their own confidence.

Implement by building the `CatalogFacetValue` name-selects the same way as the analyzer ones and folding them into the same `INTERSECT` chain — both tables key on `tool_name`, so no join is needed.

**Tests:** declared-only filter; declared AND analyzer combined (a tool matching one but not the other is excluded); empty declared filter fails closed; `matched` carries the declared entry with its converted confidence; a tool with NO analysis report at all is still findable by a declared filter (this is the coverage-independence guarantee).

---

### Task 4: Backfill migration

**Files:**
- Modify: `proxy/migrate.py`
- Test: `tests/proxy/test_tool_facets.py` (extend)

**Step 1: Read `proxy/migrate.py` in full.** Find how existing migrations are structured (the `MigrationResult` dataclass near the top, and the main/run section that invokes each migration). The new migration must follow that exact pattern and be registered the same way.

**Step 2: Write the failing test**

```python
from backend.models import CanonicalToolCache, SourceAnalysisReport


def test_backfill_tool_signal_facets_is_idempotent():
    with db.session_scope() as s:
        uid = _report_user(s)
        s.add(SourceAnalysisReport(tool_name="sfedits", report=SAMPLE_REPORT, user_id=uid))
        s.add(
            SourceAnalysisReport(
                tool_name="sfedits",
                report={"dependencies": [{"value": "pypi:mwclient", "confidence": 0.9}]},
                user_id=uid,
            )
        )
    import migrate

    first = migrate.backfill_tool_signal_facets()
    second = migrate.backfill_tool_signal_facets()
    with db.session_scope() as s:
        values = {
            (f.facet_type, f.value) for f in s.query(ToolSignalFacet).all()
        }
    # Latest report wins.
    assert ("dependency", "pypi:mwclient") in values
    assert ("dependency", "pypi:pywikibot") not in values
    assert second == 0
```

Migration functions in this repo return a plain `int`; `MigrationResult` is constructed around them by `run_once()` (`proxy/migrate.py:70-85`), so the second-run assertion compares an integer. `tests/proxy/test_migrate.py` already exists — follow its import and invocation pattern exactly. `SourceAnalysisReport.user_id` is NOT NULL — every seed passes the `_report_user(s)` id, as above.

**Step 3: Implement the migration** in `proxy/migrate.py`, following the file's existing migration pattern:

- `backfill_tool_signal_facets()`: batched (500/tool batch) loop over distinct `tool_name`s in `SourceAnalysisReport`; for each, load the **latest** report (`order_by(SourceAnalysisReport.created_at.desc(), SourceAnalysisReport.id.desc()).limit(1)`) and call `tool_facets.replace_analyzer_facets(...)` with its id; skip tools whose facets already carry that `source_report_id` (that is the idempotency check — count them as untouched). No canonical-record pass: this table stores analyzer signals only.
- Register it in the migration run list exactly like its neighbors.

**Step 4: Run tests** — expect PASS. Run the full suite: `PYTHONPATH=proxy pytest tests/proxy -q` (coverage ratchet must hold).

**Step 5: Lint and commit**

```bash
ruff check proxy && ruff format proxy
git add proxy/migrate.py tests/proxy/test_tool_facets.py
git commit -m "feat: backfill tool signal facets from stored analysis reports"
```

---

### Task 5: Incremental hook (hourly scan)

**Files:**
- Modify: `proxy/repository_scan.py` (report-persist path, lines 283-301; session variable there is `s`)
- Test: extend the existing tests covering that path (grep `tests/proxy` for `repository_scan` and follow its fixtures)

**Step 1: The hook point (verified — mind the variable names).**
- In `proxy/repository_scan.py`, the analyzer output dict is named `report` (`report = analyze_source_files(...)` at line 275) and the ORM row is named `stored` (`stored = SourceAnalysisReport(..., report=report, ...)` at line 283, flushed at line 295, `state.report_id = stored.id` at line 301). Immediately after the `s.flush()` at line 295 (so `stored.id` is populated, same session `s`), add:

```python
try:
    tool_facets.replace_analyzer_facets(s, tool_name, report, source_report_id=stored.id)
except SQLAlchemyError:
    # A derived-index failure must not roll back the report itself; a
    # poisoned session still aborts the transaction, but with a trace.
    _log.exception("facet update failed for %s", tool_name)
```

with the `tool_facets` import added at the top of the file (use the module's existing logger name if one exists; otherwise add the standard `logging.getLogger(__name__)`).

- **No canonical-sync hook.** An earlier draft added one to `canonical_tools.upsert_records` for `tool_type`; it was dropped on 2026-08-13 with the tool_type facet itself (see Verified facts). The catalog sync path stays untouched, which also keeps its error-swallowing block (`canonical_tools.py:176-200`) free of derived-index work.

**Step 2: Write failing tests first.** Extend the existing test for each path: after the existing assertions that a report/canonical row was stored, assert the corresponding `ToolSignalFacet` rows exist (and for `upsert_records`, that re-upserting the same record adds nothing). Follow each test file's existing fixture/monkeypatch style exactly.

**Step 3: Implement the two hook calls. Run the touched test files, then the full suite:**

Run: `PYTHONPATH=proxy pytest tests/proxy -q --cov --cov-report=term-missing`
Expected: PASS, coverage ≥ 91.7%

**Step 4: Lint and commit**

```bash
ruff check proxy && ruff format proxy
git add proxy/repository_scan.py proxy/backend/canonical_tools.py tests/proxy/
git commit -m "feat: keep tool signal facets fresh from scan and sync paths"
```

---

## Phase completion check

- `PYTHONPATH=proxy pytest tests/proxy -q --cov --cov-report=term-missing` passes with coverage ≥ 91.7%.
- `ruff check proxy` and `ruff format --check proxy` clean.
- Manual spot check: `PYTHONPATH=proxy python proxy/migrate.py` against a copy of production data (per the design's "Done when"; a dev DB populated by a full catalog sync plus repository scans is an acceptable stand-in) populates `tool_signal_facets`; running it twice reports zero new rows the second time.

**Deviation note for reviewers:** the design's Phase 1 said the backfill runs as a "Toolforge one-shot job in `jobs.yaml`"; it lives in `proxy/migrate.py` instead because that file's contract (idempotent, batched, run by `tools/deploy.sh` on every deploy) is exactly what the design wanted from a one-shot job, and it is the repo's established home for row-proportional backfills.
