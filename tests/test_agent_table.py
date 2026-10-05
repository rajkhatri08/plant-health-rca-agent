"""eval/agent_table.py on synthetic runs (never data/) with patched loaders, a throwaway repo
holding a copy of the real library and entry key (tests/test_diag_table.py's fixture), and a
pca_v3 bundle built from the fixture's own inputs. The LLM is always a FakeClient: nothing
here spends money (tests/test_guard.py). The template is tests/agent_helpers.render, not
Raj's.

The synthetic faults all look alike, so the numbers mean nothing: these tests check the
plan, completeness, the one-engine evidence check, the records and the refusals."""

import json

import pytest

import dataset.splits as splits_mod
from app.agent import llm
from eval import agent_table as at
from eval import build_bundle, run_record
from tests import agent_helpers as ah
from tests.test_authoring import NUMBERS
from tests.test_diag_table import ctx, normal_runs  # noqa: F401 (fixture)
from tests.test_diag_table import ready, setup  # noqa: F401 (fixtures ctx depends on)

LIB = "2026-10-05T00:00:00+00:00"


@pytest.fixture
def env(ctx, monkeypatch):
    from tests.test_approve_entry import commit
    bundle_dir = ctx["repo"] / "bundles" / "pca_v3"
    build_bundle.run(ctx["model_path"], ctx["out"], bundle_dir, watch=ctx["watch"], normals=ctx["normals"],
                     repo_root=ctx["repo"])
    commit(ctx["repo"])
    monkeypatch.setattr(splits_mod, "load", lambda repo_root=None: {"pools": {"dev": NUMBERS}})
    monkeypatch.setattr(at, "REPEATS", {"evaluation": 2, "tuning": 1})
    return {**ctx, "bundle": bundle_dir, "runs_out": ctx["repo"] / "data" / "agent_runs"}


def go(e, mode, **kw):
    lines = []
    args = dict(library_as_of=LIB, model_path=e["model_path"], limits_path=e["out"], watch_path=e["watch"],
                normals_path=e["normals"], bundle_dir=e["bundle"], out_root=e["runs_out"], repo_root=e["repo"],
                eval_runs=2, tune_runs=1, out=lines.append, render=ah.render, billing_tier="tier-1")
    result = at.run(mode, **{**args, **kw})
    return result, lines


# ---------- subsets ----------

def test_subsets_are_seeded_disjoint_and_sized():
    pool = list(range(100, 150))
    ev, tu = at.subsets(pool)
    assert len(ev) == 10 and len(tu) == 3 and not set(ev) & set(tu)
    assert (ev, tu) == at.subsets(list(reversed(pool)))                 # order of the pool doesn't matter
    assert set(ev) | set(tu) <= set(pool) and ev == sorted(ev)
    assert (at.EVAL_SEED, at.TUNE_SEED) == (20261004, 20261005)


def test_subsets_refuse_too_few_runs():
    with pytest.raises(at.AgentTableError):
        at.subsets(range(5))


# ---------- the cost projection ----------

def test_projection_is_from_prompt_sizes_and_the_dated_prices():
    p = at.projection([(4000, 4100), (8000, 8200)])
    exp = llm.cost_inr(llm.SETTINGS, 3000, 2 * at.EXPECTED_OUTPUT_TOKENS, 0)
    worst = llm.cost_inr(llm.SETTINGS, 12300, 2 * 1024, 0)
    assert p["calls"] == 2 and p["input_chars"] == 12000
    assert p["expected_inr"] == pytest.approx(float(exp), abs=1e-4)
    assert p["worst_inr"] == pytest.approx(float(worst), abs=1e-4)
    assert at.projection([]) ["calls"] == 0


# ---------- the dry run ----------

def test_the_dry_run_is_complete_and_records_no_result(env):
    (results, record), lines = go(env, "dry-run")
    for subset in ("evaluation", "tuning"):
        r = results[subset]
        assert r["complete"] and r["completed"] == r["planned"] > 0
        assert set(r["outcomes"]) <= {"matcher_declined", "vetoed", "failed_check"}   # the fake declines: a veto
    ev = results["evaluation"]
    assert ev["cases"]["loo"] > 0 and ev["cases"]["false"] > 0 and ev["llm_calls"] > 0
    assert ev["projection"]["calls"] == ev["llm_calls"] and ev["projection"]["expected_inr"] > 0
    assert results["tuning"]["cases"] == {"known": results["tuning"]["cases"]["known"], "false": 0, "loo": 0}
    rec = json.loads(record.read_text())
    assert rec["name"] == "agent_dry_run" and rec["config"]["library_as_of"] == LIB
    assert rec["config"]["rules"]["provisional"]["k"] >= 1 and "threshold" in rec["config"]["rules"]["revised"]
    assert not env["runs_out"].exists()                                  # a temporary folder only
    assert any("projected Rs" in line for line in lines)


def test_project_cost_writes_nothing(env):
    (results, record), _ = go(env, "project-cost")
    assert record is None and results["evaluation"]["complete"]
    assert not list((env["repo"] / "eval" / "runs").glob("*_agent_dry_run.json"))


def test_the_evidence_check_stops_a_mismatch(env, monkeypatch):
    monkeypatch.setattr(at, "expected_evidence", lambda features, stage: {"location": "something else"})
    with pytest.raises(at.AgentTableError, match="differs from eval/cases.py"):
        go(env, "project-cost")


def test_the_bundle_must_be_built_from_the_inputs(env):
    with pytest.raises(at.AgentTableError, match="isn't built from these inputs"):
        go(env, "project-cost", bundle_dir=at.DEFAULT_BUNDLE)          # the committed one: real data's model


# ---------- the paid modes, on a fake ----------

def fake_client(tmp_path, answer=at.DRY_ANSWER):
    return llm.CachedClient(llm.FakeClient(lambda p, s, r: answer), tmp_path / "cache")


def test_a_tuning_run_writes_calls_ledger_and_record(env, tmp_path):
    (m, record), lines = go(env, "tuning", budget=5, client=fake_client(tmp_path))
    rec = json.loads(record.read_text())
    assert rec["name"] == "agent_run" and m["complete"] and m["completed"] == m["planned"]
    assert rec["config"]["budget_inr"] == 5 and rec["config"]["repeats"] == 1
    calls = env["repo"] / rec["outputs"]["calls"]["path"]
    rows = [json.loads(x) for x in calls.read_text().splitlines()]
    assert len(rows) == m["planned"] and {r["kind"] for r in rows} == {"known"}
    need = {"case", "kind", "run", "fault", "family", "right", "stage", "repeat", "outcome", "entry",
            "answer_family", "confidence", "failures", "candidates", "matcher_ranking", "matcher_declined",
            "llm_key", "cached", "latency_ms", "tokens_in", "tokens_out", "tokens_thinking", "error"}
    assert need <= set(rows[0])
    ledger = json.loads((env["repo"] / rec["outputs"]["ledger"]["path"]).read_text())
    assert set(ledger) == {r["llm_key"] for r in rows if r["llm_key"]}


def test_an_evaluation_run_covers_every_kind(env, tmp_path):
    from eval import agent_table
    (m, record), _ = go(env, "evaluation", client=fake_client(tmp_path), prompt_hash="test")
    rows = [json.loads(x) for x in (env["repo"] / json.loads(record.read_text())["outputs"]["calls"]["path"])
            .read_text().splitlines()]
    assert {r["kind"] for r in rows} == {"known", "false", "loo"}
    assert {r["repeat"] for r in rows} == {0, 1} and all(r["right"] is None for r in rows if r["kind"] != "known")
    left_out = set(json.loads(record.read_text())["config"]["left_out"].values())
    assert not left_out & {c for r in rows if r["kind"] == "loo" for c in r["candidates"]}


def test_a_budget_stop_is_recorded_incomplete_and_never_tabled(env, tmp_path):
    n = {"calls": 0}

    def answer(p, s, r):
        n["calls"] += 1
        return llm.BudgetExceeded("the next call could cross the cap") if n["calls"] > 2 else at.DRY_ANSWER
    (m, record), lines = go(env, "tuning", budget=5, client=llm.FakeClient(answer))
    assert not m["complete"] and "cross the cap" in m["stopped"] and m["completed"] < m["planned"]
    assert "INCOMPLETE" in lines[0]
    with pytest.raises(at.AgentTableError, match="incomplete"):
        at.table(record, repo_root=env["repo"], tables_dir=env["tables"])


def test_tuning_needs_a_budget(env, tmp_path):
    with pytest.raises(at.AgentTableError, match="--budget"):
        go(env, "tuning", client=fake_client(tmp_path))


def test_evaluation_refuses_a_prompt_that_isnt_frozen(env):
    # No client injected: the hash is computed from the repo's prompts folder, before anything loads.
    (env["repo"] / "app" / "agent" / "prompts").mkdir(parents=True)
    (env["repo"] / "app" / "agent" / "prompts" / "diagnosis.txt").write_text("template")
    with pytest.raises(at.AgentTableError, match="not the frozen"):
        go(env, "evaluation", prompt_hash="0" * 64)
    assert env["calls"] == []


def test_the_prompt_hash_needs_a_template(tmp_path):
    (tmp_path / ".gitkeep").write_text("")
    with pytest.raises(at.AgentTableError, match="no prompt template"):
        at.prompt_sha256(tmp_path)
    (tmp_path / "diagnosis.py").write_text("x = 1\n")
    h = at.prompt_sha256(tmp_path)
    (tmp_path / "diagnosis.py").write_text("x = 2\n")
    assert at.prompt_sha256(tmp_path) != h


def test_a_dirty_tree_is_refused_before_loading(env, tmp_path):
    (env["repo"] / "stray.py").write_text("x = 1\n")
    with pytest.raises(run_record.RunRecordError):
        go(env, "dry-run")
    assert env["calls"] == []


def test_unknown_mode_and_naive_library_clock(env):
    with pytest.raises(at.AgentTableError):
        go(env, "free-run")
    with pytest.raises(at.AgentTableError, match="UTC offset"):
        at.run("project-cost", library_as_of="2026-10-05", model_path=env["model_path"], limits_path=env["out"],
               watch_path=env["watch"], normals_path=env["normals"], bundle_dir=env["bundle"],
               repo_root=env["repo"], render=ah.render, eval_runs=2, tune_runs=1, out=lambda s: None)


# ---------- the table (needs eval/agent_metrics.py, Raj's) ----------

def test_the_table_from_a_complete_run(env, tmp_path):
    (m, record), _ = go(env, "evaluation", client=fake_client(tmp_path), prompt_hash="test")
    from tests.test_approve_entry import commit
    commit(env["repo"])
    results, table_record = at.table(record, repo_root=env["repo"], tables_dir=env["tables"], n_boot=20,
                                     out=lambda s: None)
    rec = json.loads(table_record.read_text())
    assert rec["name"] == "agent_table" and set(results) == {"provisional", "revised"}
    for st in results:
        assert set(results[st]["agent"]) == {"0", "1"} and results[st]["keep_rule"]["applicable"] is True
        assert isinstance(results[st]["keep_rule"]["keep"], bool)
        assert set(results[st]["paired"]) == {"0", "1"}
    assert len(list(env["tables"].glob("*_agent_table.md"))) == 1


def test_the_table_from_a_known_only_run(env, tmp_path):
    # The tuning subset has known cases only (decision 77): the unknown-case metrics have no
    # denominator, so they're None and the keep rule is not applicable; everything else is reported.
    (m, record), _ = go(env, "tuning", budget=50, client=fake_client(tmp_path))
    from tests.test_approve_entry import commit
    commit(env["repo"])
    results, table_record = at.table(record, repo_root=env["repo"], tables_dir=env["tables"], n_boot=20,
                                     out=lambda s: None)
    assert json.loads(table_record.read_text())["name"] == "agent_table"
    for st, r in results.items():
        kr = r["keep_rule"]
        assert kr["applicable"] is False and kr["keep"] is None and kr["reason"] == at.NO_UNKNOWNS
        a = r["agent"]["0"]
        assert a["false_alert_declined"] is None and a["loo_declined"] is None
        assert a["false_alerts"] == 0 and a["loo"] == 0
        assert a["known"] > 0 and a["top1"] is not None and a["top3"] is not None and a["family"] is not None
        assert a["wrongly_declined"] is not None
        assert {"failed_check", "schema", "errors"} <= set(a)
        mt = r["matcher"]
        assert mt["known"] == a["known"] and mt["top1"] is not None
        assert mt["false_alert_declined"] is None and mt["loo_declined"] is None
        assert set(r["paired"]) == {"0"}
        assert {"high", "medium", "low"} == set(r["confidence"]) and r["agreement"]["cases"] > 0
        assert set(r["misses"]) == {"gate", "retrieval", "reasoning"}
        assert r["not_in_library"]["cases"] == 0
        assert r["latency_cost"]["calls"] >= 0 and "cost_inr" in r["latency_cost"]
    (md,) = env["tables"].glob("*_agent_table.md")
    assert md.read_text().count("Keep rule: not applicable (no unknown cases).") == 2


def test_the_evaluation_run_defaults_to_its_rs_450_cap(env, tmp_path):
    # Decision 77: Rs 50 for tuning (given explicitly) and Rs 450 for the evaluation run.
    assert at.DEFAULT_BUDGETS == {"evaluation": 450}
    (m, record), _ = go(env, "evaluation", client=fake_client(tmp_path), prompt_hash="test")
    assert json.loads(record.read_text())["config"]["budget_inr"] == 450


# ---------- pacing in the paid runs ----------

def test_the_paid_stack_paces_real_calls_only(tmp_path):
    from tests.test_llm import FakeClock, timed_fake
    clock = FakeClock()
    fake, starts = timed_fake(clock, takes=0.25)
    c = at.paid_stack(fake, 1, 2.0, cache_dir=tmp_path / "cache", clock=clock.now, sleep=clock.sleep)
    from app.agent import schema
    s = schema.output_schema()
    c.complete("p", s, repeat=0)
    c.complete("p", s, repeat=0)                              # a cache hit: neither metered nor paced
    c.complete("q", s, repeat=0)
    assert starts == [0.0, 2.0] and clock.sleeps == [1.75] and len(fake.calls) == 2
    assert isinstance(c, llm.CachedClient) and isinstance(c.inner, llm.MeteredClient)
    assert isinstance(c.inner.inner, llm.PacedClient) and c.inner.inner.min_interval == 2.0


def test_the_run_records_its_min_interval(env, tmp_path):
    (m, record), _ = go(env, "tuning", budget=50, client=fake_client(tmp_path), min_interval=1.5)
    assert json.loads(record.read_text())["config"]["min_interval_s"] == 1.5
    from tests.test_approve_entry import commit
    commit(env["repo"])                                       # the first run's files make the tree dirty
    (m, record), _ = go(env, "tuning", budget=50, client=fake_client(tmp_path / "b"),
                        now=at.datetime(2026, 10, 4, 18, 0, tzinfo=at.timezone.utc))
    assert json.loads(record.read_text())["config"]["min_interval_s"] == 0.0     # the default


@pytest.mark.parametrize("bad", [-0.5, True])
def test_a_bad_min_interval_is_refused(env, tmp_path, bad):
    with pytest.raises(at.AgentTableError, match="min-interval"):
        go(env, "tuning", budget=50, client=fake_client(tmp_path), min_interval=bad)


def test_the_command_line_takes_min_interval(monkeypatch):
    seen = {}
    monkeypatch.setattr(at, "run", lambda mode, **kw: seen.update(mode=mode, **kw))
    import dotenv
    monkeypatch.setattr(dotenv, "load_dotenv", lambda **kw: None)
    assert at.main(["--tuning", "--library-as-of", LIB, "--budget", "50", "--min-interval", "4",
                    "--billing-tier", "tier-1"]) == 0
    assert seen["mode"] == "tuning" and seen["min_interval"] == 4.0 and seen["budget"] == 50.0


# ---------- the billing tier (decision 76) ----------

@pytest.mark.parametrize("tier", [None, "paid", "Tier-1"])
def test_a_paid_run_needs_a_known_billing_tier_before_loading(env, tmp_path, tier):
    with pytest.raises(at.AgentTableError, match="billing-tier"):
        go(env, "tuning", budget=50, client=fake_client(tmp_path), billing_tier=tier)
    assert env["calls"] == []


@pytest.mark.parametrize("tier", ["free", "tier-1"])
def test_the_run_records_its_billing_tier(env, tmp_path, tier):
    (m, record), _ = go(env, "tuning", budget=50, client=fake_client(tmp_path), billing_tier=tier)
    assert json.loads(record.read_text())["config"]["billing_tier"] == tier


def test_the_dry_run_needs_no_billing_tier(env):
    (results, record), _ = go(env, "project-cost", billing_tier=None)
    assert results["evaluation"]["complete"]


def test_the_command_line_requires_the_billing_tier_for_paid_runs(monkeypatch):
    seen = {}
    monkeypatch.setattr(at, "run", lambda mode, **kw: seen.update(mode=mode, **kw))
    import dotenv
    monkeypatch.setattr(dotenv, "load_dotenv", lambda **kw: None)
    for mode in ("--tuning", "--evaluation"):
        with pytest.raises(SystemExit):
            at.main([mode, "--library-as-of", LIB, "--budget", "50"])
    with pytest.raises(SystemExit):
        at.main(["--tuning", "--library-as-of", LIB, "--budget", "50", "--billing-tier", "paid"])
    assert seen == {}
    assert at.main(["--evaluation", "--library-as-of", LIB, "--prompt-sha256", "x", "--billing-tier", "tier-1"]) == 0
    assert seen["billing_tier"] == "tier-1"
    assert at.main(["--dry-run", "--library-as-of", LIB]) == 0 and seen["billing_tier"] is None


# ---------- --table's record path ----------

def test_the_table_takes_a_path_relative_to_the_repo_from_anywhere(env, tmp_path, monkeypatch):
    (m, record), _ = go(env, "tuning", budget=50, client=fake_client(tmp_path))
    from tests.test_approve_entry import commit
    commit(env["repo"])
    rel = record.relative_to(env["repo"]).as_posix()               # eval/runs/<stamp>_agent_run.json
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)                                    # not the repo root
    results, table_record = at.table(rel, repo_root=env["repo"], tables_dir=env["tables"], n_boot=20,
                                     out=lambda s: None)
    assert json.loads(table_record.read_text())["config"]["agent_run"] == rel


def test_the_table_still_takes_an_absolute_path_and_refuses_one_outside_the_repo(env, tmp_path):
    (m, record), _ = go(env, "tuning", budget=50, client=fake_client(tmp_path))
    from tests.test_approve_entry import commit
    commit(env["repo"])
    outside = tmp_path / "copy_agent_run.json"
    outside.write_text(record.read_text())
    with pytest.raises(at.AgentTableError, match="isn't inside the repo"):
        at.table(outside, repo_root=env["repo"], tables_dir=env["tables"], out=lambda s: None)
    _, table_record = at.table(record, repo_root=env["repo"], tables_dir=env["tables"], n_boot=20,
                               out=lambda s: None)
    assert json.loads(table_record.read_text())["config"]["agent_run"] == record.relative_to(env["repo"]).as_posix()



# ---------- the shipped flow: replay from the cache, three views (decision 79) ----------

def test_a_replay_answers_every_pass_from_the_cache_and_spends_nothing(env, tmp_path):
    from tests.test_approve_entry import commit
    cache = tmp_path / "cache"
    (m, record), _ = go(env, "evaluation", client=llm.CachedClient(llm.FakeClient(lambda p, s, r: at.DRY_ANSWER),
                                                                   cache), prompt_hash="test")
    commit(env["repo"])
    (rm, replay), lines = go(env, "replay-evaluation", cache_dir=cache, prompt_hash="test",
                             now=at.datetime(2026, 10, 5, 12, 0, tzinfo=at.timezone.utc))
    rec = json.loads(replay.read_text())
    assert rm["complete"] and rm["completed"] == m["completed"] and rm["spent_inr"] == 0.0
    assert rec["config"]["mode"] == "replay-evaluation" and rec["config"]["cache_only"] is True
    assert rec["config"]["billing_tier"] is None
    rows = [json.loads(x) for x in (env["repo"] / rec["outputs"]["calls"]["path"]).read_text().splitlines()]
    assert all(r["cached"] for r in rows if r["llm_key"])
    assert {r["outcome"] for r in rows} <= {"matcher_declined", "vetoed", "failed_check", "proposed"}


def test_a_replay_with_an_empty_cache_stops_on_the_first_miss(env, tmp_path):
    (rm, replay), lines = go(env, "replay-evaluation", cache_dir=tmp_path / "empty", prompt_hash="test")
    assert not rm["complete"] and "cache miss" in rm["stopped"] and rm["spent_inr"] == 0.0
    assert "INCOMPLETE" in lines[0]


def test_a_replay_refuses_another_prompt(env, tmp_path):
    (env["repo"] / "app" / "agent" / "prompts").mkdir(parents=True)
    (env["repo"] / "app" / "agent" / "prompts" / "diagnosis.txt").write_text("template")
    with pytest.raises(at.AgentTableError, match="a replay needs the same prompts"):
        go(env, "replay-evaluation", cache_dir=tmp_path, prompt_hash="0" * 64, render=None)
    assert env["calls"] == []


def test_the_reranker_view_of_a_pass():
    base = {"outcome": "vetoed", "entry": None, "llm_decision": "propose", "llm_entry": "b"}
    assert at.reranker_row(base)["outcome"] == "proposed" and at.reranker_row(base)["entry"] == "b"
    assert at.reranker_row({**base, "llm_decision": "decline", "llm_entry": None})["outcome"] == "declined"
    assert at.reranker_row({**base, "llm_decision": "not_in_library", "llm_entry": None})["outcome"] == "not_in_library"
    agreed = {"outcome": "proposed", "entry": "a", "llm_decision": "propose", "llm_entry": "a"}
    assert at.reranker_row(agreed) == {**agreed}
    for outcome in ("matcher_declined", "failed_check", "error", "emergency"):
        assert at.reranker_row({**base, "outcome": outcome})["outcome"] == outcome
    old = {"outcome": "declined", "entry": None}                                    # a run before decision 79
    assert at.reranker_row(old) is old


def test_the_table_reports_shipped_reranker_and_matcher(env, tmp_path):
    from tests.test_approve_entry import commit
    (m, record), _ = go(env, "evaluation", client=fake_client(tmp_path), prompt_hash="test")
    commit(env["repo"])
    results, _ = at.table(record, repo_root=env["repo"], tables_dir=env["tables"], n_boot=20, out=lambda s: None)
    for st, r in results.items():
        assert r["shipped_flow"] is True and set(r["reranker"]) == set(r["agent"]) == {"0", "1"}
        assert r["vetoes"] > 0 and set(r["paired_reranker"]) == {"0", "1"}
        a, rr = r["agent"]["0"], r["reranker"]["0"]
        assert a["known"] == rr["known"] == r["matcher"]["known"]
    (md,) = env["tables"].glob("*_agent_table.md")
    assert "| shipped, repeat 0 |" in md.read_text() and "| re-ranker, repeat 0 |" in md.read_text()
