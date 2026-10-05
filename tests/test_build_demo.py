"""eval/build_demo.py (week 6 S9) with a FakeClient as the provider: never the API, never data/."""

import json

import pytest

from app.agent import demo, llm
from app.agent.prompts import diagnosis
from eval import build_demo as bd
from tests import demo_helpers as dh
from tests.test_approve_entry import commit


def source_record(repo, mode="evaluation", complete=True):
    p = repo / "eval" / "runs" / f"20261005T000000Z_agent_run_{mode}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"name": "agent_run", "config": {
        "mode": mode, "library_as_of": dh.LIB, "prompt_sha256": "test",
        "rules": {"provisional": {"threshold": "-1", "k": 2}, "revised": {"threshold": "-1", "k": 2}}},
        "metrics": {"complete": complete}}))
    return p


@pytest.fixture
def env(tmp_path, git_repo):
    b, streams = dh.make_world(tmp_path, folder=tmp_path / "streams")
    src = source_record(git_repo)
    commit(git_repo)
    return {"repo": git_repo, "src": src, "bundle_dir": tmp_path / "pca_v3", "streams": streams,
            "out": tmp_path / "replay", "bundle": b}


def build(e, answer=dh.DECLINE, **kw):
    args = dict(from_run=e["src"], billing_tier="tier-1", provider=llm.FakeClient(lambda p, s, r: answer),
                render=diagnosis.render, out_dir=e["out"], bundle_dir=e["bundle_dir"], streams=e["streams"],
                repo_root=e["repo"], out=lambda s: None)
    return bd.run(**{**args, **kw})


def test_it_writes_both_episodes_config_and_cache_that_the_api_serves(env):
    views, record = build(env)
    cfg = json.loads((env["out"] / demo.CONFIG).read_text())
    assert cfg["notes"] == demo.NOTES and cfg["library_as_of"] == dh.LIB and cfg["k"] == 2
    assert cfg["thresholds"] == {"provisional": "-1", "revised": "-1"} and cfg["prompt_sha256"] == "test"
    assert set(cfg["episodes"]) == {"1", "2"} and cfg["episodes"]["2"]["stream"] == "episode2.csv"
    assert list((env["out"] / demo.CACHE).rglob("*.json"))
    served = demo.start_demo(env["bundle"], env["out"], streams=env["streams"], render=diagnosis.render)
    assert {e: ep["views"] for e, ep in served.items()} == views     # the API shows exactly what was built
    rec = json.loads(record.read_text())
    assert rec["name"] == "build_demo" and rec["config"]["billing_tier"] == "tier-1"
    assert rec["config"]["budget_inr"] == 5 and rec["metrics"]["calls"] >= 2
    for e in ("1", "2"):
        assert rec["metrics"]["outcomes"][f"episode{e}_emergency_provisional"] == "emergency"
    assert "fault" not in json.dumps(cfg).lower()                    # the app-side config names no fault


def test_it_never_overwrites(env):
    build(env)
    commit(env["repo"])
    with pytest.raises(FileExistsError):
        build(env)


@pytest.mark.parametrize("tier", [None, "paid"])
def test_a_billing_tier_is_required(env, tier):
    with pytest.raises(bd.BuildDemoError, match="billing-tier"):
        build(env, billing_tier=tier)
    assert not env["out"].exists()


def test_the_source_must_be_a_complete_evaluation(env):
    for src in (source_record(env["repo"], mode="tuning"), source_record(env["repo"], complete=False)):
        commit(env["repo"])
        with pytest.raises(bd.BuildDemoError, match="complete evaluation"):
            build(env, from_run=src)


def test_the_committed_prompt_must_be_the_frozen_one(env):
    prompts = env["repo"] / "app" / "agent" / "prompts"
    prompts.mkdir(parents=True)
    (prompts / "diagnosis.py").write_text("x = 1\n")
    commit(env["repo"])
    with pytest.raises(bd.BuildDemoError, match="frozen"):
        build(env, render=None)
    assert not (env["out"] / demo.CONFIG).exists()


def test_a_leaking_answer_writes_nothing(env):
    leaky = json.dumps({"decision": "decline", "entry_ref": None, "family": None, "confidence": "low",
                        "cited_evidence": [], "action_ids": [], "rationale": "Looks like fault 4."})
    with pytest.raises(bd.leak_scan.LeakError):
        build(env, answer=leaky)
    assert not (env["out"] / demo.CONFIG).exists() and not (env["out"] / demo.CACHE).exists()


def test_the_command_line_requires_a_billing_tier():
    with pytest.raises(SystemExit):
        bd.main(["--from-run", "x.json"])