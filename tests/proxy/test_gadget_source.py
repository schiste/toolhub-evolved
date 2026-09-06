# SPDX-License-Identifier: GPL-3.0-or-later
"""Reading a gadget's own code, so its inference lane has evidence to read.

The lane's other text is the description message: 83 characters at the median
and absent for 2,726 of 12,777 gadgets. It supports `keywords` and `audiences`
and nothing else, which is why every gadget's code is fetched here instead.
"""

import sys
from pathlib import Path

import pytest
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import db, gadget_source  # noqa: E402
from backend.models import WikiGadget  # noqa: E402


@pytest.fixture(autouse=True)
def database():
    db.configure("sqlite://")
    db.init_schema()


def _gadget(name="HotCat", pages=("HotCat.js",), **fields):
    return WikiGadget(wiki="en.wikipedia.org", name=name, name_key=name.casefold(), pages=list(pages), **fields)


def _bodies(mapping):
    """Stand in for the wiki, returning page text by full title."""

    def _fetch(_http, gadget):
        titles = gadget_source._titles(gadget)
        return "\n\n".join(f"/* {t} */\n{mapping[t]}" for t in titles if mapping.get(t))

    return _fetch


def test_a_gadgets_pages_are_read_and_kept(monkeypatch):
    with db.session_scope() as s:
        s.add(_gadget())
    monkeypatch.setattr(
        gadget_source, "_body_for", _bodies({"MediaWiki:Gadget-HotCat.js": "var hotcat = 1;"})
    )

    summary = gadget_source.refresh(limit=10)

    assert summary["stored"] == 1
    with db.session_scope() as s:
        stored = s.execute(select(WikiGadget)).scalar_one()
        assert "var hotcat = 1;" in stored.body
        assert stored.body_fingerprint == gadget_source.fingerprint(stored.body)
        assert stored.body_fetched_at is not None


def test_pages_are_concatenated_in_the_order_the_definition_lists_them(monkeypatch):
    """`titles` promises no ordering, and a body that reshuffled itself would
    change its own fingerprint without the gadget changing at all."""
    with db.session_scope() as s:
        s.add(_gadget(pages=("A.js", "B.js")))
    monkeypatch.setattr(
        gadget_source,
        "_body_for",
        _bodies({"MediaWiki:Gadget-A.js": "first", "MediaWiki:Gadget-B.js": "second"}),
    )

    gadget_source.refresh(limit=10)

    with db.session_scope() as s:
        body = s.execute(select(WikiGadget)).scalar_one().body
    assert body.index("first") < body.index("second")


def test_an_unchanged_gadget_costs_nothing_downstream(monkeypatch):
    """The fingerprint is what stops a re-read invalidating a good inference."""
    with db.session_scope() as s:
        s.add(_gadget())
    monkeypatch.setattr(gadget_source, "_body_for", _bodies({"MediaWiki:Gadget-HotCat.js": "same"}))

    gadget_source.refresh(limit=10)
    second = gadget_source.refresh(limit=10)

    assert second["unchanged"] == 1
    assert second["stored"] == 0


def test_one_unreadable_wiki_does_not_end_the_pass(monkeypatch):
    """The rest of the run's gadgets are on other wikis and still readable."""
    with db.session_scope() as s:
        s.add(_gadget(name="Broken", pages=("Broken.js",)))
        s.add(_gadget(name="Fine", pages=("Fine.js",)))

    def _sometimes(_http, gadget):
        if gadget.name == "Broken":
            raise gadget_source.GadgetSourceError("maxlag")
        return "/* Fine */\nok"

    monkeypatch.setattr(gadget_source, "_body_for", _sometimes)

    summary = gadget_source.refresh(limit=10)

    assert summary["failed"] == 1
    assert summary["stored"] == 1


def test_a_gadget_whose_pages_are_all_missing_is_not_re_read_forever(monkeypatch):
    """Stamped even when empty, or the oldest-first walk never moves past it."""
    with db.session_scope() as s:
        s.add(_gadget())
    monkeypatch.setattr(gadget_source, "_body_for", _bodies({}))

    summary = gadget_source.refresh(limit=10)

    assert summary["empty"] == 1
    with db.session_scope() as s:
        assert s.execute(select(WikiGadget)).scalar_one().body_fetched_at is not None


def test_a_gadget_naming_no_pages_asks_the_wiki_nothing():
    assert gadget_source._titles(_gadget(pages=())) == ()
    assert gadget_source._titles(_gadget(pages=("  ",))) == ()


def test_titles_carry_the_gadget_namespace():
    assert gadget_source._titles(_gadget(pages=("HotCat.js",))) == ("MediaWiki:Gadget-HotCat.js",)


# ---- The fetch itself, not a stand-in for it -------------------------------
# The tests above replace `_body_for` to exercise the pass; these exercise the
# reading, because a wiki that answers with an error object and HTTP 200 is the
# case that would otherwise store "this gadget has no code".


def _payload(pages):
    return {"query": {"pages": [
        {"title": title, "revisions": [{"revid": 1, "timestamp": "2026-01-01T00:00:00Z", "slots": {
            "main": {"content": content}}}]}
        for title, content in pages.items()
    ]}}


def test_a_wiki_refusing_the_query_is_a_failure_not_an_empty_gadget(monkeypatch):
    """The Action API reports errors with HTTP 200 and an error object, so a
    caller checking only the status stores a lagged wiki as a gadget with no
    code -- and empty is indistinguishable from never read."""
    monkeypatch.setattr(
        gadget_source.outbound, "fetch_bounded", lambda *a, **k: b'{"error": {"code": "maxlag"}}'
    )

    with pytest.raises(gadget_source.GadgetSourceError, match="maxlag"):
        gadget_source._query(None, "https://en.wikipedia.org/w/api.php")


def test_the_reading_concatenates_the_pages_the_definition_names(monkeypatch):
    import json as _json

    monkeypatch.setattr(
        gadget_source.outbound,
        "fetch_bounded",
        lambda *a, **k: _json.dumps(
            _payload({"MediaWiki:Gadget-B.js": "second", "MediaWiki:Gadget-A.js": "first"})
        ).encode(),
    )

    body = gadget_source._body_for(None, _gadget(pages=("A.js", "B.js")))

    # Definition order, though the wiki answered in the other one.
    assert body.index("first") < body.index("second")
    assert "MediaWiki:Gadget-A.js" in body


def test_a_page_the_wiki_does_not_have_is_left_out_rather_than_blank(monkeypatch):
    import json as _json

    monkeypatch.setattr(
        gadget_source.outbound,
        "fetch_bounded",
        lambda *a, **k: _json.dumps(_payload({"MediaWiki:Gadget-A.js": "only this"})).encode(),
    )

    body = gadget_source._body_for(None, _gadget(pages=("A.js", "Missing.js")))

    assert "only this" in body
    assert "Missing" not in body


def test_a_gadget_naming_no_pages_is_not_asked_about(monkeypatch):
    """No titles means no request at all, rather than a query for nothing."""
    def _explode(*_a, **_k):
        raise AssertionError("asked the wiki about a gadget with no pages")

    monkeypatch.setattr(gadget_source.outbound, "fetch_bounded", _explode)
    assert gadget_source._body_for(None, _gadget(pages=())) == ""


def test_a_run_with_nothing_to_read_reports_so():
    assert gadget_source.refresh(limit=10)["examined"] == 0
