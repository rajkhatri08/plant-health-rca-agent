"""app/api.py's /diagnosis (week 6 S9) on a synthetic demo (tests/demo_helpers.py): the contract,
the as-of rule, ReplayClient refusing a miss, the leak scan on every response, and the replay
routes unaffected when the demo isn't there."""

import json
import shutil
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app import api
from app.agent import demo
from app.detector import replay
from tests import demo_helpers as dh
from tests.test_leak_scan import find_leaks


@pytest.fixture
def built(tmp_path):
    d, b, csv_path, fake = dh.build_demo_dir(tmp_path)
    return {"dir": d, "bundle_dir": tmp_path / "pca_v3", "csv": csv_path,
            "notified": replay.parse_ts(json.loads((d / demo.CONFIG).read_text())["notified_at"])}


def client(b, demo_dir=None):
    return TestClient(api.create_app(b["bundle_dir"], b["csv"], allowed_origins=[], demo_dir=demo_dir or b["dir"]))


def ts(t):
    return t.strftime(replay.TS_FORMAT)


def test_health_reports_the_diagnosis_ready(built):
    with client(built) as c:
        h = c.get("/health").json()
    assert h["status"] == "ok" and h["diagnosis"] == "ready"


def test_the_contract_before_and_after_the_alert(built):
    n = built["notified"]
    with client(built) as c:
        before = c.get("/diagnosis", params={"upto": ts(n - timedelta(minutes=3))}).json()
        waiting = c.get("/diagnosis", params={"upto": ts(n + timedelta(minutes=15))}).json()
        prov = c.get("/diagnosis", params={"upto": ts(n + timedelta(minutes=30)), "note": "none"}).json()
        rev = c.get("/diagnosis", params={"upto": ts(n + timedelta(minutes=60))}).json()
    assert before["available"] is False and "alert_at" not in before and "diagnosis" not in before
    assert waiting["available"] is False and waiting["available_from"] == ts(n + timedelta(minutes=30))
    assert prov["available"] is True and prov["stage"] == "provisional" and prov["note"] == "none"
    assert prov["diagnosis"]["stage"] == "provisional" and prov["revised_from"] == ts(n + timedelta(minutes=60))
    assert rev["stage"] == "revised" and rev["diagnosis"]["stage"] == "revised"
    for r in (before, waiting, prov, rev):
        assert r["advisory"] == demo.ADVISORY and r["precomputed"] == demo.PRECOMPUTED


def test_the_emergency_note_shows_only_the_procedure(built):
    n = built["notified"]
    with client(built) as c:
        r = c.get("/diagnosis", params={"upto": ts(n + timedelta(minutes=30)), "note": "emergency"}).json()
    d = r["diagnosis"]
    assert d["outcome"] == "emergency" and "site emergency procedure" in d["message"]
    assert "proposal" not in d and "matcher_top" not in d and "dissent" not in d


@pytest.mark.parametrize("params, status", [
    ({"upto": "2026-01-05T08:00:00Z", "note": "anything typed"}, 422),     # no free text
    ({"upto": "yesterday"}, 422),
    ({}, 422),
])
def test_bad_requests(built, params, status):
    with client(built) as c:
        assert c.get("/diagnosis", params=params).status_code == status


def test_every_response_is_clean(built):
    n = built["notified"]
    times = [n + timedelta(minutes=m) for m in (-60, -3, 0, 15, 30, 45, 60, 120)]
    with client(built) as c:
        bodies = [c.get("/health").text, c.get("/replay/info").text,
                  c.get("/replay/status", params={"upto": ts(times[-1])}).text]
        for note in demo.NOTES:
            for t in times:
                r = c.get("/diagnosis", params={"upto": ts(t), "note": note})
                assert r.status_code == 200
                bodies.append(r.text)
    assert all(find_leaks(b) == [] for b in bodies)
    # no raw value: the only numbers in a diagnosis are times and tag IDs (states only)
    for b in bodies[3:]:
        assert '"ratio"' not in b and '"value"' not in b


def test_a_missing_answer_makes_only_the_diagnosis_unavailable(built):
    shutil.rmtree(built["dir"] / demo.CACHE)
    (built["dir"] / demo.CACHE).mkdir()                                       # ReplayClient will miss
    with client(built) as c:
        h = c.get("/health").json()
        d = c.get("/diagnosis", params={"upto": ts(built["notified"] + timedelta(minutes=30))})
        s = c.get("/replay/status", params={"upto": ts(built["notified"])})
    assert h["status"] == "ok" and h["diagnosis"].startswith("unavailable: CacheMiss")
    assert d.status_code == 503 and "CacheMiss" in d.json()["detail"]
    assert s.status_code == 200                                               # the replay is unaffected


def test_no_demo_built_keeps_the_replay_working(built, tmp_path):
    with client(built, demo_dir=tmp_path / "nothing") as c:
        assert c.get("/health").json()["diagnosis"].startswith("unavailable: DemoError")
        assert c.get("/diagnosis", params={"upto": "2026-01-05T08:00:00Z"}).status_code == 503
        assert c.get("/replay/info").status_code == 200


def test_the_demo_never_records_an_approval_or_an_action(built):
    # The API builds the views in a temporary folder; demo.build_views refuses to return if an
    # approval or act record exists, and no route can resume an episode.
    routes = {r.path for r in api.create_app(built["bundle_dir"], built["csv"], allowed_origins=[],
                                             demo_dir=built["dir"]).routes}
    assert {"/health", "/replay/info", "/replay/status", "/diagnosis"} <= routes
    assert not any(p.startswith(("/approve", "/decide", "/act")) for p in routes)


def test_only_get_routes():
    for r in api.create_app(allowed_origins=[]).routes:
        if hasattr(r, "methods") and r.path in ("/health", "/replay/info", "/replay/status", "/diagnosis"):
            assert r.methods <= {"GET", "HEAD"}