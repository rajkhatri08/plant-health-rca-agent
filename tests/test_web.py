"""web/index.html and web/vercel.json: static checks (the page's text is also leak-scanned
in tests/test_leak_scan.py)."""

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PAGE = (REPO / "web" / "index.html").read_text()


def test_api_base_is_one_marked_constant_and_local_uses_127():
    assert PAGE.count("const RENDER_API_URL = ") == 1
    assert "Fill this in after the Render deploy" in PAGE
    assert 'LOCAL_HOSTS.includes(location.hostname) ? "http://127.0.0.1:8000" : RENDER_API_URL' in PAGE


def test_says_advisory_and_watch_not_built():
    assert "Advisory only." in PAGE and "never changes plant controls" in PAGE
    assert "Watch band isn't built yet" in PAGE


def test_calls_only_the_read_routes():
    routes = set(re.findall(r'getJSON\([`"](/[a-z/]+)', PAGE))
    assert routes == {"/health", "/replay/info", "/replay/status"}
    assert "method:" not in PAGE                     # fetch defaults to GET


def test_no_external_scripts_styles_or_urls():
    assert "<script src" not in PAGE and "<link" not in PAGE
    urls = set(re.findall(r"https?://[^\s\"'`)]+", PAGE))
    assert urls <= {"http://127.0.0.1:8000", "https://REPLACE-WITH-YOUR-SERVICE.onrender.com"}


def test_never_names_a_run_or_label():
    assert not re.search(r"\b(run|fault)\s*(number|no\.?|#|\d)", PAGE, re.IGNORECASE)


def test_vercel_config_is_static():
    cfg = json.loads((REPO / "web" / "vercel.json").read_text())
    assert not {"builds", "functions", "rewrites"} & set(cfg)
