"""Security-header assertions for the Toolforge proxy (proxy/app.py).

The CSP test recomputes the inline theme-script hash from index.html and asserts
the proxy's CSP carries it, so the hash can never silently drift out of sync.
"""

import base64
import hashlib
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import app as proxy_app  # noqa: E402  (path injected above)


@pytest.fixture
def client():
    proxy_app.app.config["TESTING"] = True
    return proxy_app.app.test_client()


def test_baseline_security_headers(client):
    resp = client.get("/")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert "max-age=" in resp.headers["Strict-Transport-Security"]
    assert "geolocation=()" in resp.headers["Permissions-Policy"]


def test_csp_is_strict_and_matches_inline_script(client):
    html = (ROOT / "public_html" / "index.html").read_text(encoding="utf-8")
    inline = re.findall(r"<script>([\s\S]*?)</script>", html)
    assert len(inline) == 1, "index.html must have exactly one inline <script> (the CSP carries one hash)"
    digest = base64.b64encode(hashlib.sha256(inline[0].encode("utf-8")).digest()).decode()

    csp = client.get("/").headers["Content-Security-Policy"]
    script_src = next(d for d in csp.split(";") if d.strip().startswith("script-src"))
    assert f"sha256-{digest}" in script_src, "CSP script-src hash is stale vs the index.html inline script"
    assert "'unsafe-inline'" not in script_src, "script-src must stay strict (no unsafe-inline)"
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp
