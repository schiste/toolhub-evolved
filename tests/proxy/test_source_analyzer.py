# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for deterministic source-code metadata analysis."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import source_analyzer  # noqa: E402
from backend.source_analyzer import MAX_FILE_BYTES, MAX_FILES, SourceAnalysisError, analyze_source_files  # noqa: E402


def values(report, bucket):
    return {item["value"] for item in report[bucket]}


def test_source_analyzer_extracts_projects_apis_rights_scopes_technology_and_redacted_warnings():
    report = analyze_source_files(
        [
            {
                "path": "src/gadget.user.js",
                "content": "\n".join(
                    [
                        "mw.loader.using(['mediawiki.api'], () => {});",
                        "const api = new mw.Api();",
                        "api.postWithToken('csrf', { action: 'edit', title: 'Sandbox', text: '...' });",
                        "fetch('https://commons.wikimedia.org/w/api.php?action=upload&format=json');",
                        "const scope = 'editpage uploadfile privateinfo';",
                        "const client_secret = 'super-secret-value';",
                    ]
                ),
            },
            {
                "path": "bot.py",
                "content": "\n".join(
                    [
                        "import pywikibot",
                        "params = {'action': 'wbeditentity'}",
                        "endpoint = 'https://query.wikidata.org/sparql'",
                        "query = 'SELECT * WHERE { ?item ?p ?o }'",
                    ]
                ),
            },
            {
                "path": "package.json",
                "content": '{"scripts":{"start":"vite"},"dependencies":{"react":"latest"}}',
            },
        ],
        tool_name="sample-tool",
        source_label="local checkout",
    )

    assert report["toolName"] == "sample-tool"
    assert report["sourceLabel"] == "local checkout"
    assert report["summary"]["filesAnalyzed"] == 3
    assert {"commonswiki", "wikidatawiki"} <= values(report, "projects")
    assert {"mediawiki-action-api", "wikibase-api", "wikidata-query-service", "commons-upload"} <= values(
        report, "apis"
    )
    assert {"edit", "upload", "wikibase-edit", "csrf-token"} <= values(report, "accessRights")
    assert {"csrf-token"} <= values(report, "authentication")
    assert {"editpage", "uploadfile", "privateinfo"} <= values(report, "oauthScopes")
    assert {"npm:react", "pypi:pywikibot"} <= values(report, "dependencies")
    assert {"JavaScript", "MediaWiki gadget", "Python", "Pywikibot", "React", "Node.js"} <= values(report, "technology")
    assert "credential-like-source" in values(report, "warnings")
    assert "write-without-auth-signal" not in values(report, "warnings")
    assert "[redacted credential-like assignment]" in str(report["warnings"])
    assert "super-secret-value" not in str(report)
    assert set(report["suggestions"]["toolinfoPatch"]["for_wikis"]) == {"commonswiki", "wikidatawiki"}
    assert report["suggestions"]["toolinfoPatch"]["tool_type"] == "gadget"
    assert {"npm:react", "pypi:pywikibot"} <= set(report["suggestions"]["evolvedMetadata"]["dependencies"])
    assert "x_toolhub_evolved_source_analysis" not in report["suggestions"]["toolinfoPatch"]


def test_source_analyzer_extracts_dependencies_from_manifests_and_imports():
    report = analyze_source_files(
        [
            {
                "path": "package.json",
                "content": '{"dependencies":{"@wikimedia/codex":"1.0.0","mediawiki-api":"2.0.0","wikibase-sdk":"9.0.0"},"devDependencies":{"vitest":"latest"}}',
            },
            {"path": "requirements.txt", "content": "Flask==3.0\nmwclient>=0.10\n-r extra.txt\n"},
            {
                "path": "pyproject.toml",
                "content": '[project]\ndependencies = ["requests>=2"]\n[project.optional-dependencies]\ntest = ["pytest"]\n',
            },
            {
                "path": "composer.json",
                "content": '{"require":{"mediawiki/oauthclient":"^2.0"},"require-dev":{"phpunit/phpunit":"^10"}}',
            },
            {
                "path": "composer.lock",
                "content": '{"packages":[{"name":"guzzlehttp/guzzle"}],"packages-dev":[{"name":"phpstan/phpstan"}]}',
            },
            {"path": "go.mod", "content": "module example\nrequire github.com/gorilla/mux v1.8.1\n"},
            {"path": "package-lock.json", "content": '{"packages":{"node_modules/lodash":{"version":"4.17.21"}}}'},
            {
                "path": "Pipfile.lock",
                "content": '{"default":{"click":{"version":"==8.0"}},"develop":{"ruff":{"version":"==0.1"}}}',
            },
            {"path": "poetry.lock", "content": '[[package]]\nname = "pydantic"\nversion = "2.0"\n'},
            {"path": "Cargo.toml", "content": '[dependencies]\nserde = "1"\n[dev-dependencies]\nproptest = "1"\n'},
            {"path": "Cargo.lock", "content": '[[package]]\nname = "regex"\nversion = "1.10"\n'},
            {"path": "Gemfile", "content": 'gem "rails", "~> 7"\n'},
            {"path": "Gemfile.lock", "content": "GEM\n  specs:\n    sinatra (3.0.0)\n"},
            {"path": "yarn.lock", "content": '"@wikimedia/design-tokens@npm:^1.0.0":\nreact@^18.0.0:\n'},
            {"path": "src/app.js", "content": 'import axios from "axios";\nconst local = require("./local");'},
            {"path": "src/app.py", "content": "import requests\nfrom backend import local\n"},
        ]
    )

    assert {
        "npm:@wikimedia/codex",
        "npm:mediawiki-api",
        "npm:wikibase-sdk",
        "npm:vitest",
        "npm:axios",
        "npm:lodash",
        "npm:@wikimedia/design-tokens",
        "pypi:flask",
        "pypi:mwclient",
        "pypi:requests",
        "pypi:pytest",
        "pypi:click",
        "pypi:pydantic",
        "composer:mediawiki/oauthclient",
        "composer:phpunit/phpunit",
        "composer:guzzlehttp/guzzle",
        "go:github.com/gorilla/mux",
        "cargo:serde",
        "cargo:proptest",
        "cargo:regex",
        "rubygems:rails",
        "rubygems:sinatra",
    } <= values(report, "dependencies")
    assert "mediawiki-action-api" in values(report, "apis")
    assert "wikibase-api" in values(report, "apis")
    assert report["summary"]["dependencyCount"] >= 14


def test_source_analyzer_builds_repository_context_and_assessments():
    report = analyze_source_files(
        [
            {"path": "README.md", "content": "Tool docs for en.wikipedia.org and a /healthz endpoint."},
            {"path": "LICENSE", "content": "GPL-3.0-or-later"},
            {"path": "SECURITY.md", "content": "Report security issues privately."},
            {"path": ".github/workflows/ci.yml", "content": "name: ci\non: [push]\n"},
            {"path": "tests/test_app.py", "content": "def test_smoke():\n    assert True\n"},
            {"path": "Dockerfile", "content": "FROM python:3.12\n"},
            {"path": ".toolforge/jobs.yaml", "content": "jobs: []\n"},
            {
                "path": "package.json",
                "content": '{"dependencies":{"@axe-core/playwright":"4.0.0","mediawiki-api":"2.0.0"}}',
            },
            {"path": "package-lock.json", "content": '{"dependencies":{"@axe-core/playwright":{"version":"4.0.0"}}}'},
            {
                "path": "public/index.html",
                "content": '<html lang="en"><button aria-label="Search">Search</button></html>',
            },
            {"path": "src/app.js", "content": "fetch('/w/api.php?action=query');"},
        ],
        repository_context={
            "repository": {
                "analyzedAt": "2026-07-30T12:00:00Z",
                "url": "https://github.com/example/tool",
                "branch": "main",
                "commitSha": "abc123",
                "lastCommitAt": "2026-07-29T12:00:00Z",
                "contributorCount": 3,
            },
            "maintainers": {
                "maintainerCount": 2,
                "activeMaintainerCount": 1,
                "lastActivityAgeDays": 3,
                "recentActivityCount": 4,
                "source": "toolhub",
            },
            "declared": {"oauthScopes": ["basic"], "runtime": "Toolforge webservice", "healthUrl": "/healthz"},
        },
    )

    context = report["repositoryContext"]
    assert context["repository"]["url"] == "https://github.com/example/tool"
    assert {"readme", "license", "security"} <= {item["kind"] for item in context["documentation"]}
    assert {"npm"} <= {item["kind"] for item in context["manifests"]}
    assert {"npm"} <= {item["kind"] for item in context["lockfiles"]}
    assert {"github-actions"} <= {item["kind"] for item in context["ci"]}
    assert {"container", "toolforge"} <= {item["kind"] for item in context["runtime"]}
    assert {"test-suite"} <= {item["kind"] for item in context["tests"]}
    assert context["health"][0]["kind"] == "health-endpoint"
    assert context["accessibility"][0]["kind"] == "accessibility-signal"
    assert context["maintenance"]["status"] == "active"
    assert context["maintainerActivity"]["status"] == "active"
    assert {"frontend", "manifest"} <= {item["class"] for item in context["inventory"]["bySourceClass"]}
    assert report["summary"]["assessmentCount"] == 8
    assert report["summary"]["assessmentScore"] > 75
    assert report["summary"]["healthScore"] > 75
    assert report["summary"]["maintainerStatus"] == "active"
    assert report["healthCore"]["stewardshipStatus"] == "healthy"
    assert "maintainer-activity" in {item["key"] for item in report["healthCore"]["dimensions"]}
    assert "metadata-completeness" in report["suggestions"]["evolvedMetadata"]["assessment_scores"]
    assert report["suggestions"]["evolvedMetadata"]["health_core"]["score"] == report["summary"]["healthScore"]
    assessments = {item["key"]: item for item in report["assessments"]}
    assert assessments["metadata-completeness"]["grade"] == "strong"
    assert assessments["maintenance-activity"]["grade"] == "strong"
    assert assessments["frontend-accessibility"]["score"] >= 85


def test_source_analyzer_handles_lockfile_edges_and_low_assessment_scores():
    report = analyze_source_files(
        [
            {"path": "src/app.py", "content": "import requests\n"},
            {"path": "package-lock.json", "content": "["},
            {"path": "list/package-lock.json", "content": "[]"},
            {
                "path": "npm-shrinkwrap.json",
                "content": '{"packages":{"":{"version":"1.0.0"},"packages/not-node":{},"node_modules/@scope/pkg":{}}}',
            },
            {"path": "Pipfile.lock", "content": "["},
            {"path": "list/Pipfile.lock", "content": "[]"},
            {"path": "poetry.lock", "content": "["},
            {"path": "list/poetry.lock", "content": 'package = ["bad"]\n'},
            {"path": "blank/poetry.lock", "content": '[[package]]\nname = ""\n'},
            {"path": "composer.lock", "content": "["},
            {"path": "list/composer.lock", "content": "[]"},
            {"path": "weird/composer.lock", "content": '{"packages":["bad",{"name":""}]}'},
            {"path": "Cargo.lock", "content": "["},
            {"path": "list/Cargo.lock", "content": "[]"},
            {"path": "weird/Cargo.lock", "content": 'package = ["bad"]\n'},
            {"path": "blank/Cargo.lock", "content": '[[package]]\nname = ""\n'},
            {"path": "Gemfile.lock", "content": "GEM\n  specs:\n"},
            {"path": "pnpm-lock.yaml", "content": "# lockfile\n./local@npm:1.0.0:\nleft-pad@npm:1.3.0:\n"},
        ]
    )

    assert {"pypi:requests", "npm:@scope/pkg", "npm:left-pad"} <= values(report, "dependencies")
    assessments = {item["key"]: item for item in report["assessments"]}
    assert assessments["dependency-health"]["grade"] == "needs-attention"
    assert assessments["metadata-completeness"]["grade"] == "needs-attention"
    assert report["summary"]["assessmentCount"] == 7


def test_source_analyzer_scores_missing_declared_scopes_and_frontend_a11y_gaps():
    report = analyze_source_files(
        [
            {
                "path": "src/app.js",
                "content": "\n".join(
                    [
                        "const api = new mw.Api();",
                        "api.postWithToken('csrf', { action: 'edit', title: 'Sandbox' });",
                        "const scope = 'editpage uploadfile';",
                    ]
                ),
            }
        ],
        repository_context={"declared": {"oauthScopes": ["editpage"]}},
    )

    assessments = {item["key"]: item for item in report["assessments"]}
    permission = assessments["permission-clarity"]
    assert permission["grade"] == "good"
    assert "Inferred scopes missing from declared context" in str(permission["signals"])
    assert assessments["frontend-accessibility"]["grade"] == "high-risk"


def test_source_analyzer_covers_dependency_edge_cases_and_import_ecosystems():
    report = analyze_source_files(
        [
            {"path": "package.json", "content": '{"dependencies":{".local":"file:."}'},
            {"path": "valid/package.json", "content": '{"dependencies":{".local":"file:.","axios":"^1"}}'},
            {"path": "composer.json", "content": '{"require":'},
            {"path": "requirements.txt", "content": "Toolz @ https://example.org/toolz.tar.gz\n"},
            {
                "path": "pyproject.toml",
                "content": "\n".join(
                    [
                        "[project]",
                        'dependencies = ["", "Django>=4"]',
                        "[project.optional-dependencies]",
                        'test = [""]',
                        "[tool.poetry.dependencies]",
                        'python = "^3.11"',
                        'Flask = "^3"',
                        "[tool.poetry.group.dev.dependencies]",
                        'pytest = "*"',
                    ]
                ),
            },
            {"path": "broken/pyproject.toml", "content": "["},
            {
                "path": "bad-optional/pyproject.toml",
                "content": '[project]\ndependencies = []\noptional-dependencies = "not-a-table"\n',
            },
            {"path": "string-poetry/pyproject.toml", "content": '[tool]\npoetry = "not-a-table"\n'},
            {"path": "Pipfile", "content": "[packages]\nrequests='*'\n[dev-packages]\npytest='*'\n"},
            {"path": "broken/Pipfile", "content": "["},
            {"path": "Gemfile", "content": 'source "https://rubygems.org"\n'},
            {"path": "src/app.js", "content": 'import codex from "@wikimedia/codex";'},
            {"path": "src/app.php", "content": "<?php\nuse GuzzleHttp\\Client;"},
            {"path": "src/app.rb", "content": 'puts "hello"\nrequire "sinatra"'},
        ]
    )

    assert {
        "npm:axios",
        "pypi:django",
        "pypi:flask",
        "pypi:pytest",
        "pypi:requests",
        "pypi:toolz",
        "npm:@wikimedia/codex",
        "composer:guzzlehttp",
        "rubygems:sinatra",
    } <= values(report, "dependencies")
    assert "pypi:python" not in values(report, "dependencies")


def test_source_analyzer_adds_cross_file_warnings_for_admin_and_unauthenticated_writes():
    report = analyze_source_files([{"path": "src/admin.js", "content": "fetch('/w/api.php?action=delete&title=Bad');"}])
    assert {"administrator-actions", "write-without-auth-signal"} <= values(report, "warnings")
    assert report["summary"]["writeActionsDetected"] is True


def test_source_analyzer_records_read_actions_without_write_warning():
    report = analyze_source_files([{"path": "src/read.js", "content": "fetch('/w/api.php?action=query');"}])
    assert "read-public" in values(report, "accessRights")
    assert "write-without-auth-signal" not in values(report, "warnings")
    assert report["summary"]["writeActionsDetected"] is False


def test_source_analyzer_handles_database_names_without_technology_suggestion():
    report = analyze_source_files([{"path": "README.md", "content": "Targets enwiki and commonswiki."}])
    assert {"enwiki", "commonswiki"} <= values(report, "projects")
    assert report["technology"] == []
    assert report["suggestions"]["toolinfoPatch"] == {"for_wikis": ["commonswiki", "enwiki"]}


def test_source_analyzer_ignores_dependency_and_build_paths():
    report = analyze_source_files(
        [
            {
                "path": ".venv/lib/python3.14/site-packages/boolean/boolean.py",
                "content": "See https://en.wikipedia.org/wiki/Absorption_law",
            },
            {
                "path": "src/app.js",
                "content": "const api = new mw.Api();",
            },
        ]
    )

    assert values(report, "projects") == set()
    assert values(report, "apis") == {"mediawiki-action-api"}
    assert report["summary"]["filesAnalyzed"] == 1


def test_source_analyzer_keeps_low_provenance_findings_out_of_publishable_metadata():
    report = analyze_source_files(
        [
            {
                "path": "proxy/backend/source_analyzer.py",
                "content": "\n".join(
                    [
                        'KNOWN_OAUTH_SCOPES = {"delete": ("Delete pages", 0.88)}',
                        'ACTION_RIGHTS = {"delete": (("delete", "Delete pages", "administrator", 0.92),)}',
                    ]
                ),
            },
            {
                "path": "public_html/lib/organisms/source-analysis.js",
                "content": 'const sample = \'api.postWithToken("csrf", { action: "edit" });\';',
            },
        ]
    )

    assert values(report, "oauthScopes") == set()
    assert {"edit", "csrf-token"} <= values(report, "accessRights")
    assert report["summary"]["writeActionsDetected"] is False
    assert "write-without-auth-signal" not in values(report, "warnings")
    assert report["suggestions"]["evolvedMetadata"]["oauth_scopes"] == []
    assert "edit" not in report["suggestions"]["evolvedMetadata"]["access_rights"]
    assert all(item["maxSourceWeight"] <= 0.15 for item in report["accessRights"])


def test_source_analyzer_identifies_stale_repository_activity():
    report = analyze_source_files(
        [{"path": "README.md", "content": "Tool docs for en.wikipedia.org."}],
        repository_context={
            "repository": {
                "analyzedAt": "2026-07-30T00:00:00Z",
                "commitCount": 4,
                "contributorCount": 1,
                "lastCommitAt": "2025-01-01T00:00:00Z",
            },
            "maintainers": {
                "maintainerCount": 2,
                "activeMaintainerCount": 1,
                "lastActivityAgeDays": 7,
                "recentActivityCount": 2,
            },
        },
    )

    context = report["repositoryContext"]
    assessments = {item["key"]: item for item in report["assessments"]}
    assert context["maintenance"]["status"] == "stale"
    assert context["maintenance"]["lastCommitAgeDays"] == 575
    assert context["maintainerActivity"]["status"] == "active"
    assert report["summary"]["maintenanceStatus"] == "stale"
    assert report["summary"]["maintainerStatus"] == "active"
    assert report["summary"]["stewardshipStatus"] == "source-stale-maintainer-active"
    assert assessments["maintenance-activity"]["grade"] == "high-risk"
    dimensions = {item["key"]: item for item in report["healthCore"]["dimensions"]}
    assert dimensions["source-maintenance"]["grade"] == "high-risk"
    assert dimensions["maintainer-activity"]["grade"] == "strong"


def test_source_analyzer_does_not_treat_mediawiki_prose_as_a_project_database():
    report = analyze_source_files(
        [
            {
                "path": "README.md",
                "content": "Uses the MediaWiki Action API, a \\bmediawiki action pattern, and Meta-Wiki.",
            }
        ]
    )

    assert values(report, "projects") == set()
    assert "mediawiki-action-api" in values(report, "apis")


def test_source_analyzer_avoids_cli_action_keywords_and_local_python_modules():
    report = analyze_source_files(
        [
            {"path": "README.md", "content": "Local tool."},
            {"path": "crawl.py", "content": "def main():\n    return None\n"},
            {"path": "proxy/cache_prewarm.py", "content": "def main():\n    return None\n"},
            {"path": "toolpkg/__init__.py", "content": ""},
            {
                "path": "app.py",
                "content": "\n".join(
                    [
                        'parser.add_argument("--flag", action="store_true")',
                        "import crawl",
                        "import cache_prewarm",
                        "import toolpkg",
                        "import requests",
                    ]
                ),
            },
        ]
    )

    assert "mediawiki-action-api" not in values(report, "apis")
    assert "pypi:requests" in values(report, "dependencies")
    assert "pypi:crawl" not in values(report, "dependencies")
    assert "pypi:cache_prewarm" not in values(report, "dependencies")
    assert "pypi:toolpkg" not in values(report, "dependencies")


@pytest.mark.parametrize(
    ("host", "sub", "family", "expected"),
    [
        ("commons.wikimedia.org", "commons", "wikimedia", ("commonswiki", "Commons", 0.94)),
        ("www.wikidata.org", "www", "wikidata", ("wikidatawiki", "Wikidata", 0.94)),
        ("meta.wikimedia.org", "meta", "wikimedia", ("metawiki", "Meta-Wiki", 0.94)),
        ("www.mediawiki.org", "www", "mediawiki", ("mediawikiwiki", "MediaWiki.org", 0.92)),
        ("en.wikipedia.org", "en", "wikipedia", ("enwiki", "en.wikipedia.org", 0.9)),
        ("api.wikimedia.org", "api", "wikimedia", ("api.wikimedia.org", "api.wikimedia.org", 0.78)),
    ],
)
def test_project_host_mapping(host, sub, family, expected):
    assert source_analyzer._project_from_host(host, sub, family) == expected


@pytest.mark.parametrize(
    ("files", "message"),
    [
        (None, "non-empty list"),
        ([], "non-empty list"),
        ([None], "object"),
        ([{"path": "a.py", "content": None}], "content must be text"),
        ([{"path": "a.py", "content": "x" * (MAX_FILE_BYTES + 1)}], "file is larger"),
        ([{"path": "image.png", "content": "x"}], "no supported source files"),
        ([{"path": f"{i}.py", "content": "x"} for i in range(MAX_FILES + 1)], "at most"),
    ],
)
def test_source_analyzer_rejects_unsafe_or_malformed_input(files, message):
    with pytest.raises(SourceAnalysisError, match=message):
        analyze_source_files(files)


def test_source_analyzer_rejects_total_payloads_over_the_limit():
    content = "x" * MAX_FILE_BYTES
    files = [{"path": f"{index}.py", "content": content} for index in range(9)]
    with pytest.raises(SourceAnalysisError, match="in total"):
        analyze_source_files(files)


def test_source_analyzer_rejects_invalid_repository_context():
    with pytest.raises(SourceAnalysisError, match="repositoryContext"):
        analyze_source_files([{"path": "src/app.js", "content": "const api = new mw.Api();"}], repository_context=[])


def test_source_analyzer_utility_branches_are_stable():
    assert source_analyzer._suffix("README") == ""
    assert source_analyzer._clean_path("") == "source.txt"
    assert source_analyzer._clean_path("\\nested//tool.py").startswith("nested/")
    assert source_analyzer._is_source_path("Dockerfile") is True
    assert source_analyzer._is_source_path("package-lock.json") is True
    assert source_analyzer._is_source_path("cspell.json") is False
    assert source_analyzer._is_source_path("asset.png") is False
    assert source_analyzer._line_for_text("first\nsecond", "missing") == (1, "first")
    assert source_analyzer._line_excerpt("plain text") == "plain text"
    assert source_analyzer._line_excerpt("password = 'hidden'") == "[redacted credential-like assignment]"
    assert source_analyzer._line_excerpt("access_token: Mapped[str] = mapped_column(Text)") != (
        "[redacted credential-like assignment]"
    )
    assert source_analyzer._documentation_kind("docs/README.rst") == "readme"
    assert source_analyzer._documentation_kind("LICENSE.txt") == "license"
    assert source_analyzer._documentation_kind("notes.txt") is None
    assert source_analyzer._ci_kind(".github/workflows/ci.txt") is None
    assert source_analyzer._runtime_kind(".toolforge/jobs.yaml") == "toolforge"
    assert source_analyzer._test_kind("src/app.test.js") == "test-file"
    assert source_analyzer._lock_package_from_locator("./local@npm:1") is None
    assert source_analyzer._lock_package_from_locator("@scope/pkg@npm:^1") == "@scope/pkg"
    assert source_analyzer._score_grade(40) == "high-risk"
    assert source_analyzer._clean_context_value(True) is True
    assert source_analyzer._clean_context_value(5) == 5
    assert source_analyzer._clean_context_list("basic") == ["basic"]
    assert source_analyzer._normalize_repository_context(None) == {}
    assert source_analyzer._context_kinds({"rows": [None]}, "rows") == set()
    assert source_analyzer._declared_list({"declared": {"oauthScopes": "basic"}}, "oauthScopes") == set()
    assert source_analyzer._category_counts(
        {"dependencySources": {"categories": [None, {"category": "imported", "count": "2"}]}}
    ) == {"imported": 2}
    assert source_analyzer._dependency_source_context({"dependencies": [{"value": "bad", "category": "runtime"}]}) == {
        "count": 1,
        "ecosystems": [],
        "categories": [{"category": "runtime", "count": 1}],
    }
    assert source_analyzer._source_class("proxy/backend/source_analyzer.py") == "analysis-tooling"
    assert source_analyzer._source_class("tests/unit/example.test.js") == "test"
    assert source_analyzer._source_class("package-lock.json") == "lockfile"
    assert source_analyzer._activity_status(800) == "dormant"
    assert source_analyzer._first_finding_evidence({"rows": [{}, {"evidence": []}]}, "rows") is None
    assert source_analyzer._first_context_evidence({"rows": [None, {"kind": "b", "path": "p"}]}, "rows", "a") is None
    stray_findings = {}
    source_analyzer._scan_lockfile_dependencies(stray_findings, source_analyzer.SourceFile("unknown.lock", ""))
    assert stray_findings == {}
    clamped = source_analyzer._assessment(
        "x",
        "X",
        -10,
        2,
        "Summary",
        [{"status": "neutral", "label": str(index)} for index in range(10)],
        [str(index) for index in range(10)],
    )
    assert clamped["score"] == 0
    assert clamped["confidence"] == 0.99
    assert len(clamped["signals"]) == source_analyzer.MAX_ASSESSMENT_SIGNALS
    assert source_analyzer._clean_dependency_name("") is None
    assert source_analyzer._clean_dependency_name("x" * 121) is None
    assert source_analyzer._clean_dependency_name("https://example.org/pkg") is None
    findings = {}
    source_analyzer._put_dependency(
        findings,
        ecosystem="npm",
        name="",
        category="runtime",
        confidence=1,
        reason="test",
        evidence={"path": "test", "line": 1, "match": "", "excerpt": ""},
    )
    source_analyzer._put_dependency(
        findings,
        ecosystem="composer",
        name="ext-json",
        category="runtime",
        confidence=1,
        reason="test",
        evidence={"path": "test", "line": 1, "match": "", "excerpt": ""},
    )
    assert findings == {}
    assert source_analyzer._tool_type_suggestion([{"value": "React"}], []) == "web app"
    assert source_analyzer._tool_type_suggestion([{"value": "Pywikibot"}], [{"value": "mediawiki-action-api"}]) == "bot"
    assert source_analyzer._tool_type_suggestion([], []) is None


def test_source_class_covers_fixture_example_and_unknown_paths():
    assert source_analyzer._source_class("src/fixtures/data.json") == "fixture"
    assert source_analyzer._source_class("src/examples/demo.js") == "example"
    assert source_analyzer._source_class("data.csv") == "unknown"
    assert source_analyzer._source_weight("data.csv") == source_analyzer.SOURCE_CLASS_WEIGHTS["unknown"]


def test_local_python_import_roots_skips_case_mismatched_python_suffix():
    roots = source_analyzer._local_python_import_roots([source_analyzer.SourceFile("Weird.PY", "")])
    assert "Weird" not in roots
    assert "weird" not in roots


def test_parse_iso_datetime_handles_explicit_offsets_and_malformed_text():
    parsed = source_analyzer._parse_iso_datetime("2026-07-30T12:00:00+00:00")
    assert parsed is not None
    assert parsed.tzinfo is not None
    assert source_analyzer._parse_iso_datetime("not-a-date") is None


def test_int_context_value_rejects_booleans():
    assert source_analyzer._int_context_value(True) is None
    assert source_analyzer._int_context_value(False) is None


def test_last_commit_age_days_uses_provided_age_when_present():
    assert source_analyzer._last_commit_age_days({"lastCommitAgeDays": 5}) == 5
    assert source_analyzer._last_commit_age_days({"lastCommitAgeDays": -5}) == 0


def test_activity_and_maintainer_status_cover_every_band():
    assert source_analyzer._activity_status(200) == "quiet"
    assert source_analyzer._maintainer_status(None) == "unknown"
    assert source_analyzer._maintainer_status(200) == "quiet"
    assert source_analyzer._maintainer_status(500) == "stale"
    assert source_analyzer._maintainer_status(800) == "dormant"


def test_repository_maintenance_context_flags_dirty_checkout():
    context = source_analyzer._repository_maintenance_context({"dirty": True})
    assert {"kind": "dirty-checkout", "value": True} in context["signals"]


def test_maintainer_activity_context_falls_back_to_repository_analyzed_at():
    context = source_analyzer._maintainer_activity_context(
        {"lastActivityAt": "2026-07-30T00:00:00Z"},
        {"analyzedAt": "2026-08-01T00:00:00Z"},
    )
    assert context["lastActivityAgeDays"] == 2


def test_maintainer_activity_context_prefers_its_own_analyzed_at_over_repository():
    context = source_analyzer._maintainer_activity_context(
        {"lastActivityAt": "2026-07-30T00:00:00Z", "analyzedAt": "2026-08-01T00:00:00Z"},
        {"analyzedAt": "2026-09-01T00:00:00Z"},
    )
    assert context["lastActivityAgeDays"] == 2


def test_maintainer_activity_context_leaves_age_unknown_without_any_dates():
    context = source_analyzer._maintainer_activity_context({"source": "toolhub"}, {})
    assert context["lastActivityAgeDays"] is None
    assert context["status"] == "unknown"
    assert "last-maintainer-activity-age" not in {item["kind"] for item in context["signals"]}


def test_maintainer_activity_context_handles_missing_counts():
    context = source_analyzer._maintainer_activity_context({"lastActivityAgeDays": 10}, {})
    signal_kinds = {item["kind"] for item in context["signals"]}
    assert context["maintainerCount"] is None
    assert context["activeMaintainerCount"] is None
    assert context["recentActivityCount"] is None
    assert "maintainer-count" not in signal_kinds
    assert "active-maintainer-count" not in signal_kinds
    assert "recent-maintainer-activity-count" not in signal_kinds


def test_security_review_assessment_flags_admin_actions_and_unauthenticated_writes():
    report = {
        "warnings": [
            {"value": "administrator-actions", "confidence": 0.9, "maxSourceWeight": 1.0},
            {"value": "write-without-auth-signal", "confidence": 0.9, "maxSourceWeight": 1.0},
        ],
        "authentication": [],
    }
    result = source_analyzer._security_review_assessment(report, {})
    labels = {signal["label"] for signal in result["signals"]}
    assert "Administrator or suppressive actions need review" in labels
    assert "Write action without authentication evidence" in labels
    assert "Document why elevated wiki rights are necessary." in result["recommendations"]
    assert "Add explicit authentication/token handling or document why it is external." in result["recommendations"]


def test_maintenance_activity_assessment_flags_quiet_status_and_dirty_checkout():
    result = source_analyzer._maintenance_activity_assessment(
        {
            "maintenance": {"status": "quiet", "lastCommitAgeDays": 200},
            "repository": {"dirty": True},
        }
    )
    labels = {signal["label"] for signal in result["signals"]}
    assert "Repository activity is quiet" in labels
    assert "Local checkout had uncommitted changes" in labels
    assert "Confirm the repository still reflects the deployed tool." in result["recommendations"]


def test_maintenance_activity_assessment_flags_dormant_status():
    result = source_analyzer._maintenance_activity_assessment(
        {"maintenance": {"status": "dormant", "lastCommitAgeDays": 900}}
    )
    labels = {signal["label"] for signal in result["signals"]}
    assert "Repository appears dormant" in labels
    assert "Flag the tool for maintainer outreach or archival review." in result["recommendations"]


def test_maintainer_activity_score_covers_every_count_branch():
    assert source_analyzer._maintainer_activity_score({"status": "quiet"}) == 70
    assert source_analyzer._maintainer_activity_score({"status": "active", "activeMaintainerCount": 5}) == 95
    assert source_analyzer._maintainer_activity_score({"status": "active", "activeMaintainerCount": 0}) == 70
    assert source_analyzer._maintainer_activity_score({"status": "active", "maintainerCount": 0}) == 60
    assert source_analyzer._maintainer_activity_score({"status": "active", "maintainerCount": 1}) == 85


def test_stewardship_status_covers_at_risk_and_outreach_branches():
    assert (
        source_analyzer._stewardship_status(
            {"maintenance": {"status": "stale"}, "maintainerActivity": {"status": "dormant"}}
        )
        == "at-risk"
    )
    assert (
        source_analyzer._stewardship_status(
            {"maintenance": {"status": "active"}, "maintainerActivity": {"status": "stale"}}
        )
        == "maintainer-outreach-needed"
    )
