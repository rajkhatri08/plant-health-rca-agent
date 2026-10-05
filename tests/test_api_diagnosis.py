"""app/api.py's episodes and /diagnosis (week 6 S9) on a synthetic two-episode demo
(tests/demo_helpers.py): the contract, the as-of rule, ReplayClient refusing a miss, the leak scan
on every response, episodes labelled by number only, and the replay unaffected when the demo or
episode 2 isn't there."""

import json
import re
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
    d, b, streams, fake = dh.build_demo_dir(tmp_path)
    cfg = json.loads((d / demo.CONFIG).read_text())
    return {"dir": d, "bundle_dir": tmp_path / "pca_v3", "streams": streams,
            "notified": {e: replay.parse_ts(cfg["episodes"][e]["notified_at"]) for e in demo.EPISODES}}


def client(b, demo_dir=None, csv=None):
    return TestClient(api.create_app(b["bundle_dir"], csv or b["streams"]["1"], allowed_origins=[],
                                     demo_dir=demo_dir or b["dir"]))


def ts(t):
    return t.strftime(replay.TS_FORMAT)


def test_health_lists_the_episodes_by_number_and_the_diagnosis_ready(built):
    with client(built) as c:
        h = c.get("/health").json()
    assert h["status"] == "ok" and h["diagnosis"] == "ready"
    assert h["episodes"] == [{"id": "1", "label": "Episode 1"}, {"id": "2", "label": "Episode 2"}]


@pytest.mark.parametrize("episode", ["1", "2"])
def test_each_episode_has_its_own_stream(built, episode):
    with client(built) as c:
        info = c.get("/replay/info", params={"episode": episode}).json()
        st = c.get("/replay/status", params={"upto": info["end"], "episode": episode}).json()
    assert info["episode"] == {"id": episode, "label": f"Episode {episode}"} and info["samples"] == dh.SAMPLES
    first_alert = next(s["ts"] for s in st["samples"] if s["band"] == "Alert")
    assert first_alert == ts(built["notified"][episode])


@pytest.mark.parametrize("episode", ["1", "2"])
def test_the_contract_before_and_after_the_alert(built, episode):
    n = built["notified"][episode]
    get = lambda c, m, note="none": c.get("/diagnosis", params={"upto": ts(n + timedelta(minutes=m)), "note": note,
                                                                 "episode": episode}).json()
    with client(built) as c:
        before, waiting, prov, rev = get(c, -3), get(c, 15), get(c, 30), get(c, 60)
    assert before["available"] is False and "alert_at" not in before and "diagnosis" not in before
    assert waiting["available"] is False and waiting["available_from"] == ts(n + timedelta(minutes=30))
    assert prov["available"] is True and prov["stage"] == "provisional" and prov["diagnosis"]["stage"] == "provisional"
    assert rev["stage"] == "revised" and rev["diagnosis"]["stage"] == "revised"
    for r in (before, waiting, prov, rev):
        assert r["episode"] == {"id": episode, "label": f"Episode {episode}"}
        assert r["advisory"] == demo.ADVISORY and r["precomputed"] == demo.PRECOMPUTED


def test_the_as_of_rule_is_per_episode(built):
    # Episode 2's alert comes later: at episode 1's +30 min, episode 2 has nothing yet.
    n1, n2 = built["notified"]["1"], built["notified"]["2"]
    assert n2 > n1 + timedelta(minutes=30)
    with client(built) as c:
        r1 = c.get("/diagnosis", params={"upto": ts(n1 + timedelta(minutes=30)), "episode": "1"}).json()
        r2 = c.get("/diagnosis", params={"upto": ts(n1 + timedelta(minutes=30)), "episode": "2"}).json()
    assert r1["available"] is True and r2["available"] is False and "alert_at" not in r2


def test_the_emergency_note_shows_only_the_procedure_in_both_episodes(built):
    with client(built) as c:
        for e, n in built["notified"].items():
            d = c.get("/diagnosis", params={"upto": ts(n + timedelta(minutes=30)), "note": "emergency",
                                            "episode": e}).json()["diagnosis"]
            assert d["outcome"] == "emergency" and "site emergency procedure" in d["message"]
            assert "proposal" not in d and "matcher_top" not in d and "dissent" not in d


@pytest.mark.parametrize("path, params, status", [
    ("/diagnosis", {"upto": "2026-01-05T08:00:00Z", "note": "anything typed"}, 422),     # no free text
    ("/diagnosis", {"upto": "yesterday"}, 422),
    ("/diagnosis", {}, 422),
    ("/diagnosis", {"upto": "2026-01-05T08:00:00Z", "episode": "3"}, 422),
    ("/replay/info", {"episode": "fault 4"}, 422),
    ("/replay/status", {"upto": "2026-01-05T08:00:00Z", "episode": "0"}, 422),
])
def test_bad_requests(built, path, params, status):
    with client(built) as c:
        assert c.get(path, params=params).status_code == status


def test_every_response_is_clean_and_names_no_fault(built):
    bodies = []
    with client(built) as c:
        bodies += [c.get("/health").text]
        for e, n in built["notified"].items():
            times = [n + timedelta(minutes=m) for m in (-60, -3, 0, 15, 30, 45, 60, 120)]
            bodies += [c.get("/replay/info", params={"episode": e}).text,
                       c.get("/replay/status", params={"upto": ts(times[-1]), "episode": e}).text]
            for note in demo.NOTES:
                for t in times:
                    r = c.get("/diagnosis", params={"upto": ts(t), "note": note, "episode": e})
                    assert r.status_code == 200
                    bodies.append(r.text)
    assert all(find_leaks(b) == [] for b in bodies)
    for b in bodies:
        labels = re.findall(r'"label":\s*"([^"]*)"', b)
        assert set(labels) <= {"Episode 1", "Episode 2"}                     # an episode is a number, never a fault
        assert "masked" not in b.lower()


def test_a_missing_answer_makes_only_the_diagnosis_unavailable(built):
    shutil.rmtree(built["dir"] / demo.CACHE)
    (built["dir"] / demo.CACHE).mkdir()                                       # ReplayClient will miss
    with client(built) as c:
        h = c.get("/health").json()
        d = c.get("/diagnosis", params={"upto": ts(built["notified"]["1"] + timedelta(minutes=30))})
        s = c.get("/replay/status", params={"upto": ts(built["notified"]["2"]), "episode": "2"})
    assert h["status"] == "ok" and h["diagnosis"].startswith("unavailable: CacheMiss")
    assert d.status_code == 503 and "CacheMiss" in d.json()["detail"]
    assert s.status_code == 200                                               # the replay is unaffected


def test_without_episode_2_episode_1_still_replays(built):
    (built["dir"] / demo.EPISODES["2"]).unlink()
    with client(built) as c:
        h = c.get("/health").json()
        assert h["episodes"] == [{"id": "1", "label": "Episode 1"}] and h["diagnosis"].startswith("unavailable")
        assert c.get("/replay/info", params={"episode": "1"}).status_code == 200
        assert c.get("/replay/info", params={"episode": "2"}).status_code == 503


def test_no_demo_built_keeps_the_replay_working(built, tmp_path):
    with client(built, demo_dir=tmp_path / "nothing") as c:
        assert c.get("/health").json()["diagnosis"].startswith("unavailable: DemoError")
        assert c.get("/diagnosis", params={"upto": "2026-01-05T08:00:00Z"}).status_code == 503
        assert c.get("/replay/info").status_code == 200


def test_the_demo_never_records_an_approval_or_an_action(built):
    routes = {r.path for r in api.create_app(built["bundle_dir"], built["streams"]["1"], allowed_origins=[],
                                             demo_dir=built["dir"]).routes}
    assert {"/health", "/replay/info", "/replay/status", "/diagnosis"} <= routes
    assert not any(p.startswith(("/approve", "/decide", "/act")) for p in routes)


def test_only_get_routes():
    for r in api.create_app(allowed_origins=[]).routes:
        if hasattr(r, "methods") and r.path in ("/health", "/replay/info", "/replay/status", "/diagnosis"):
            assert r.methods <= {"GET", "HEAD"}