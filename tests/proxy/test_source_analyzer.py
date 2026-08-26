# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for deterministic source-code metadata analysis."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import (  # noqa: E402
    source_analysis_assessments,
    source_analysis_common,
    source_analyzer,
    wiki_sources,
)
from backend.source_analyzer import (  # noqa: E402
    MAX_FILE_BYTES,
    MAX_FILES,
    MAX_WIKI_FILE_BYTES,
    SourceAnalysisError,
    analyze_source_files,
    source_reading_rank,
)


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
    assert {"JavaScript", "MediaWiki JavaScript", "Python", "Pywikibot", "React", "Node.js"} <= values(
        report, "technology"
    )
    assert "credential-like-source" in values(report, "warnings")
    assert "write-without-auth-signal" not in values(report, "warnings")
    assert "[redacted credential-like assignment]" in str(report["warnings"])
    assert "super-secret-value" not in str(report)
    assert set(report["suggestions"]["toolinfoPatch"]["for_wikis"]) == {"commonswiki", "wikidatawiki"}
    # A local checkout is not a wiki page, so no amount of MediaWiki JavaScript
    # in it can make it a gadget. React and Node.js decide what it is instead.
    assert report["suggestions"]["toolinfoPatch"]["tool_type"] == "web app"
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
    # Found, reported with its evidence -- but a single mention in prose is not
    # enough to write onto someone's catalogue record. See _is_corroborated().
    assert report["suggestions"]["toolinfoPatch"] == {}


def test_a_wiki_named_once_in_prose_is_reported_but_not_suggested():
    report = analyze_source_files([{"path": "README.md", "content": "Targets enwiki."}])

    assert values(report, "projects") == {"enwiki"}
    assert report["projects"][0]["fileCount"] == 1
    assert report["suggestions"]["toolinfoPatch"] == {}


def test_a_wiki_named_in_two_documents_is_corroborated_enough_to_suggest():
    report = analyze_source_files(
        [
            {"path": "README.md", "content": "Targets enwiki."},
            {"path": "docs/usage.md", "content": "Runs against enwiki."},
        ]
    )

    assert report["projects"][0]["fileCount"] == 2
    assert report["suggestions"]["toolinfoPatch"] == {"for_wikis": ["enwiki"]}


def test_a_wiki_named_once_in_the_tools_own_source_needs_no_second_opinion():
    report = analyze_source_files([{"path": "src/app.js", "content": "const wiki = 'enwiki';"}])

    assert report["projects"][0]["fileCount"] == 1
    assert report["projects"][0]["maxSourceWeight"] >= 0.85
    assert report["suggestions"]["toolinfoPatch"]["for_wikis"] == ["enwiki"]


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
        # An API host is not a wiki. This case previously pinned the old
        # fallthrough, which published the raw hostname into for_wikis.
        ("api.wikimedia.org", "api", "wikimedia", None),
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


def test_the_wider_wiki_ceiling_belongs_to_the_page_not_to_the_caller():
    """A wiki page may exceed the checkout cap. The same bytes submitted may not.

    The limit is keyed on wiki_page because only _acquire_wiki sets it; the HTTP
    route and the CLI leave it None. Were it a plain argument, a caller could ask
    for the larger ceiling, and this is the test that would stop mattering.
    """
    files = [{"path": "MediaWiki:Gadget-LiveRC.js", "content": "var a = 1;\n" + "x" * MAX_FILE_BYTES}]
    page = wiki_sources.WikiSource(
        domain="fr.wikipedia.org", title="MediaWiki:Gadget-LiveRC.js", kind=wiki_sources.KIND_GADGET
    )

    assert analyze_source_files(files, wiki_page=page)["filesAnalyzed"] == 1
    with pytest.raises(SourceAnalysisError, match="file is larger"):
        analyze_source_files(files)


def test_even_a_wiki_page_stops_at_the_wiki_ceiling():
    files = [{"path": "MediaWiki:Gadget-Huge.js", "content": "x" * (MAX_WIKI_FILE_BYTES + 1)}]
    page = wiki_sources.WikiSource(
        domain="ru.wikipedia.org", title="MediaWiki:Gadget-Huge.js", kind=wiki_sources.KIND_GADGET
    )
    with pytest.raises(SourceAnalysisError, match="file is larger"):
        analyze_source_files(files, wiki_page=page)


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
    assert source_analysis_assessments._score_grade(40) == "high-risk"
    assert source_analyzer._clean_context_value(True) is True
    assert source_analyzer._clean_context_value(5) == 5
    assert source_analyzer._clean_context_list("basic") == ["basic"]
    assert source_analyzer._normalize_repository_context(None) == {}
    assert source_analysis_common._context_kinds({"rows": [None]}, "rows") == set()
    assert source_analysis_common._declared_list({"declared": {"oauthScopes": "basic"}}, "oauthScopes") == set()
    assert source_analysis_common._category_counts(
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
    assert source_analysis_assessments._first_finding_evidence({"rows": [{}, {"evidence": []}]}, "rows") is None
    assert (
        source_analysis_assessments._first_context_evidence({"rows": [None, {"kind": "b", "path": "p"}]}, "rows", "a")
        is None
    )
    stray_findings = {}
    source_analyzer._scan_lockfile_dependencies(stray_findings, source_analyzer.SourceFile("unknown.lock", ""))
    assert stray_findings == {}
    clamped = source_analysis_assessments._assessment(
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
    assert len(clamped["signals"]) == source_analysis_common.MAX_ASSESSMENT_SIGNALS
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


GADGET_URL = "https://fr.wikipedia.org/wiki/MediaWiki:Gadget-HotCat.js"
SCRIPT_URL = "https://fr.wikipedia.org/wiki/User:Someone/HotCat.js"


def test_a_wiki_page_is_typed_by_what_the_wiki_says_rather_than_by_its_contents():
    """A user script is settled by its namespace and a gadget by its registration."""
    assert source_analyzer._tool_type_suggestion([], [], SCRIPT_URL) == "user script"
    assert source_analyzer._tool_type_suggestion([], [], GADGET_URL, wiki_sources.KIND_GADGET) == "gadget"
    # No code was read to reach either answer, so contradicting evidence in the
    # page cannot move it: a gadget that ships React is still a gadget.
    assert (
        source_analyzer._tool_type_suggestion([{"value": "React"}], [], GADGET_URL, wiki_sources.KIND_GADGET)
        == "gadget"
    )


def test_a_gadget_namespace_page_is_not_a_gadget_until_the_definition_says_so():
    """The title is the convention a gadget's files follow, not its registration.

    A gadget retired by removing its definition line keeps its page, and a page
    written in advance of its line never had one. Both are `MediaWiki:Gadget-*`
    and neither is served to a reader, so neither may fill an empty tool_type.
    """
    assert source_analyzer._tool_type_suggestion([], [], GADGET_URL) is None
    assert source_analyzer._tool_type_suggestion([], [], GADGET_URL, wiki_sources.KIND_GADGET_PAGE) is None


def test_a_wiki_page_of_unestablished_kind_does_not_fall_through_to_the_heuristics():
    """Not-a-gadget is still a wiki page, and a wiki page is not a Flask app.

    Falling through would answer "web app" for the MediaWiki JavaScript every
    gadget page contains, which is the same mistake one namespace further on.
    """
    mediawiki_js = [{"value": "MediaWiki JavaScript"}, {"value": "React"}]
    assert source_analyzer._tool_type_suggestion(mediawiki_js, [], GADGET_URL) is None


def _wiki_report(definition):
    """Analyze one gadget page for real, with its registration settled as the scanner does."""
    page, _pages = wiki_sources.registered_gadget(wiki_sources.wiki_source(GADGET_URL), definition)
    return analyze_source_files(
        [{"path": "MediaWiki:Gadget-HotCat.js", "content": "new mw.Api().get({});\n"}],
        tool_name="hotcat",
        source_label=GADGET_URL,
        wiki_page=page,
    )


def test_a_registered_gadget_is_suggested_as_a_gadget_and_says_why():
    report = _wiki_report("* HotCat[ResourceLoader]|HotCat.js\n")
    assert report["suggestions"]["toolinfoPatch"]["tool_type"] == "gadget"
    # On file next to the suggestion it produced, so a reviewer can see what
    # the answer was read off rather than having to re-derive it.
    assert report["wikiPage"] == {
        "domain": "fr.wikipedia.org",
        "title": "MediaWiki:Gadget-HotCat.js",
        "kind": wiki_sources.KIND_GADGET,
    }


def test_a_gadget_page_the_wiki_does_not_serve_gets_no_tool_type_at_all():
    report = _wiki_report("* Something[ResourceLoader]|Else.js\n")
    assert "tool_type" not in report["suggestions"]["toolinfoPatch"]
    assert report["wikiPage"]["kind"] == wiki_sources.KIND_GADGET_PAGE


def test_an_analysis_that_never_looked_at_a_definition_claims_no_gadget():
    """The API path takes files from a request and fetches nothing.

    It cannot check a registration, so it does not get to assert one -- which
    is the same rule as everywhere else here: the suggestion states what was
    established, and an unchecked convention was not established.
    """
    report = analyze_source_files(
        [{"path": "MediaWiki:Gadget-HotCat.js", "content": "new mw.Api().get({});\n"}],
        tool_name="hotcat",
        source_label=GADGET_URL,
    )
    assert "tool_type" not in report["suggestions"]["toolinfoPatch"]
    assert report["wikiPage"] == {}


def test_a_repository_is_never_suggested_as_a_gadget_or_a_user_script():
    """A gadget is a page a wiki serves, so a checkout cannot be one.

    Toolhub Evolved itself was catalogued as a gadget: a Flask application
    whose own analyzer, tests and UI all quote `mw.Api`, with no tool type
    declared upstream for the guess to lose to.
    """
    mediawiki_js = [{"value": "MediaWiki JavaScript"}, {"value": "JavaScript"}]

    for source in ("https://github.com/schiste/toolhub-evolved", "local checkout", ""):
        assert source_analyzer._tool_type_suggestion(mediawiki_js, [], source) not in {"gadget", "user script"}


def test_mediawiki_javascript_is_detected_from_a_call_in_a_script_and_not_from_a_mention():
    """The technology rule reads calls in browser JavaScript, not prose."""
    report = analyze_source_files(
        [
            {"path": "docs/design.py", "content": '"""`mw.Api` says MediaWiki without naming a wiki."""'},
            {"path": "src/notes.md", "content": "We call new mw.Api() from the gadget."},
            {"path": "src/shouty.js", "content": "const api = new MW.API();"},
            {"path": "src/prose.js", "content": "// mw.Api is the client we use."},
        ],
        tool_name="mentions-only",
    )

    assert "MediaWiki JavaScript" not in values(report, "technology")


def test_a_file_named_as_a_user_script_counts_without_reading_its_contents():
    report = analyze_source_files([{"path": "src/HotCat.user.js", "content": "var x = 1;"}], tool_name="named")

    assert "MediaWiki JavaScript" in values(report, "technology")


def test_source_class_covers_fixture_example_and_unknown_paths():
    assert source_analyzer._source_class("src/fixtures/data.json") == "fixture"
    assert source_analyzer._source_class("src/examples/demo.js") == "example"
    assert source_analyzer._source_class("data.csv") == "unknown"
    assert source_analyzer._source_weight("data.csv") == source_analysis_common.SOURCE_CLASS_WEIGHTS["unknown"]


def test_local_python_import_roots_skips_case_mismatched_python_suffix():
    roots = source_analyzer._local_python_import_roots([source_analyzer.SourceFile("Weird.PY", "")])
    assert "Weird" not in roots
    assert "weird" not in roots


def test_parse_iso_datetime_handles_explicit_offsets_and_malformed_text():
    parsed = source_analysis_common._parse_iso_datetime("2026-07-30T12:00:00+00:00")
    assert parsed is not None
    assert parsed.tzinfo is not None
    assert source_analysis_common._parse_iso_datetime("not-a-date") is None


def test_int_context_value_rejects_booleans():
    assert source_analysis_common._int_context_value(True) is None
    assert source_analysis_common._int_context_value(False) is None


def test_last_commit_age_days_uses_provided_age_when_present():
    assert source_analyzer._last_commit_age_days({"lastCommitAgeDays": 5}) == 5
    assert source_analyzer._last_commit_age_days({"lastCommitAgeDays": -5}) == 0


def test_activity_and_maintainer_status_cover_every_band():
    assert source_analyzer._activity_status(200) == "quiet"
    assert source_analysis_common._maintainer_status(None) == "unknown"
    assert source_analysis_common._maintainer_status(200) == "quiet"
    assert source_analysis_common._maintainer_status(500) == "stale"
    assert source_analysis_common._maintainer_status(800) == "dormant"


def test_repository_maintenance_context_flags_dirty_checkout():
    context = source_analyzer._repository_maintenance_context({"dirty": True})
    assert {"kind": "dirty-checkout", "value": True} in context["signals"]


def test_maintainer_activity_context_falls_back_to_repository_analyzed_at():
    context = source_analysis_assessments._maintainer_activity_context(
        {"lastActivityAt": "2026-07-30T00:00:00Z"},
        {"analyzedAt": "2026-08-01T00:00:00Z"},
    )
    assert context["lastActivityAgeDays"] == 2


def test_maintainer_activity_context_prefers_its_own_analyzed_at_over_repository():
    context = source_analysis_assessments._maintainer_activity_context(
        {"lastActivityAt": "2026-07-30T00:00:00Z", "analyzedAt": "2026-08-01T00:00:00Z"},
        {"analyzedAt": "2026-09-01T00:00:00Z"},
    )
    assert context["lastActivityAgeDays"] == 2


def test_maintainer_activity_context_leaves_age_unknown_without_any_dates():
    context = source_analysis_assessments._maintainer_activity_context({"source": "toolhub"}, {})
    assert context["lastActivityAgeDays"] is None
    assert context["status"] == "unknown"
    assert "last-maintainer-activity-age" not in {item["kind"] for item in context["signals"]}


def test_maintainer_activity_context_handles_missing_counts():
    context = source_analysis_assessments._maintainer_activity_context({"lastActivityAgeDays": 10}, {})
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
    result = source_analysis_assessments._security_review_assessment(report, {})
    labels = {signal["label"] for signal in result["signals"]}
    assert "Administrator or suppressive actions need review" in labels
    assert "Write action without authentication evidence" in labels
    assert "Document why elevated wiki rights are necessary." in result["recommendations"]
    assert "Add explicit authentication/token handling or document why it is external." in result["recommendations"]


def test_maintenance_activity_assessment_flags_quiet_status_and_dirty_checkout():
    result = source_analysis_assessments._maintenance_activity_assessment(
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
    result = source_analysis_assessments._maintenance_activity_assessment(
        {"maintenance": {"status": "dormant", "lastCommitAgeDays": 900}}
    )
    labels = {signal["label"] for signal in result["signals"]}
    assert "Repository appears dormant" in labels
    assert "Flag the tool for maintainer outreach or archival review." in result["recommendations"]


def test_maintainer_activity_score_covers_every_count_branch():
    assert source_analysis_assessments._maintainer_activity_score({"status": "quiet"}) == 70
    assert (
        source_analysis_assessments._maintainer_activity_score({"status": "active", "activeMaintainerCount": 5}) == 95
    )
    assert (
        source_analysis_assessments._maintainer_activity_score({"status": "active", "activeMaintainerCount": 0}) == 70
    )
    assert source_analysis_assessments._maintainer_activity_score({"status": "active", "maintainerCount": 0}) == 60
    assert source_analysis_assessments._maintainer_activity_score({"status": "active", "maintainerCount": 1}) == 85


def test_stewardship_status_covers_at_risk_and_outreach_branches():
    assert (
        source_analysis_assessments._stewardship_status(
            {"maintenance": {"status": "stale"}, "maintainerActivity": {"status": "dormant"}}
        )
        == "at-risk"
    )
    assert (
        source_analysis_assessments._stewardship_status(
            {"maintenance": {"status": "active"}, "maintainerActivity": {"status": "stale"}}
        )
        == "maintainer-outreach-needed"
    )


def test_the_report_names_the_hosts_and_calls_a_tool_makes():
    # The apis bucket says "MediaWiki Action API" for the first line and has
    # nothing at all to say about the second. Together the two buckets say what
    # a reviewer actually asks: which services, and doing what.
    report = analyze_source_files(
        [
            {
                "path": "src/bot.js",
                "content": "\n".join(
                    [
                        "fetch('https://commons.wikimedia.org/w/api.php?action=upload&format=json');",
                        "fetch('https://api.openai.com/v1/chat/completions', {method: 'POST'});",
                    ]
                ),
            }
        ]
    )
    assert values(report, "endpoints") == {
        "commons.wikimedia.org/w/api.php?action=upload",
        "api.openai.com/v1/chat/completions",
    }
    assert report["summary"]["endpointCount"] == 2
    # The half a reviewer is looking for: one service nobody in the movement runs.
    assert report["summary"]["externalEndpointCount"] == 1


def test_an_endpoint_is_filed_by_who_operates_it():
    report = analyze_source_files(
        [
            {
                "path": "src/geo.js",
                "content": "\n".join(
                    [
                        "fetch('https://query.wikidata.org/sparql?query=SELECT');",
                        "fetch('https://nominatim.openstreetmap.org/search');",
                    ]
                ),
            }
        ]
    )
    families = {item["value"]: item["category"] for item in report["endpoints"]}
    # Not a wiki, but Wikimedia's. Filing WDQS as third party would misreport
    # the one dependency the movement actually controls.
    assert families["query.wikidata.org/sparql"] == "wikimedia"
    assert families["nominatim.openstreetmap.org/search"] == "external"


def test_a_url_that_is_called_outranks_one_that_is_only_mentioned():
    # Same file both times, so the only difference is the call. A README would
    # not do here any more: a mention in one is no longer a finding at all.
    called = analyze_source_files(
        [{"path": "src/app.js", "content": "await fetch('https://api.openai.com/v1/models');"}]
    )
    mentioned = analyze_source_files(
        [{"path": "src/app.js", "content": "const BASE = 'https://api.openai.com/v1/models';"}]
    )
    assert called["endpoints"][0]["confidence"] > mentioned["endpoints"][0]["confidence"]


def test_a_lockfiles_registry_is_not_reported_as_a_tools_endpoint():
    # Every resolved entry carries a registry URL. That registry belongs to the
    # package manager, and at a lockfile's 0.95 weight it would otherwise be
    # the loudest endpoint in most reports.
    report = analyze_source_files(
        [
            {
                "path": "package-lock.json",
                "content": '{"packages": {"node_modules/axios": {"resolved": "https://registry.npmjs.org/axios/-/axios-1.0.0.tgz"}}}',
            }
        ]
    )
    assert report["endpoints"] == []


@pytest.mark.parametrize(
    "path",
    [
        "README.md",
        "docs/install.md",
        "CHANGELOG.md",
        "HISTORY.txt",
        "tests/test_client.py",
        "examples/demo.py",
        ".github/workflows/release.yml",
    ],
)
def test_a_file_that_points_at_things_needs_to_show_the_call(path):
    # Measured across sixteen repositories: a README lists where to download the
    # tool, a changelog cites the ticket behind a fix, a test names a host
    # nothing is listening on. On cli/cli and psf/requests that tail filled the
    # forty-finding cap between them and left neither project's own API surface
    # in the report.
    content = "Install from https://packages.acme-data.org/stable/tool"
    assert analyze_source_files([{"path": path, "content": content}])["endpoints"] == []


@pytest.mark.parametrize(
    "path",
    ["README.md", "tests/test_client.py", ".github/workflows/release.yml"],
)
def test_the_same_file_is_believed_once_it_shows_the_call(path):
    # The rule is about evidence, not about the folder. A documentation line
    # that pipes an address into curl is describing a fetch, and psf/requests'
    # own manual is where its httpbin calls are written down.
    content = "Run curl https://packages.acme-data.org/stable/tool"
    report = analyze_source_files([{"path": path, "content": content}])
    assert [item["value"] for item in report["endpoints"]] == ["packages.acme-data.org/stable/tool"]


@pytest.mark.parametrize(
    "path",
    ["src/client.py", "src/app.js", "config/services.yaml", "package.json"],
)
def test_a_file_the_tool_is_made_of_is_taken_at_its_word(path):
    # A base URL is assigned far more often than it is fetched on the same line.
    # Requiring a call here would cost the addresses the bucket exists to hold.
    content = '{"base": "https://api.acme-data.org/v1/things"}'
    report = analyze_source_files([{"path": path, "content": content}])
    assert "api.acme-data.org/v1/things" in {item["value"] for item in report["endpoints"]}


def test_a_secret_in_a_url_never_reaches_the_endpoints_bucket():
    report = analyze_source_files(
        [{"path": "src/app.js", "content": "fetch('https://api.acme-data.org/v1?api_key=sk-live-abcdef0123456789');"}]
    )
    assert values(report, "endpoints") == {"api.acme-data.org/v1"}
    assert "sk-live" not in str(report["endpoints"])


def test_a_request_word_inside_the_url_is_not_a_call():
    # Measured on wikimedia-gadgets/twinkle: a CONTRIBUTING.md line linking to
    # `.../creating-a-pull-request-from-a-fork` scored as a request, because
    # the signal matched the word `request` inside the address itself.
    #
    # In a documentation file the signal now decides whether the address is
    # recorded at all, so a word read out of the address costs the whole rule.
    prose = analyze_source_files(
        [{"path": "docs/guide.md", "content": "Open https://api.acme-data.org/creating-a-pull-request-from-a-fork"}]
    )
    called = analyze_source_files(
        [{"path": "docs/guide.md", "content": "fetch('https://api.acme-data.org/creating-a-pull-request-from-a-fork')"}]
    )
    assert prose["endpoints"] == []
    assert [item["value"] for item in called["endpoints"]] == ["api.acme-data.org/creating-a-pull-request-from-a-fork"]


def test_a_link_to_documentation_is_not_reported_as_an_endpoint():
    # The bucket is capped, so reading material does not merely add noise --
    # on Twinkle it filled the cap and displaced the real API surface. Read here
    # from a file that is believed without a call signal, so that what is being
    # tested is the shape of the address rather than the shape of the line.
    report = analyze_source_files(
        [
            {
                "path": "src/twinkle.js",
                "content": (
                    "See https://en.wikipedia.org/wiki/Wikipedia:Twinkle and "
                    "https://github.com/wikimedia-gadgets/twinkle for details. "
                    "It calls https://en.wikipedia.org/w/api.php?action=edit"
                ),
            }
        ]
    )
    assert [item["value"] for item in report["endpoints"]] == ["en.wikipedia.org/w/api.php?action=edit"]


def test_a_url_at_the_line_budget_is_not_reported_half_read():
    # Measured on commons-app/apps-android-commons: the README contributor
    # table is one line of many URLs, and cutting it at MAX_LINE_CHARS left
    # `avatars.githubusercon` behind -- a name that parses as a host, resolves
    # nowhere, and reads in a report as a service the app contacts.
    filler = "word " * 120
    content = f"{filler}https://avatars.githubusercontent.com/u/12345 trailing"
    assert len(content) > source_analysis_common.MAX_LINE_CHARS
    report = analyze_source_files([{"path": "README.md", "content": content}])
    assert all("githubuserc" not in item["value"] for item in report["endpoints"])


def test_a_line_with_no_token_boundary_is_still_read():
    # Minified JavaScript has no whitespace to cut back to. Falling back to the
    # hard cut keeps the scanner working on every bundle; refusing the line
    # would blind it to them entirely.
    head = "x='" + "a" * 300 + "';fetch('https://api.acme-data.org/v1');"
    content = head + "b" * 400
    assert len(head) < source_analysis_common.MAX_LINE_CHARS < len(content)
    assert " " not in content
    report = analyze_source_files([{"path": "src/app.js", "content": content}])
    assert [item["value"] for item in report["endpoints"]] == ["api.acme-data.org/v1"]


def test_the_reading_order_takes_the_tools_own_code_before_what_describes_it():
    paths = [
        "tests/test_client.py",
        "docs/guide.md",
        ".github/workflows/ci.yml",
        "src/client.py",
        "package.json",
        "examples/demo.py",
    ]

    assert sorted(paths, key=source_reading_rank) == [
        "package.json",
        "src/client.py",
        "docs/guide.md",
        ".github/workflows/ci.yml",
        "tests/test_client.py",
        "examples/demo.py",
    ]


def test_the_reading_order_takes_the_shallow_file_of_a_class_before_the_deep_one():
    paths = ["src/update/internal/refresh.py", "src/client.py", "main.py"]

    assert sorted(paths, key=source_reading_rank) == ["main.py", "src/client.py", "src/update/internal/refresh.py"]


def test_the_reading_order_settles_the_last_tie_by_path_so_two_reads_agree():
    assert sorted(["src/b.py", "src/a.py"], key=source_reading_rank) == ["src/a.py", "src/b.py"]


def test_the_reading_order_reads_a_windows_separator_as_a_path_separator():
    assert source_reading_rank("src\\client.py") == source_reading_rank("src/client.py")


def bucket_finding(label, confidence, paths):
    row = source_analyzer.Finding(
        value=label, label=label, kind="endpoints", category="api", base_confidence=confidence
    )
    row.evidence = [{"path": path} for path in paths]
    return row


def test_the_bucket_cap_keeps_the_finding_that_more_files_agree_on():
    two = bucket_finding("two", 0.74, ["src/a.py", "src/b.py"])
    one = bucket_finding("one", 0.74, ["src/a.py"])
    assert sorted([one, two], key=source_analyzer._finding_rank) == [two, one]


def test_the_bucket_cap_keeps_the_finding_the_same_file_said_more_than_once():
    twice = bucket_finding("twice", 0.74, ["src/a.py", "src/a.py"])
    once = bucket_finding("once", 0.74, ["src/a.py"])
    assert sorted([once, twice], key=source_analyzer._finding_rank) == [twice, once]


def test_the_bucket_cap_keeps_what_the_code_said_over_what_only_describes_it():
    # Equally scored and equally attested, so the tie falls to where the sighting came
    # from -- and the tool is its code, not the page advertising the code.
    code = bucket_finding("code", 0.74, ["src/charts.js"])
    page = bucket_finding("page", 0.74, ["docs/index.md"])
    assert sorted([page, code], key=source_analyzer._finding_rank) == [code, page]


def test_the_bucket_cap_ranks_on_the_confidence_it_measured_not_the_one_it_prints():
    # Both print as 0.74. Ranking the printed form would call them equal and then hand
    # the tie to the alphabet, which would put the weaker of the two first.
    stronger = bucket_finding("z", 0.744, ["src/a.py"])
    weaker = bucket_finding("a", 0.736, ["src/a.py"])
    assert sorted([weaker, stronger], key=source_analyzer._finding_rank) == [stronger, weaker]


def test_the_bucket_cap_settles_the_last_tie_by_label_so_two_runs_agree():
    later = bucket_finding("b", 0.74, ["src/a.py"])
    earlier = bucket_finding("a", 0.74, ["src/a.py"])
    assert sorted([later, earlier], key=source_analyzer._finding_rank) == [earlier, later]


def test_a_short_bucket_cap_keeps_the_endpoint_the_tools_own_module_calls(monkeypatch):
    # One slot, two endpoints scored identically, and the one that sorts first
    # alphabetically is buried three directories down. The slot belongs to the call
    # written in the module the package presents.
    monkeypatch.setattr(source_analyzer, "MAX_FINDINGS_PER_BUCKET", 1)
    report = analyze_source_files(
        [
            {"path": "src/client.py", "content": "requests.get('https://api.zzz-data.org/v1/things')"},
            {
                "path": "src/internal/legacy/shim.py",
                "content": "requests.get('https://api.aaa-data.org/v1/things')",
            },
        ]
    )
    assert values(report, "endpoints") == {"api.zzz-data.org/v1/things"}


def rows_by_value(report, bucket):
    return {item["value"]: item for item in report[bucket]}


def test_a_pinned_requirement_reports_the_release_and_a_range_reports_only_the_spec():
    report = analyze_source_files(
        [{"path": "requirements.txt", "content": "mwclient==0.10.1\nFlask>=3.0,<4\npywikibot\n"}]
    )
    rows = rows_by_value(report, "dependencies")
    assert rows["pypi:mwclient"]["version"] == "0.10.1"
    assert rows["pypi:mwclient"]["versionSpecs"] == ["==0.10.1"]
    # A range names no release, so there is a spec to show and no version.
    assert "version" not in rows["pypi:flask"]
    assert rows["pypi:flask"]["versionSpecs"] == [">=3.0,<4"]
    # An unconstrained requirement declared nothing at all.
    assert "version" not in rows["pypi:pywikibot"]
    assert "versionSpecs" not in rows["pypi:pywikibot"]


def test_a_locator_where_a_version_belongs_is_not_reported_as_a_version():
    report = analyze_source_files(
        [
            {
                "path": "package.json",
                "content": json.dumps(
                    {
                        "dependencies": {
                            "from-git": "git+https://example.org/a/b.git",
                            "from-workspace": "workspace:*",
                            "unpinned": "*",
                            "pinned": "1.3.0",
                        }
                    }
                ),
            }
        ]
    )
    rows = rows_by_value(report, "dependencies")
    for name in ("npm:from-git", "npm:from-workspace", "npm:unpinned"):
        assert "version" not in rows[name], name
        assert "versionSpecs" not in rows[name], name
    assert rows["npm:pinned"]["version"] == "1.3.0"


def test_two_manifests_pinning_different_releases_report_no_single_version():
    report = analyze_source_files(
        [
            {"path": "requirements.txt", "content": "flask==3.0.2\n"},
            {"path": "requirements-dev.txt", "content": "flask==2.3.3\n"},
        ]
    )
    row = rows_by_value(report, "dependencies")["pypi:flask"]
    assert "version" not in row
    assert row["versionSpecs"] == ["==2.3.3", "==3.0.2"]


def test_every_lockfile_reports_the_release_it_resolved():
    report = analyze_source_files(
        [
            {
                "path": "yarn.lock",
                "content": 'react@^18.2.0:\n  version "18.2.0"\n  resolved "https://x"\n',
            },
            {"path": "Gemfile.lock", "content": "GEM\n  specs:\n    rails (7.0.4)\n"},
            {"path": "poetry.lock", "content": '[[package]]\nname = "requests"\nversion = "2.31.0"\n'},
            {"path": "Cargo.lock", "content": '[[package]]\nname = "serde"\nversion = "1.0.197"\n'},
            {
                "path": "composer.lock",
                "content": json.dumps({"packages": [{"name": "monolog/monolog", "version": "3.5.0"}]}),
            },
            {"path": "go.mod", "content": "module x\n\nrequire github.com/foo/bar v1.4.2 // indirect\n"},
        ]
    )
    rows = rows_by_value(report, "dependencies")
    assert rows["npm:react"]["version"] == "18.2.0"
    assert rows["rubygems:rails"]["version"] == "7.0.4"
    assert rows["pypi:requests"]["version"] == "2.31.0"
    assert rows["cargo:serde"]["version"] == "1.0.197"
    assert rows["composer:monolog/monolog"]["version"] == "3.5.0"
    assert rows["go:github.com/foo/bar"]["version"] == "1.4.2"


def test_a_yarn_entry_without_a_version_line_does_not_borrow_the_next_entrys():
    report = analyze_source_files([{"path": "yarn.lock", "content": 'silent@^1:\nlodash@^4:\n  version "4.17.21"\n'}])
    rows = rows_by_value(report, "dependencies")
    assert "version" not in rows["npm:silent"]
    assert rows["npm:lodash"]["version"] == "4.17.21"


def test_a_gemfile_option_that_is_not_a_version_is_not_read_as_one():
    report = analyze_source_files([{"path": "Gemfile", "content": 'gem "rails", "~> 7.0"\ngem "puma", group: "dev"\n'}])
    rows = rows_by_value(report, "dependencies")
    assert rows["rubygems:rails"]["versionSpecs"] == ["~> 7.0"]
    assert "versionSpecs" not in rows["rubygems:puma"]


def test_a_technology_carries_the_version_the_manifest_pins_for_its_package():
    report = analyze_source_files(
        [
            {"path": "app.py", "content": "from flask import Flask\napp = Flask(__name__)\n"},
            {"path": "requirements.txt", "content": "Flask==3.0.2\n"},
        ]
    )
    assert rows_by_value(report, "technology")["Flask"]["version"] == "3.0.2"
    # The catalog patch stays the plain name: the version lives beside it.
    assert report["suggestions"]["toolinfoPatch"]["technology_used"] == ["Flask", "Python"]


def test_a_package_named_only_by_a_lockfile_does_not_invent_its_technology():
    report = analyze_source_files(
        [
            {
                "path": "package-lock.json",
                "content": json.dumps({"packages": {"node_modules/vue": {"version": "3.4.21"}}}),
            }
        ]
    )
    # Nothing in this checkout is written in Vue, so the resolved version has no
    # technology to attach to and none is conjured for it.
    assert "Vue" not in values(report, "technology")
    assert rows_by_value(report, "dependencies")["npm:vue"]["version"] == "3.4.21"


def test_a_declared_runtime_names_the_technology_and_the_version_it_requires():
    report = analyze_source_files(
        [
            {"path": "package.json", "content": json.dumps({"engines": {"node": ">=18"}})},
            {"path": "pyproject.toml", "content": '[project]\nname = "x"\nrequires-python = ">=3.11"\n'},
            {"path": "composer.json", "content": json.dumps({"require": {"php": ">=8.1"}})},
            {"path": "go.mod", "content": "module x\n\ngo 1.21\n"},
        ]
    )
    rows = rows_by_value(report, "technology")
    assert rows["Node.js"]["versionSpecs"] == [">=18"]
    assert rows["Python"]["versionSpecs"] == [">=3.11"]
    assert rows["PHP"]["versionSpecs"] == [">=8.1"]
    # A go directive pins one release, unlike the three ranges above.
    assert rows["Go"]["version"] == "1.21"
    # The language version is not a module the tool depends on.
    assert "go:go" not in values(report, "dependencies")


def test_a_lockfile_naming_react_does_not_make_the_tool_a_react_tool():
    """The bug: one `node_modules/react` line catalogued any checkout that installed it."""
    report = analyze_source_files(
        [
            {
                "path": "package-lock.json",
                "content": json.dumps({"packages": {"node_modules/react": {"version": "18.2.0"}}}),
            }
        ]
    )
    assert "React" not in values(report, "technology")
    assert "npm:react" in values(report, "dependencies")


def test_the_english_word_react_is_not_a_framework():
    report = analyze_source_files(
        [
            {"path": "README.md", "content": "The bot will react to new edits.\n"},
            {"path": "app.js", "content": "// react to the click event\nconst x = 1;\n"},
            {"path": "bot.py", "content": '"""We react to changes."""\n'},
        ]
    )
    assert "React" not in values(report, "technology")


def test_a_usage_quoted_in_documentation_is_documentation():
    """A README showing how to import React is writing about it, not calling it."""
    report = analyze_source_files(
        [{"path": "README.md", "content": "Install it, then:\n\n```js\nimport React from 'react';\n```\n"}]
    )
    assert "React" not in values(report, "technology")


def test_react_is_read_from_a_usage_in_browser_source():
    for content in (
        "import React from 'react';\n",
        'import { useState } from "react";\n',
        "const React = require('react');\n",
        "React.createElement('div');\n",
    ):
        report = analyze_source_files([{"path": "src/ui.js", "content": content}])
        assert "React" in values(report, "technology"), content
    # A different library whose name ends in the same letters is not React.
    report = analyze_source_files([{"path": "src/ui.js", "content": "import { h } from 'preact';\n"}])
    assert "React" not in values(report, "technology")


def test_a_declared_package_names_its_technology_when_no_source_file_reached_it():
    report = analyze_source_files(
        [{"path": "package.json", "content": json.dumps({"dependencies": {"react": "18.2.0"}})}]
    )
    row = rows_by_value(report, "technology")["React"]
    assert row["category"] == "framework"
    assert row["version"] == "18.2.0"
    # Declared, not observed, so it sits below every source-observed rule.
    assert row["confidence"] < 0.9


def test_a_promoted_technology_keeps_the_category_its_kind_belongs_in():
    report = analyze_source_files(
        [{"path": "package.json", "content": json.dumps({"dependencies": {"vue": "3.4.21", "flask": "1.0"}})}]
    )
    rows = rows_by_value(report, "technology")
    assert rows["Vue"]["category"] == "language"
    # A pypi package declared in package.json is not a pypi dependency.
    assert "Flask" not in rows


def test_only_evidence_somebody_wrote_down_can_promote_a_technology():
    lockfile_only = source_analyzer.Finding(
        value="npm:react", label="react (npm)", kind="dependencies", category="locked", base_confidence=0.8
    )
    lockfile_only.add(0.8, "Locked npm dependency.", {"sourceClass": "lockfile"})
    assert source_analyzer._declared_evidence(lockfile_only) is None

    declared = source_analyzer.Finding(
        value="npm:react", label="react (npm)", kind="dependencies", category="runtime", base_confidence=0.9
    )
    declared.add(0.9, "Locked npm dependency.", {"sourceClass": "lockfile"})
    declared.add(0.9, "Declared npm runtime dependency.", {"sourceClass": "manifest", "path": "package.json"})
    # The lockfile row came first and is skipped: the evidence shown has to be
    # the one the promotion actually rests on.
    assert source_analyzer._declared_evidence(declared)["path"] == "package.json"


def test_a_component_written_in_jsx_is_source_the_analyzer_can_see():
    """The bug: `.jsx` was in no extension list, so the readers never offered one.

    A React tool whose components are all `.jsx` had nothing the analyzer would
    accept -- it answered "no supported source files were provided" -- so the
    framework it is built with, the language it is written in and every package
    it imports were all invisible.
    """
    report = analyze_source_files(
        [
            {
                "path": "src/App.jsx",
                "content": "import React from 'react';\nimport axios from 'axios';\nexport default () => <App />;\n",
            }
        ]
    )
    assert "React" in values(report, "technology")
    assert "JavaScript" in values(report, "technology")
    assert "npm:axios" in values(report, "dependencies")


def test_an_es_module_and_a_commonjs_script_have_their_imports_read():
    """`.mjs` and `.cjs` were named as browser scripts but never read, so those entries were dead."""
    report = analyze_source_files(
        [
            {"path": "tools/build.mjs", "content": "import minimist from 'minimist';\n"},
            {"path": "tools/legacy.cjs", "content": "const lodash = require('lodash');\n"},
        ]
    )
    assert values(report, "dependencies") >= {"npm:minimist", "npm:lodash"}
    assert "JavaScript" in values(report, "technology")


def test_a_jsx_component_is_worth_reading_as_much_as_the_js_file_beside_it():
    """Same code, same weight: the module syntax in the suffix is not evidence about the file."""
    baseline = source_reading_rank("src/app.js")[0]
    for suffix in (".cjs", ".jsx", ".mjs"):
        assert source_reading_rank(f"src/app{suffix}")[0] == baseline, suffix


# --- F2: for_wikis is a closed vocabulary -----------------------------------
#
# These pin values observed in a live run of the analyzer over this repository,
# where 7 of 29 emitted "projects" were Python identifiers or regex artifacts.


@pytest.mark.parametrize(
    "identifier",
    ["target_wiki", "clean_wiki", "whole_wiki", "created_at_wiki", "touched_at_wiki", "enumerate_wiki"],
)
def test_underscore_identifiers_are_not_wikis(identifier):
    """An underscore directly before the suffix marks an identifier, not a wiki."""
    assert source_analysis_common.PROJECT_DB_RE.findall(identifier) == []


@pytest.mark.parametrize("db_name", ["enwiki", "commonswiki", "zh_yuewiki", "be_x_oldwiki", "simplewiki"])
def test_real_database_names_still_match(db_name):
    """Underscores inside a language code are legitimate and must survive."""
    assert source_analysis_common.PROJECT_DB_RE.findall(db_name) == [db_name]


@pytest.mark.parametrize("word", ["interwiki", "dokuwiki", "xwiki", "mediawiki"])
def test_wiki_vocabulary_words_are_not_database_names(word):
    """These match the shape but name a concept or a competing engine."""
    assert word in source_analysis_common.IGNORED_PROJECT_DB_NAMES


def test_capitalised_prefix_does_not_leak_a_truncated_match():
    """`MediaWiki:Gadget-*` used to yield the database name `ediawiki`."""
    assert source_analysis_common.PROJECT_DB_RE.findall("# `MediaWiki:Gadget-LinkTransform`") == []


@pytest.mark.parametrize(
    "host,sub",
    [
        ("gerrit.wikimedia.org", "gerrit"),
        ("phabricator.wikimedia.org", "phabricator"),
        ("upload.wikimedia.org", "upload"),
        ("toolsadmin.wikimedia.org", "toolsadmin"),
    ],
)
def test_wikimedia_infrastructure_hosts_are_not_wikis(host, sub):
    assert source_analyzer._project_from_host(host, sub, "wikimedia") is None


def test_every_content_family_maps_to_a_database_name():
    """fr.wikipedia.org became `frwiki` while fr.wiktionary.org stayed a hostname."""
    assert source_analyzer._project_from_host("fr.wikipedia.org", "fr", "wikipedia")[0] == "frwiki"
    assert source_analyzer._project_from_host("fr.wiktionary.org", "fr", "wiktionary")[0] == "frwiktionary"
    assert source_analyzer._project_from_host("de.wikisource.org", "de", "wikisource")[0] == "dewikisource"


def test_hyphenated_language_subdomain_becomes_an_underscored_database_name():
    assert source_analyzer._project_from_host("zh-yue.wikipedia.org", "zh-yue", "wikipedia")[0] == "zh_yuewiki"


def test_mobile_subdomain_does_not_become_the_wiki_m():
    """`en.m.wikipedia.org` presents `m` as the subdomain."""
    assert source_analyzer._project_from_host("en.m.wikipedia.org", "m", "wikipedia") is None


# --- F1: the reading budget reserves slots for context -----------------------


def _many_runtime_files(count=400):
    return [f"src/module_{i:04d}.py" for i in range(count)]


def test_reserve_reaches_context_past_a_full_budget_of_code():
    """The defect: on a repo with >= MAX_FILES code files, no README is reachable."""
    paths = [*_many_runtime_files(), "README.md", "LICENSE", ".github/workflows/ci.yml", "tests/test_a.py"]
    head = source_analyzer.order_sources_for_reading(paths)[:MAX_FILES]
    for expected in ("README.md", "LICENSE", ".github/workflows/ci.yml", "tests/test_a.py"):
        assert expected in head, expected


def test_plain_weight_ranking_would_have_missed_them():
    """Pins the behaviour being corrected, so the fix cannot silently regress."""
    paths = [*_many_runtime_files(), "README.md", ".github/workflows/ci.yml", "tests/test_a.py"]
    head = sorted(paths, key=source_reading_rank)[:MAX_FILES]
    assert "README.md" not in head
    assert ".github/workflows/ci.yml" not in head


def test_one_class_cannot_consume_the_whole_reserve():
    """22 docs candidates used to take all 20 slots, starving ci/tests again."""
    paths = [
        *_many_runtime_files(),
        *[f"docs/page_{i}.md" for i in range(40)],
        ".github/workflows/ci.yml",
        "tests/test_a.py",
    ]
    head = source_analyzer.order_sources_for_reading(paths)[:MAX_FILES]
    assert ".github/workflows/ci.yml" in head
    assert "tests/test_a.py" in head


def test_unused_quota_spills_to_other_context_classes():
    """A repository with no CI should spend those slots, not waste them."""
    paths = [*_many_runtime_files(), *[f"tests/test_{i}.py" for i in range(30)]]
    reserved = source_analyzer.order_sources_for_reading(paths)[: source_analysis_common.CONTEXT_RESERVE_SLOTS]
    assert sum(1 for p in reserved if p.startswith("tests/")) > 6  # more than the bare test quota


def test_reserve_never_drops_or_duplicates_a_candidate():
    paths = [*_many_runtime_files(50), "README.md", "tests/test_a.py", ".github/workflows/ci.yml"]
    ordered = source_analyzer.order_sources_for_reading(paths)
    assert sorted(ordered) == sorted(paths)
    assert len(ordered) == len(set(ordered))


def test_ordering_accepts_a_path_extractor_for_tuple_candidates():
    """repository_scan carries (oid, path) pairs through the same ordering."""
    items = [("oid-a", "src/app.py"), ("oid-b", "README.md")]
    ordered = source_analyzer.order_sources_for_reading(items, lambda entry: entry[1])
    assert ordered[0] == ("oid-b", "README.md")


def test_a_repository_with_no_context_files_is_ordered_by_weight_alone():
    paths = _many_runtime_files(10)
    assert source_analyzer.order_sources_for_reading(paths) == sorted(paths, key=source_reading_rank)


def test_the_reserve_never_crowds_out_a_small_budget():
    """At MAX_FILES=1 a 20-slot reserve would spend the only slot on a doc."""
    paths = ["docs/guide.md", "src/client.py"]
    assert source_analyzer.order_sources_for_reading(paths, budget=1) == ["src/client.py", "docs/guide.md"]


def test_reserve_scales_with_the_budget_in_force():
    assert source_analyzer.order_sources_for_reading(["README.md"], budget=6)[:1] == ["README.md"]
    paths = [*_many_runtime_files(30), "README.md"]
    assert "README.md" not in source_analyzer.order_sources_for_reading(paths, budget=5)[:5]


# --- F3: corroboration is per distinct file, and bounded ---------------------


def _ev(path, weight=1.0, source_class="runtime"):
    return {"path": path, "line": 1, "match": "m", "excerpt": "e", "sourceClass": source_class, "sourceWeight": weight}


def _finding():
    return source_analyzer.Finding(value="v", label="v", kind="projects", category="wiki")


def test_repetition_within_one_file_is_one_observation():
    """Thirty hits in a single file used to add ~0.87 of confidence."""
    single = _finding()
    for line in range(30):
        single.add(0.76, "r", {**_ev("src/app.py"), "line": line})
    once = _finding()
    once.add(0.76, "r", _ev("src/app.py"))
    assert single.confidence == pytest.approx(once.confidence)


def test_distinct_files_do_corroborate():
    spread = _finding()
    spread.add(0.76, "r", _ev("src/a.py"))
    spread.add(0.76, "r", _ev("src/b.py"))
    assert spread.confidence > 0.76


def test_corroboration_is_bounded_by_the_file_count():
    many = _finding()
    for i in range(40):
        many.add(0.76, "r", _ev(f"src/f{i}.py"))
    ceiling = (
        0.76
        + source_analysis_common.CONFIDENCE_MAX_CORROBORATING_FILES * source_analysis_common.CONFIDENCE_REPEAT_BOOST
    )
    assert many.confidence <= ceiling + 1e-9


def test_low_provenance_files_never_corroborate():
    fixtures = _finding()
    for i in range(10):
        fixtures.add(0.76, "r", _ev(f"tests/fixture_{i}.py", weight=0.15, source_class="fixture"))
    assert fixtures.confidence < 0.76  # weighted down, and never boosted


def test_a_repeated_false_positive_cannot_reach_certainty_on_volume():
    """The shape of the clean_wiki failure: one idiom, many sightings."""
    noisy = _finding()
    for i in range(50):
        noisy.add(0.76, "r", _ev(f"src/module_{i}.py"))
    assert noisy.confidence < 0.9


def test_a_trivial_repository_is_not_confidently_graded():
    """One file containing print(1) used to be graded high-risk at 0.81."""
    core = analyze_source_files([{"path": "main.py", "content": "print(1)"}])["healthCore"]

    assert core["confidence"] < source_analysis_common.HEALTH_MIN_SCORING_CONFIDENCE
    assert core["grade"] == "unknown"
    # The measurement stays readable; only the verdict is withheld.
    assert core["score"] > 0
    assert core["dimensions"]


def test_a_withheld_grade_still_reports_every_dimension_it_measured():
    core = analyze_source_files([{"path": "main.py", "content": "print(1)"}])["healthCore"]

    assert core["grade"] == "unknown"
    scored = [item for item in core["dimensions"] if item["includedInScore"]]
    assert len(scored) >= 4
    assert all(item["score"] is not None for item in scored)


def test_composite_confidence_follows_the_dimensions_rather_than_their_count():
    """Coverage said 0.81 for a repository that knew almost nothing."""
    core = analyze_source_files([{"path": "main.py", "content": "print(1)"}])["healthCore"]
    scored = [item for item in core["dimensions"] if item["includedInScore"]]

    assert core["confidence"] <= max(item["confidence"] for item in scored)


MANIFEST = json.dumps(
    {
        "manifest_version": 3,
        "name": "Example",
        "permissions": ["tabs", "storage", "webRequest"],
        "host_permissions": ["<all_urls>"],
        "content_scripts": [{"matches": ["https://*.wikipedia.org/*"]}],
        "homepage_url": "https://example.org/tool",
        "storage": {"managed_schema": "schema.json"},
    },
    indent=1,
)


def test_browser_permissions_are_collected_from_the_three_places_they_are_declared():
    report = analyze_source_files(
        [
            {"path": "manifest.json", "content": MANIFEST},
            {
                "path": "src/copy.user.js",
                "content": "\n".join(
                    [
                        "// ==UserScript==",
                        "// @grant GM_setValue",
                        "// @connect example.org",
                        "// ==/UserScript==",
                        "navigator.clipboard.writeText(text);",
                        "Notification.requestPermission();",
                    ]
                ),
            },
        ]
    )

    found = values(report, "browserPermissions")
    assert {"extension:tabs", "extension:webRequest", "host:<all_urls>"} <= found
    assert {"grant:GM_setValue", "connect:example.org"} <= found
    assert {"clipboard-write", "notifications"} <= found
    assert report["summary"]["browserPermissionCount"] == len(report["browserPermissions"])
    categories = {item["value"]: item["category"] for item in report["browserPermissions"]}
    assert categories["extension:tabs"] == "extension"
    assert categories["grant:GM_setValue"] == "user-script"
    assert categories["clipboard-write"] == "web-api"


def test_an_extension_manifest_yields_neither_its_own_keys_nor_its_plain_addresses():
    report = analyze_source_files([{"path": "manifest.json", "content": MANIFEST}])

    found = values(report, "browserPermissions")
    # "storage" is declared once as a permission and once as the section that
    # configures it; the section is not a second grant.
    assert "extension:storage" in found
    assert "host:https://example.org/tool" not in found
    assert not any(value.startswith("host:") and "*" not in value and value != "host:<all_urls>" for value in found)


def test_a_manifest_that_is_not_a_web_extension_declares_no_permissions():
    """A web app manifest carries the same filename and none of the meaning."""
    report = analyze_source_files(
        [
            {
                "path": "public/manifest.json",
                "content": json.dumps({"name": "Tool", "display": "standalone", "scope": "/", "icons": []}),
            }
        ]
    )

    assert report["browserPermissions"] == []


def test_a_feature_test_is_not_a_permission_request_and_grant_none_is_not_a_grant():
    report = analyze_source_files(
        [
            {
                "path": "src/probe.js",
                "content": "\n".join(
                    [
                        "// @grant none",
                        "if (navigator.clipboard && navigator.geolocation) { report('supported'); }",
                    ]
                ),
            }
        ]
    )

    assert report["browserPermissions"] == []


def test_browser_permissions_are_reported_under_permission_clarity_without_moving_the_score():
    files = [{"path": "src/app.js", "content": "mw.Api();"}]
    plain = analyze_source_files(files)
    with_permissions = analyze_source_files(
        [*files, {"path": "src/notify.js", "content": "Notification.requestPermission();"}]
    )

    def clarity(report):
        return next(item for item in report["assessments"] if item["key"] == "permission-clarity")

    signal = next(
        item for item in clarity(with_permissions)["signals"] if item["label"].startswith("Browser permissions")
    )
    assert signal["status"] == "neutral"
    assert "Show desktop notifications" in signal["detail"]
    assert clarity(with_permissions)["score"] == clarity(plain)["score"]


# Real lines, copied from the definition pages they were measured on rather than
# written to suit the parser: en.wikipedia's Twinkle and a Wikidata gadget with
# two rights and a default flag. A rule tested only on examples its author wrote
# agrees with its author by construction.
GADGETS_DEFINITION = """== Editing ==
* Twinkle[ResourceLoader|dependencies=mediawiki.util|rights=rollback,minoredit]|Twinkle.js|Twinkle.css
* watchlist[ResourceLoader|default|rights=viewmywatchlist]|watchlist.js
* retired[ResourceLoader|hidden]|retired.js
* sitenotice[ResourceLoader|default]|sitenotice.js
* base[ResourceLoader|default|hidden]|base.js
"""


def _gadget_report(filename: str, *, kind: str = wiki_sources.KIND_GADGET):
    declaration = wiki_sources.gadget_declaration(GADGETS_DEFINITION, filename)
    page = wiki_sources.WikiSource(domain="en.wikipedia.org", title=f"MediaWiki:Gadget-{filename}", kind=kind)
    return source_analyzer.analyze_source_files(
        [{"path": f"MediaWiki:Gadget-{filename}", "content": "var x = 1;\n"}],
        wiki_page=page,
        gadget_declaration=declaration,
    )


def test_gadget_declaration_keeps_the_line_it_was_found_on() -> None:
    declaration = wiki_sources.gadget_declaration(GADGETS_DEFINITION, "Twinkle.js")
    assert declaration is not None
    assert declaration.line_number == 2
    assert "rights=rollback,minoredit" in declaration.line
    assert declaration.entry.values("rights") == ("rollback", "minoredit")
    assert wiki_sources.gadget_declaration(GADGETS_DEFINITION, "absent.js") is None


def test_declared_rights_become_access_rights_with_definition_evidence() -> None:
    report = _gadget_report("Twinkle.js")
    rows = {row["value"]: row for row in report["accessRights"]}
    assert {"rollback", "minor-edit"} <= set(rows)
    evidence = rows["rollback"]["evidence"][0]
    assert evidence["path"] == "MediaWiki:Gadgets-definition"
    assert evidence["line"] == 2
    assert evidence["sourceClass"] == "manifest"
    assert "rollback right" in rows["rollback"]["reasons"][0]


def test_a_declared_right_alone_does_not_claim_the_tool_writes() -> None:
    # `rights=` says who the gadget is served to, not what it does. Only code
    # that was read may settle writeActionsDetected, so a restriction reported
    # on its own stays outside the write categories and leaves the flag alone.
    report = _gadget_report("Twinkle.js")
    assert report["summary"]["writeActionsDetected"] is False
    categories = {row["value"]: row["category"] for row in report["accessRights"]}
    assert categories["rollback"] == "restricted"
    assert categories["minor-edit"] == "restricted"


def _permission_clarity(report):
    return next(item for item in report["assessments"] if item["key"] == "permission-clarity")


def test_a_declared_restriction_is_not_read_as_evidence_of_being_read_only() -> None:
    # Twinkle is gated on rollback and minoredit and this copy calls neither.
    # Before the restricted category had a consumer, that landed in the
    # read-only branch and scored 90 -- a gadget the wiki gates on rollback
    # reported as safer than one whose code was actually read.
    assessment = _permission_clarity(_gadget_report("Twinkle.js"))
    labels = [signal["label"] for signal in assessment["signals"]]
    assert "Served only to users holding declared rights" in labels
    assert "Only read-oriented actions detected" not in labels
    assert assessment["score"] == 70


def test_a_tool_with_no_declared_restriction_still_reaches_the_read_only_branch() -> None:
    report = source_analyzer.analyze_source_files(
        [{"path": "app.js", "content": 'api.get({action: "query", prop: "revisions"});\n'}]
    )
    labels = [signal["label"] for signal in _permission_clarity(report)["signals"]]
    assert "Only read-oriented actions detected" in labels
    assert "Served only to users holding declared rights" not in labels


def test_an_observed_call_keeps_its_category_over_a_declaration() -> None:
    # Twinkle declares `rollback` and `minoredit`; this copy is also seen calling
    # rollback. The observed call is read first and settles that right's
    # category, while the right only declared stays a restriction.
    declaration = wiki_sources.gadget_declaration(GADGETS_DEFINITION, "Twinkle.js")
    page = wiki_sources.WikiSource(
        domain="en.wikipedia.org", title="MediaWiki:Gadget-Twinkle.js", kind=wiki_sources.KIND_GADGET
    )
    report = source_analyzer.analyze_source_files(
        [{"path": "MediaWiki:Gadget-Twinkle.js", "content": 'api.post({action: "rollback"});\n'}],
        wiki_page=page,
        gadget_declaration=declaration,
    )
    rows = {row["value"]: row for row in report["accessRights"]}
    assert rows["rollback"]["category"] == "moderation"
    assert rows["minor-edit"]["category"] == "restricted"
    assert len(rows["rollback"]["evidence"]) == 2
    assert report["summary"]["writeActionsDetected"] is True


# Real lines again, from two of the fifteen definition pages the vocabulary was
# re-measured against. MassProtect gates on `protect` and CheckUserHelper on
# `checkuser` -- the first was missing from the twenty-one-right table read off
# five wikis, the second is missing from the thirty-eight-right table read off
# twenty, which is what makes it the case that still exercises the fallback.
WIDER_DEFINITION = """== Administration ==
* MassProtect[ResourceLoader|rights=protect|dependencies=mediawiki.util,mediawiki.api]|MassProtect.js
* CheckUserHelper[ResourceLoader|rights=checkuser]|CheckUserHelper.js
"""


def _wider_gadget_report(filename: str, content: str = "var x = 1;\n"):
    declaration = wiki_sources.gadget_declaration(WIDER_DEFINITION, filename)
    assert declaration is not None
    page = wiki_sources.WikiSource(
        domain="ja.wikipedia.org", title=f"MediaWiki:Gadget-{filename}", kind=wiki_sources.KIND_GADGET
    )
    return source_analyzer.analyze_source_files(
        [{"path": f"MediaWiki:Gadget-{filename}", "content": content}],
        wiki_page=page,
        gadget_declaration=declaration,
    )


def test_a_right_the_first_measurement_missed_now_labels_and_merges() -> None:
    # `protect` was absent from the table until the definition pages were read
    # again, so this gadget's gate rendered as the bare string "protect" and
    # could not merge with the call below -- two rows for one right, one of them
    # jargon. The merge is the point of aligning the slug with ACTION_RIGHTS.
    report = _wider_gadget_report("MassProtect.js", 'api.post({action: "protect"});\n')
    rows = {row["value"]: row for row in report["accessRights"]}
    assert rows["protect"]["label"] == "Protect pages"
    assert len(rows["protect"]["evidence"]) == 2
    assert rows["protect"]["category"] == "administrator"


def test_a_right_outside_the_vocabulary_is_reported_under_its_own_name() -> None:
    assert "checkuser" not in source_analysis_common.GADGET_RIGHT_VOCABULARY
    report = _wider_gadget_report("CheckUserHelper.js")
    rows = {row["value"]: row for row in report["accessRights"]}
    assert rows["checkuser"]["label"] == "checkuser"
    assert rows["checkuser"]["category"] == "restricted"
    # Reported, and reported as undescribed. The raw name on its own reads as a
    # label the analyzer produced rather than one it never had.
    assert "no description for that right" in rows["checkuser"]["reasons"][0]
    assert rows["checkuser"]["confidence"] == pytest.approx(source_analysis_common.GADGET_DECLARED_RIGHT_CONFIDENCE)


def test_a_described_right_says_nothing_about_missing_descriptions() -> None:
    reasons = {row["value"]: row["reasons"][0] for row in _gadget_report("Twinkle.js")["accessRights"]}
    assert "no description" not in reasons["rollback"]
    assert "no description" not in reasons["minor-edit"]


def test_the_report_records_the_share_of_declared_rights_it_could_describe() -> None:
    # The drift measurement. GADGET_RIGHT_VOCABULARY is a reading of pages other
    # people edit, and nothing re-reads them; this ratio is what says when it
    # has fallen behind, rather than the table quietly going stale.
    described = _gadget_report("Twinkle.js")
    assert described["wikiPage"]["gadgetRights"] == ["rollback", "minoredit"]
    assert described["wikiPage"]["gadgetUnknownRights"] == []
    assert described["summary"]["declaredRightCount"] == 2
    assert described["summary"]["unknownDeclaredRightCount"] == 0

    undescribed = _wider_gadget_report("CheckUserHelper.js")
    assert undescribed["wikiPage"]["gadgetUnknownRights"] == ["checkuser"]
    assert undescribed["summary"]["declaredRightCount"] == 1
    assert undescribed["summary"]["unknownDeclaredRightCount"] == 1


def test_a_tool_with_no_definition_line_declares_no_rights_to_count() -> None:
    # Zero out of zero, not one out of zero: a repository that is not a gadget
    # must not push the rate around.
    summary = source_analyzer.analyze_source_files([{"path": "app.js", "content": "var x = 1;\n"}])["summary"]
    assert summary["declaredRightCount"] == 0
    assert summary["unknownDeclaredRightCount"] == 0


REACH_LABELS = {label for label, _detail in source_analysis_assessments.GADGET_REACH_CASES.values()}


def _reach_signals(report) -> list[dict]:
    """Return only the reach signals, so a test asserting one is not fooled by another."""
    return [
        signal
        for assessment in report["assessments"]
        if assessment["key"] == "permission-clarity"
        for signal in assessment["signals"]
        if signal["label"] in REACH_LABELS
    ]


EXTENSION_MANIFEST = json.dumps(
    {
        "manifest_version": 3,
        "permissions": ["tabs", "cookies", "history", "storage", "scripting", "webRequest"],
        "host_permissions": ["<all_urls>"],
    }
)


def _browser_permissions(report):
    return next((item for item in report["assessments"] if item["key"] == "browser-permissions"), None)


def _browser_dimension(report):
    return next(item for item in report["healthCore"]["dimensions"] if item["key"] == "browser-permissions")


def test_a_tool_that_asks_the_browser_for_nothing_is_not_graded_on_it() -> None:
    # None rather than a perfect score: "asked for nothing" and "does not run in
    # a browser" are the same absence here, and a backend script handed a top
    # mark would be told it passed a test it never sat.
    report = source_analyzer.analyze_source_files([{"path": "app.py", "content": "print(1)\n"}])
    assert _browser_permissions(report) is None
    dimension = _browser_dimension(report)
    assert dimension["applicable"] is False
    assert dimension["includedInScore"] is False


def test_a_device_permission_outscores_nothing_it_is_bundled_with() -> None:
    report = source_analyzer.analyze_source_files(
        [{"path": "MediaWiki:Gadget-cam.js", "content": "navigator.mediaDevices.getUserMedia({video: true});\n"}]
    )
    assessment = _browser_permissions(report)
    assert assessment is not None
    assert assessment["score"] == 45
    assert [signal["label"] for signal in assessment["signals"]] == ["Reaches hardware, files, or stored credentials"]


def test_a_permission_that_stays_in_the_page_is_scored_as_such() -> None:
    report = source_analyzer.analyze_source_files(
        [{"path": "MediaWiki:Gadget-copy.js", "content": "navigator.clipboard.writeText(x);\n"}]
    )
    assessment = _browser_permissions(report)
    assert assessment is not None
    assert assessment["score"] == 85
    assert assessment["signals"][0]["status"] == "positive"


def test_breadth_and_every_site_access_both_cost_the_extension_something() -> None:
    report = source_analyzer.analyze_source_files([{"path": "manifest.json", "content": EXTENSION_MANIFEST}])
    assessment = _browser_permissions(report)
    assert assessment is not None
    # 65 for reaching other sites, -15 for seven separate requests, -15 for
    # every-site access.
    assert assessment["score"] == 35
    labels = [signal["label"] for signal in assessment["signals"]]
    assert "Asks to run on every site the reader visits" in labels
    assert "A long list of separate permissions" in labels


def test_the_browser_dimension_leaves_a_tool_without_permissions_where_it_was() -> None:
    # The dimension must be absent, not zero: an added dimension that scored the
    # absence would restate every catalogued tool's health without the tool
    # having changed.
    files = [{"path": "src/bot.py", "content": 'requests.post(url, data={"action": "edit"})\n'}]
    report = source_analyzer.analyze_source_files(files)
    applicable = {item["key"] for item in report["healthCore"]["dimensions"] if item["applicable"]}
    assert "browser-permissions" not in applicable
    # Confidence divides by the applicable weight, so a dimension that was
    # merely absent rather than inapplicable would move it for every such tool.
    assert sum(
        float(item["weight"]) for item in report["healthCore"]["dimensions"] if item["applicable"]
    ) == pytest.approx(6.25)


STYLESHEET = """@import url("https://fonts.googleapis.com/css2?family=Lato");
.box { background: url(https://cdn.example.org/bg.png) no-repeat; }
@font-face { src: url(//fonts.gstatic.com/s/lato/v1.woff2) format("woff2"); }
.logo { background: url(//upload.wikimedia.org/wikipedia/commons/a/b.svg); }
.local { background: url(/w/images/x.png); }
"""


def _stylesheet_warning(report):
    rows = [row for row in report["warnings"] if row["value"] == "stylesheet-third-party-request"]
    return rows[0] if rows else None


def test_a_stylesheet_names_the_third_party_hosts_it_fetches_from() -> None:
    # `url()` to an image and a protocol-relative webfont are exactly what the
    # endpoint bucket's static-asset filter removes, which is why they are
    # reported here instead of being lost between the two.
    report = source_analyzer.analyze_source_files([{"path": "MediaWiki:Gadget-Foo.css", "content": STYLESHEET}])
    row = _stylesheet_warning(report)
    assert row is not None
    assert row["category"] == "privacy"
    hosts = {evidence["match"] for evidence in row["evidence"]}
    assert hosts == {"fonts.googleapis.com", "cdn.example.org", "fonts.gstatic.com"}


def test_a_stylesheet_stays_quiet_about_wikimedia_and_relative_addresses() -> None:
    css = ".logo { background: url(//upload.wikimedia.org/a.svg); }\n.x { background: url(/w/i.png); }\n"
    report = source_analyzer.analyze_source_files([{"path": "MediaWiki:Gadget-Foo.css", "content": css}])
    assert _stylesheet_warning(report) is None


def test_only_stylesheets_are_read_as_stylesheets() -> None:
    # The same text inside a script is a string, not a request the browser makes.
    report = source_analyzer.analyze_source_files(
        [{"path": "app.js", "content": 'var s = "url(https://cdn.example.org/a.png)";\n'}]
    )
    assert _stylesheet_warning(report) is None


def test_declared_modules_become_dependencies_in_their_own_ecosystem() -> None:
    # A gadget has no package.json, so `dependencies=` is its whole manifest.
    report = _gadget_report("Twinkle.js")
    rows = {row["value"]: row for row in report["dependencies"]}
    assert "resourceloader:mediawiki.util" in rows
    row = rows["resourceloader:mediawiki.util"]
    assert row["label"] == "mediawiki.util (resourceloader)"
    assert row["category"] == "runtime"
    assert row["evidence"][0]["path"] == "MediaWiki:Gadgets-definition"


def test_a_gadget_that_declares_no_modules_gets_no_dependency_rows() -> None:
    report = _gadget_report("retired.js")
    assert [row for row in report["dependencies"] if row["value"].startswith("resourceloader:")] == []


def test_the_action_api_module_is_read_as_the_action_api() -> None:
    # `mediawiki.api` is the ResourceLoader spelling of the client the npm and
    # pypi rules already recognise, so it must reach the same apis finding
    # rather than stopping at being a dependency name.
    definition = "* tool[ResourceLoader|dependencies=mediawiki.api,mediawiki.util]|tool.js\n"
    declaration = wiki_sources.gadget_declaration(definition, "tool.js")
    page = wiki_sources.WikiSource(
        domain="en.wikipedia.org", title="MediaWiki:Gadget-tool.js", kind=wiki_sources.KIND_GADGET
    )
    report = source_analyzer.analyze_source_files(
        [{"path": "MediaWiki:Gadget-tool.js", "content": "var x = 1;\n"}],
        wiki_page=page,
        gadget_declaration=declaration,
    )
    assert "mediawiki-action-api" in {row["value"] for row in report["apis"]}


def test_default_is_reported_as_reach_and_not_as_a_right() -> None:
    report = _gadget_report("sitenotice.js")
    assert report["wikiPage"]["gadgetDefault"] is True
    assert report["wikiPage"]["gadgetScope"] == []
    assert "default" not in {row["value"] for row in report["accessRights"]}
    assert [signal["label"] for signal in _reach_signals(report)] == ["Enabled for all users by default"]


def test_a_scoped_default_does_not_claim_the_whole_wiki() -> None:
    # watchlist is `default|rights=viewmywatchlist`. Of the 85 `default` entries
    # measured across five wikis only 16 are unqualified, so treating every
    # `default` as "all readers" would overstate the majority of them.
    report = _gadget_report("watchlist.js")
    assert report["wikiPage"]["gadgetScope"] == ["rights"]
    signal = _reach_signals(report)[0]
    assert signal["label"] == "Enabled by default for part of the wiki"
    assert "limits it by user right" in signal["detail"]


def test_default_and_hidden_together_say_the_reader_cannot_refuse_it() -> None:
    report = _gadget_report("base.js")
    assert report["wikiPage"]["gadgetDefault"] is True
    assert report["wikiPage"]["gadgetHidden"] is True
    signal = _reach_signals(report)[0]
    assert signal["label"] == "Always on and not listed in preferences"
    assert "none of them can turn it off" in signal["detail"]


def test_hidden_alone_reports_that_nobody_can_switch_it_on() -> None:
    report = _gadget_report("retired.js")
    assert report["wikiPage"]["gadgetDefault"] is False
    assert report["wikiPage"]["gadgetHidden"] is True
    assert [signal["label"] for signal in _reach_signals(report)] == ["Not listed in gadget preferences"]


def test_an_opt_in_gadget_says_so_rather_than_saying_nothing() -> None:
    report = _gadget_report("Twinkle.js")
    assert report["wikiPage"]["gadgetDefault"] is False
    assert report["wikiPage"]["gadgetHidden"] is False
    assert _reach_signals(report) == []


def test_a_clone_has_no_gadget_row_at_all() -> None:
    report = source_analyzer.analyze_source_files([{"path": "src/app.js", "content": "var x = 1;\n"}])
    assert report["wikiPage"] == {}
    assert "gadgetDefault" not in report["wikiPage"]
    assert "gadgetHidden" not in report["wikiPage"]


def test_an_unmeasured_right_is_reported_rather_than_dropped() -> None:
    definition = "* tool[ResourceLoader|rights=abusefilter-modify]|tool.js\n"
    declaration = wiki_sources.gadget_declaration(definition, "tool.js")
    page = wiki_sources.WikiSource(
        domain="en.wikipedia.org", title="MediaWiki:Gadget-tool.js", kind=wiki_sources.KIND_GADGET
    )
    report = source_analyzer.analyze_source_files(
        [{"path": "MediaWiki:Gadget-tool.js", "content": "var x = 1;\n"}],
        wiki_page=page,
        gadget_declaration=declaration,
    )
    rows = {row["value"]: row for row in report["accessRights"]}
    assert rows["abusefilter-modify"]["label"] == "abusefilter-modify"
    assert rows["abusefilter-modify"]["category"] == "restricted"


def test_the_definition_page_is_trusted_like_a_manifest() -> None:
    assert source_analyzer._source_class("MediaWiki:Gadgets-definition") == "manifest"
    # One sighting on it is a statement, so a declared right reaches published
    # metadata without needing a second file to agree.
    report = _gadget_report("Twinkle.js")
    assert "rollback" in report["suggestions"]["evolvedMetadata"]["access_rights"]


def test_repository_context_reports_authorship_from_the_paths_it_was_given():
    report = analyze_source_files(
        [
            {"path": "CLAUDE.md", "content": "Run npm test before committing."},
            {"path": "src/app.js", "content": "console.log('hi');"},
        ],
        tool_name="example-tool",
        source_label="https://github.com/example/tool",
    )

    authorship = report["repositoryContext"]["authorship"]
    assert authorship["llmAssisted"] is True
    assert authorship["provider"] == "anthropic"


def test_a_caller_cannot_assert_authorship_through_the_supplied_context():
    # This lane analyzes files supplied in a request body, so a caller already
    # chooses the input. What it must not get is a way to state the conclusion
    # directly: "this tool was written by an LLM" is a claim about somebody
    # else's tool, and no file here supports it.
    report = analyze_source_files(
        [{"path": "src/app.js", "content": "console.log('hi');"}],
        tool_name="example-tool",
        source_label="https://github.com/example/tool",
        repository_context={
            "repository": {"url": "https://github.com/example/tool"},
            "authorship": {
                "llmAssisted": True,
                "provider": "anthropic",
                "model": "Claude Opus 5",
                "signals": [{"kind": "marker", "provider": "anthropic", "evidence": "invented"}],
            },
        },
    )

    authorship = report["repositoryContext"]["authorship"]
    assert authorship["llmAssisted"] is None
    assert authorship["provider"] == ""
    assert authorship["signals"] == []
