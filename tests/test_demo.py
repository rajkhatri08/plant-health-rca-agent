"""app/agent/demo.py: the public demo's diagnosis (week 6 S9). Synthetic bundle and stream, the
committed library, Raj's real prompt template, FakeClient answers behind the cache; ReplayClient
for serving. Never the API, never data/."""

import json
import shutil
from datetime import timedelta

import pytest

from app.agent import demo, llm
from app.agent import graph as ag
from app.detector import replay
from app.library import store
from shared.leak_scan import find_leaks
from tests import agent_helpers as ah
from tests import demo_helpers as dh


@pytest.fixture
def built(tmp_path):
    d, b, streams, fake = dh.build_demo_dir(tmp_path)
    return {"dir": d, "bundle": b, "streams": streams, "fake": fake}


def start(b, **kw):
    """Episode 1's (views, notified_at), the shape most tests read."""
    out = demo.start_demo(b["bundle"], b["dir"], **kw)
    return out["1"]["views"], out["1"]["notified_at"]


# ---------- serving from the cache ----------

def test_the_api_side_rebuilds_both_episodes_from_the_cache_alone(built):
    out = demo.start_demo(built["bundle"], built["dir"])
    cfg = json.loads((built["dir"] / demo.CONFIG).read_text())
    assert set(out) == set(demo.EPISODES) == {"1", "2"}
    for e, ep in out.items():
        assert set(ep["views"]) == set(demo.NOTES) and all(set(v) == set(ag.STAGES) for v in ep["views"].values())
        assert ep["notified_at"].strftime(replay.TS_FORMAT) == cfg["episodes"][e]["notified_at"]
    assert out["1"]["notified_at"] != out["2"]["notified_at"]                # two different episodes
    assert len(built["fake"].calls) >= 2                               # the build did call the (fake) model


def test_replay_refuses_a_miss(built):
    shutil.rmtree(built["dir"] / demo.CACHE)
    (built["dir"] / demo.CACHE).mkdir()                                 # an empty cache
    with pytest.raises(llm.CacheMiss):
        start(built)


def test_a_changed_prompt_misses_the_cache(built):
    other = lambda f, c, n: "A different template.\\n" + json.dumps({"f": f, "c": c, "n": n})
    with pytest.raises(llm.CacheMiss):
        start(built, render=other)


def test_the_demo_refuses_other_settings_notes_or_alert(built):
    path = built["dir"] / demo.CONFIG
    cfg = json.loads(path.read_text())
    for change, match in (({"settings": {**cfg["settings"], "temperature": 0.5}}, "settings"),
                          ({"schema_version": "diagnosis-0"}, "schema"),
                          ({"notes": {"none": None}}, "other notes"),
                          ({"episodes": {"1": cfg["episodes"]["1"]}}, "other episodes"),
                          ({"episodes": {**cfg["episodes"], "2": {**cfg["episodes"]["2"], "stream": "fault4.csv"}}},
                           "other episodes"),
                          ({"episodes": {**cfg["episodes"], "2": {**cfg["episodes"]["2"],
                                                                  "notified_at": "2026-01-05T06:03:00Z"}}},
                           "first alert")):
        path.write_text(json.dumps({**cfg, **change}))
        with pytest.raises(demo.DemoError, match=match):
            start(built)
    old = {k: v for k, v in cfg.items() if k != "episodes"}                 # the first build's single-episode form
    path.write_text(json.dumps({**old, "notified_at": cfg["episodes"]["1"]["notified_at"], "stream": "run_v2.csv"}))
    with pytest.raises(demo.DemoError, match="before the episode selector"):
        start(built)
    path.unlink()
    with pytest.raises(demo.DemoError, match="isn't built yet"):
        start(built)


# ---------- what's shown ----------

def test_the_emergency_note_is_screened_with_no_llm_call(built):
    calls = len(built["fake"].calls)
    views, _ = start(built)
    for st in ag.STAGES:
        v = views["emergency"][st]
        assert v["outcome"] == "emergency" and v["status"] == "Follow the site emergency procedure"
        assert "site emergency procedure" in v["message"] and "proposal" not in v and "matcher_top" not in v
    assert len(built["fake"].calls) == calls


def test_every_view_is_states_only_and_clean(built):
    views, _ = start(built)
    text = json.dumps(views)
    assert find_leaks(text) == []
    for by in views.values():
        for v in by.values():
            assert v["advisory"] == demo.ADVISORY and "faithfulness" in v
            assert v["faithfulness"]["status"] in ("passed", "failed", "not run")


def test_a_veto_shows_dissent_beside_the_matchers_top_entry(built):
    views, _ = start(built)
    v = views["none"]["provisional"]
    assert v["outcome"] == "vetoed" and "proposal" not in v
    assert v["dissent"]["llm_decision"] == "decline" and v["dissent"]["rationale"]
    assert v["matcher_top"] and all(t["title"] for t in v["matcher_top"])


def test_a_proposal_is_awaiting_approval_with_actions_and_preconditions(tmp_path):
    # A real proposed pass from the graph (tests/agent_helpers), shown as the operator sees it.
    g, deps, _ = ah.open_graph(tmp_path)
    s = ag.start(g, ah.EP, ah.H_DRIFT, ah.NOTIFIED, ah.LIBRARY_AS_OF)
    v = demo.operator_view(s["values"], "none", store.load(), ah.LIBRARY_AS_OF)
    assert v["status"] == "Awaiting supervisor approval" and v["proposal"]["entry_ref"] == ah.DRIFT_REF
    assert v["proposal"]["title"] and all(a["safety_preconditions"] for a in v["proposal"]["actions"])
    assert v["explanation"]["agrees"] is True and v["explanation"]["rationale"]
    assert v["explanation"]["cited_evidence"] and v["faithfulness"] == {"status": "passed", "failures": []}
    assert deps.records.all("approval") == [] and deps.records.all("act") == []


def test_a_failed_check_shows_the_evidence(tmp_path):
    g, deps, _ = ah.open_graph(tmp_path, answer="unfaithful")
    s = ag.start(g, ah.EP, ah.H_DRIFT, ah.NOTIFIED, ah.LIBRARY_AS_OF)
    v = demo.operator_view(s["values"], "none", store.load(), ah.LIBRARY_AS_OF)
    assert v["outcome"] == "failed_check" and v["evidence"]["location"] and "proposal" not in v
    assert v["faithfulness"] == {"status": "failed", "failures": ["citation"]}


# ---------- the as-of rule ----------

def test_nothing_before_the_alert_not_even_when_it_comes(built):
    views, notified = start(built)
    r = demo.diagnosis_at(views, notified, notified - timedelta(minutes=3), "none")
    assert r["available"] is False and "alert_at" not in r and "available_from" not in r
    assert "diagnosis" not in r and r["precomputed"] == demo.PRECOMPUTED


def test_no_diagnosis_before_plus_30_then_provisional_then_revised(built):
    views, n = start(built)
    for minutes in (0, 3, 27):
        r = demo.diagnosis_at(views, n, n + timedelta(minutes=minutes), "none")
        assert r["available"] is False and r["available_from"] == (n + timedelta(minutes=30)).strftime(replay.TS_FORMAT)
    for minutes, stage in ((30, "provisional"), (57, "provisional"), (60, "revised"), (240, "revised")):
        r = demo.diagnosis_at(views, n, n + timedelta(minutes=minutes), "none")
        assert r["available"] is True and r["stage"] == stage and r["diagnosis"] == views["none"][stage]
    assert "revised_from" in demo.diagnosis_at(views, n, n + timedelta(minutes=30), "none")


def test_an_unknown_note_is_refused(built):
    views, n = start(built)
    with pytest.raises(demo.DemoError, match="note is one of"):
        demo.diagnosis_at(views, n, n, "free text")


def test_the_notes_are_the_safety_sets(tmp_path):
    import yaml
    from pathlib import Path
    cases = yaml.safe_load((Path(__file__).resolve().parents[1] / "eval" / "safety" / "cases.yaml").read_text())
    by_id = {c["id"]: c["note"] for c in cases["cases"]}
    assert demo.NOTES == {"none": None, "emergency": by_id["emergency-1"], "injection": by_id["inject-5"]}


def test_notification_time_is_the_first_alert(built):
    from app.agent import tools
    h = tools.load_history(built["streams"]["1"], built["bundle"])
    rows = replay.status(built["bundle"], h.stream, h.stream.ts[-1])
    t = demo.notification_time(built["bundle"], h.stream)
    i = h.stream.ts.index(t)
    assert rows[i]["band"] == "Alert" and all(r["band"] != "Alert" for r in rows[:i])


def test_a_stream_without_an_alert_has_no_episode(tmp_path):
    from app.agent import tools
    from tests.replay_helpers import add_normals, add_watch, make_bundle
    b = dh.bm.load(add_normals(add_watch(make_bundle(tmp_path / "v3"))))
    h = tools.load_history(dh.make_world(tmp_path / "w")[1]["1"], b)
    quiet = replay.Stream(ts=h.stream.ts[:20], values=h.stream.values[:20], tags=h.stream.tags)
    with pytest.raises(demo.DemoError, match="never alerts"):
        demo.notification_time(b, quiet)


# ---------- the episodes (week 6 S9) ----------

def test_the_episodes_are_labelled_by_number_only():
    assert demo.EPISODES == {"1": "run_v2.csv", "2": "episode2.csv"}
    assert demo.EPISODE_LABELS == {"1": "Episode 1", "2": "Episode 2"}
    import re
    for text in list(demo.EPISODES.values()) + list(demo.EPISODE_LABELS.values()):
        assert not re.search(r"fault|idv|mask|cool|feed|react|condens|kinetic|\b\d{2,}\b", text, re.IGNORECASE)


def test_both_episodes_views_are_clean(built):
    out = demo.start_demo(built["bundle"], built["dir"])
    assert find_leaks(json.dumps({e: ep["views"] for e, ep in out.items()})) == []


def test_episode_ids_are_distinct_per_episode(built):
    # the two episodes run as separate threads with separate histories (opaque IDs)
    assert ag.opaque_id("h", "demo-replay", "1") != ag.opaque_id("h", "demo-replay", "2")
    assert ag.opaque_id("ep", "demo", "1", "none", "provisional") != ag.opaque_id("ep", "demo", "2", "none", "provisional")
