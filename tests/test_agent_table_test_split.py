"""eval/agent_table.py --split test (week 7 S1d), on synthetic runs only.

Built on test_agent_table's env (a throwaway repo with the real library, a pca_v3 bundle
from the fixture's inputs, dev loaders patched). load_testing is a fake serving synthetic
testing runs (onset after sample 160, faults 0-20), the sealed folder is a tmp_path, and
the LLM is always a FakeClient: nothing here reads data, opens the real sealed folder,
sets EVAL_MODE or spends money. To keep it quick the draw is cut to 3 run numbers and the
repeat counts to (2, 1); the rules being tested don't depend on either.
"""

import json
from datetime import datetime, timezone

import numpy as np
import pytest

import dataset.loader as loader_mod
from dataset.convert import VARIABLES
from dataset.loader import Runs
from eval import agent_table as at
from eval import diag_table as dt
from eval import split as split_mod
from ingest import tags as tagmap
from tests import agent_helpers as ah
from tests.test_agent_table import LIB, env, fake_client  # noqa: F401 (fixture)
from tests.test_authoring import ANALYZERS, INTERVAL, hold
from tests.test_diag_table import ctx, ready, setup  # noqa: F401 (fixtures env depends on)
from tests.test_fit_pca import FAST, two_factor_runs

DRAW = split_mod.test_draw()[:3]
EXTRA = next(n for n in range(1, 501) if n not in split_mod.test_draw())     # a run outside the draw
SAMPLES = 300


def synthetic_testing_runs(fault):
    runs = two_factor_runs(numbers=DRAW + [EXTRA], samples=SAMPLES, seed=700 + fault)
    fast = tagmap.column_indices(VARIABLES, FAST)
    an = dict(zip(ANALYZERS, tagmap.column_indices(VARIABLES, ANALYZERS)))
    for k, x in runs.runs.items():
        if fault:
            x[160:, fast] += np.float32(1.5 + 0.3 * fault)
        elif k == DRAW[0]:
            x[50:62, fast] += np.float32(3.0)                         # a false alert on a drawn normal run
        for t, c in an.items():
            x[:, c] = hold(x[:, c], INTERVAL[t])
    return Runs("faulty_testing" if fault else "fault_free_testing", fault, "test", VARIABLES, runs.runs)


@pytest.fixture
def te(env, monkeypatch, tmp_path):
    sealed = tmp_path / "sealed"
    monkeypatch.setattr(loader_mod, "SEALED_ROOT", sealed)
    monkeypatch.setattr(split_mod, "test_draw", lambda: list(DRAW))
    monkeypatch.setattr(at, "TEST_REPEATS", (2, 1))
    test_calls = []

    def load_testing(fault, *, purpose):
        test_calls.append((fault, purpose))
        return synthetic_testing_runs(fault)

    monkeypatch.setattr(loader_mod, "load_testing", load_testing)
    dt.run(env["model_path"], env["out"], env["watch"], env["normals"], tables_dir=tmp_path / "fp_tables",
           repo_root=env["repo"], now=datetime(2026, 10, 5, 9, tzinfo=timezone.utc), n_boot=50,
           library_as_of=datetime.fromisoformat(LIB), fingerprint_out=True)
    (fp,) = (env["repo"] / "eval" / "runs").glob("*_diag_fingerprint.json")
    env["calls"].clear()
    return {**env, "sealed": sealed, "test_calls": test_calls, "fp": fp}


def go_test(e, mode, **kw):
    lines = []
    args = dict(library_as_of=LIB, model_path=e["model_path"], limits_path=e["out"], watch_path=e["watch"],
                normals_path=e["normals"], bundle_dir=e["bundle"], repo_root=e["repo"], out=lines.append,
                render=ah.render, prompt_hash="test", split="test", fingerprint_record=e["fp"])
    return at.run(mode, **{**args, **kw}), lines


def dry(e, **kw):
    (m, record), lines = go_test(e, "dry-run", **kw)
    return m, record, lines


def paid(e, tmp_path, record, **kw):
    kw.setdefault("client", fake_client(tmp_path))
    return go_test(e, "evaluation", billing_tier="tier-1", dry_run_record=record, **kw)


# ---------- the dry run ----------

def test_the_dry_run_covers_every_kind_and_projects_both_repeat_counts(te):
    m, record, lines = dry(te)
    assert m["complete"] and m["completed"] == m["planned"] > 0
    assert all(m["cases"][k] > 0 for k in ("known", "unknown", "loo", "false"))
    assert set(m["projection"]) == {"2", "1"}
    assert m["projection"]["1"]["calls"] < m["projection"]["2"]["calls"]
    assert m["repeats_allowed"] == 2                                     # far under the cap here
    rec = json.loads(record.read_text())
    assert rec["name"] == "test_agent_dry_run" and rec["outputs"] == {}
    assert rec["config"]["split"] == "test" and rec["config"]["subsample"] == {"seed": 20261006, "runs": 10}
    assert set(rec["config"]["left_out"]) == {"1", "4", "5", "13"}
    assert any("paid run: --repeats 2" in line for line in lines)
    assert not (te["repo"] / "data" / "agent_runs").exists() and not (te["repo"] / "data" / "llm_cache").exists()


def test_dev_rules_are_checked_before_the_first_test_load(te):
    dry(te)
    assert te["calls"] and all(pool == "dev" for _, pool in te["calls"])
    assert [f for f, _ in te["test_calls"]] == [1, 2, 4, 5, 6, 7, 8, 10, 11, 12, 13, 14, 16, 17, 18, 19, 20, 0]
    assert {p for _, p in te["test_calls"]} == {"test_agent_dry_run"}


def test_only_the_drawn_runs_are_cases(te, tmp_path):
    m, dry_record, _ = dry(te)
    assert m["cases"]["false"] >= 1                                      # the spiked drawn normal run
    # every case is on a drawn run (EXTRA is in every file but never scored)
    (_, record), _ = paid(te, tmp_path, dry_record)
    rows = [json.loads(x) for x in at.output_path(te["repo"], json.loads(record.read_text())["outputs"]["calls"]["path"])
            .read_text().splitlines()]
    assert {r["run"] for r in rows} <= set(DRAW) and EXTRA not in {r["run"] for r in rows}


def test_a_fingerprint_mismatch_stops_before_any_test_load(te):
    doc = json.loads(te["fp"].read_text())
    doc["metrics"]["revised"]["matcher"]["threshold"] = "99/100"
    te["fp"].write_text(json.dumps(doc))
    with pytest.raises(at.AgentTableError, match="aren't the fingerprint's"):
        dry(te)
    assert te["test_calls"] == []


def test_too_many_false_alert_cases_stop_the_run(te, monkeypatch):
    monkeypatch.setattr(at, "TEST_FALSE_CAP", 0)
    with pytest.raises(at.AgentTableError, match="over 0 .*stop and tell Raj"):
        dry(te)
    assert not list((te["repo"] / "eval" / "runs").glob("*_test_agent_dry_run.json"))


@pytest.mark.parametrize("cap, allowed", [(1e9, 2), (None, 1), (0.0, None)])
def test_repeats_allowed_follows_the_projection_cap(te, monkeypatch, cap, allowed):
    if cap is None:                                                      # between the two projections
        m, _, _ = dry(te)
        cap = (m["projection"]["1"]["expected_inr"] + m["projection"]["2"]["expected_inr"]) / 2
        for p in (te["repo"] / "eval" / "runs").glob("*_test_agent_dry_run.json"):
            p.unlink()
    monkeypatch.setattr(at, "TEST_PROJECTION_CAP", cap)
    m, _, lines = dry(te, now=datetime(2026, 10, 6, 1, tzinfo=timezone.utc))
    assert m["repeats_allowed"] == allowed
    if allowed is None:
        assert any(line.startswith("STOP") for line in lines)


@pytest.mark.parametrize("kw, match", [
    ({"prompt_hash": None}, "not the frozen"),
    ({"fingerprint_record": None}, "needs --fingerprint-record"),
    ({"repeats": 7}, "one of"),
    ({"repeats": 1}, "give no --repeats"),
])
def test_dry_run_refusals_before_any_load(te, kw, match):
    with pytest.raises(at.AgentTableError, match=match):
        go_test(te, "dry-run", **kw)
    assert te["calls"] == [] and te["test_calls"] == []


def test_other_modes_refused_on_test_and_test_flags_refused_on_dev(te):
    for mode in ("tuning", "project-cost", "replay-evaluation"):
        with pytest.raises(at.AgentTableError, match="--dry-run or --evaluation"):
            go_test(te, mode)
    with pytest.raises(at.AgentTableError, match="only for --split test"):
        go_test(te, "dry-run", split="dev")
    assert te["test_calls"] == []


# ---------- the paid run (a FakeClient) ----------

def test_the_paid_run_writes_everything_to_the_sealed_folder(te, tmp_path):
    _, dry_record, _ = dry(te)
    (m, record), lines = paid(te, tmp_path, dry_record)
    rec = json.loads(record.read_text())
    assert rec["name"] == "test_agent_run" and m["complete"] and m["completed"] == m["planned"]
    for name in ("calls", "ledger"):
        assert rec["outputs"][name]["path"].startswith("sealed:test_outputs/")
    assert str(te["sealed"]) not in record.read_text()
    c = rec["config"]
    assert (c["budget_inr"], c["repeats"], c["billing_tier"]) == (500, 2, "tier-1")
    assert c["dry_run_record"].endswith("_test_agent_dry_run.json") and c["fingerprint_record"].endswith(
        "_diag_fingerprint.json")
    rows = [json.loads(x) for x in at.output_path(te["repo"], rec["outputs"]["calls"]["path"]).read_text().splitlines()]
    assert {r["kind"] for r in rows} == {"known", "unknown", "loo", "false"}
    assert all(r["right"] is None for r in rows if r["kind"] != "known")
    for r in rows:
        if r["kind"] == "loo":
            assert r["variant"] == f"loo_{r['fault']}" and at.LOO_TEST[r["fault"]] not in r["candidates"]
            assert at.LOO_TEST[r["fault"]] not in {e for b in r["matcher_ranking"] for e in b}
    assert {r["fault"] for r in rows if r["kind"] == "unknown"} <= set(at.UNKNOWN_FAULTS)
    assert not (te["repo"] / "data" / "agent_runs").exists()
    assert {p for _, p in te["test_calls"]} >= {"test_agent_run"}


def test_the_real_client_would_cache_in_the_sealed_folder(te, monkeypatch):
    _, dry_record, _ = dry(te)
    seen = {}
    from eval import gemini

    class Dummy:
        def __init__(self, settings):
            self.settings = settings

    monkeypatch.setattr(gemini, "GeminiClient", Dummy)

    def stack(provider, budget, min_interval, *, cache_dir=None, **kw):
        seen.update(budget=budget, cache_dir=cache_dir, min_interval=min_interval)
        return fake_client(cache_dir.parent / "fake")

    monkeypatch.setattr(at, "paid_stack", stack)
    go_test(te, "evaluation", billing_tier="tier-1", dry_run_record=dry_record, client=None, render=ah.render,
            min_interval=1.0)
    assert seen["cache_dir"] == te["sealed"] / "llm_cache" and seen["budget"] == 500 and seen["min_interval"] == 1.0


@pytest.mark.parametrize("change, match", [
    ({"budget": 600}, "at most Rs 500"),
    ({"repeats": 1}, "allows 2 repeats"),
    ({"billing_tier": None}, "--billing-tier"),
    ({"dry_run_record": None}, "needs --dry-run-record"),
])
def test_paid_run_refusals(te, tmp_path, change, match):
    _, dry_record, _ = dry(te)
    te["test_calls"].clear()
    kw = {"billing_tier": "tier-1", "dry_run_record": dry_record, **change}
    with pytest.raises(at.AgentTableError, match=match):
        go_test(te, "evaluation", client=fake_client(tmp_path), **kw)
    assert te["test_calls"] == []


@pytest.mark.parametrize("field", ["commit", "dirty", "name"])
def test_the_dry_run_must_be_this_commits(te, tmp_path, field):
    _, dry_record, _ = dry(te)
    doc = json.loads(dry_record.read_text())
    if field == "commit":
        doc["commit"] = "0" * 40
    elif field == "dirty":
        doc["dirty"] = True
    dry_record.write_text(json.dumps(doc))
    if field == "name":
        dry_record = dry_record.rename(dry_record.with_name("20261005T000000Z_agent_dry_run.json"))
    te["test_calls"].clear()
    with pytest.raises(at.AgentTableError):
        paid(te, tmp_path, dry_record)
    assert te["test_calls"] == []


def test_a_dry_run_with_nothing_allowed_blocks_the_paid_run(te, tmp_path, monkeypatch):
    monkeypatch.setattr(at, "TEST_PROJECTION_CAP", 0.0)
    _, dry_record, _ = dry(te)
    with pytest.raises(at.AgentTableError, match="even 3 repeats"):
        paid(te, tmp_path, dry_record)


# ---------- the table ----------

def test_the_test_table(te, tmp_path):
    _, dry_record, _ = dry(te)
    (_, record), _ = paid(te, tmp_path, dry_record)
    results, table_record = at.table(record, repo_root=te["repo"], tables_dir=te["tables"], n_boot=50,
                                     out=lambda s: None)
    rec = json.loads(table_record.read_text())
    assert rec["name"] == "test_agent_table" and rec["config"]["test_agent_run"].endswith("_test_agent_run.json")
    assert rec["outputs"]["table_with_cases"]["path"].startswith("sealed:test_outputs/")
    for st in at.STAGES:
        r = results[st]
        assert r["shipped_flow"] and r["keep_rule"]["applied"] is False and r["keep_rule"]["applicable"]
        assert set(r["unknowns"]) == {"shipped", "reranker", "matcher"}
        assert set(r["unknowns"]["matcher"]["unknown"]["by_fault"]) == {"16", "17", "18", "19", "20"}
        assert set(r["unknowns"]["matcher"]["loo"]["by_fault"]) == {"1", "4", "5", "13"}
        assert r["latency_cost"]["cold_start"].startswith("not applicable") and r["llm_only"].startswith("not run")
    md = next(te["tables"].glob("*_test_agent_table.md")).read_text()
    sealed_md = at.output_path(te["repo"], rec["outputs"]["table_with_cases"]["path"]).read_text()
    assert md.startswith("# Agent table (test)") and "Reported, not applied" in md
    assert not any(line.startswith("- ") for line in md.splitlines())    # no case IDs outside the sealed folder
    unstable = sum(len(results[st]["agreement"]["unstable"]) for st in at.STAGES)
    assert sealed_md.startswith("# Agent table (test)")
    assert sum(line.startswith("- ") for line in sealed_md.splitlines()) == unstable


def test_main_passes_the_test_flags(monkeypatch):
    seen = []
    monkeypatch.setattr(at, "run", lambda mode, **kw: seen.append((mode, kw)))
    assert at.main(["--dry-run", "--split", "test", "--library-as-of", LIB, "--prompt-sha256", "h",
                    "--fingerprint-record", "f.json"]) == 0
    mode, kw = seen[0]
    assert mode == "dry-run" and kw["split"] == "test" and kw["fingerprint_record"] == at.Path("f.json")
    assert kw["dry_run_record"] is None and kw["repeats"] is None

# ---------- the pre-registered rerun after a budget stop, and the repeats default (driver change 3b) ----------
# TEST_REPEATS is patched to (2, 1) here, so "3 repeats" in the plan is 1 in these tests.

from app.agent import llm  # noqa: E402


def stopping_client(after_calls=2):
    n = {"calls": 0}

    def answer(p, s, r):
        n["calls"] += 1
        return llm.BudgetExceeded("the next call could cross the cap") if n["calls"] > after_calls else at.DRY_ANSWER
    return llm.FakeClient(answer)


def budget_stopped(te, tmp_path):
    _, dry_record, _ = dry(te)
    (m, record), _ = paid(te, tmp_path, dry_record, client=stopping_client())
    return dry_record, record, m


def test_a_budget_stop_is_recorded_as_one(te, tmp_path):
    _, record, m = budget_stopped(te, tmp_path)
    rec = json.loads(record.read_text())
    assert not m["complete"] and m["stop_kind"] == "budget" and rec["config"]["after_budget_stop"] is None


def test_the_rerun_after_a_budget_stop_defaults_to_3_repeats_and_the_budget_left(te, tmp_path):
    dry_record, stopped, m = budget_stopped(te, tmp_path)
    (m2, record), _ = go_test(te, "evaluation", billing_tier="tier-1", dry_run_record=dry_record,
                              after_budget_stop=stopped, client=fake_client(tmp_path / "again"),
                              now=datetime(2026, 10, 9, 1, tzinfo=timezone.utc))
    rec = json.loads(record.read_text())
    assert m2["complete"] and rec["config"]["repeats"] == at.TEST_REPEATS[-1]
    left = 500 - json.loads(stopped.read_text())["metrics"]["spent_inr"]
    assert rec["config"]["budget_inr"] <= left and rec["config"]["budget_inr"] > left - 0.01
    assert rec["config"]["after_budget_stop"].endswith("_test_agent_run.json")
    assert rec["config"]["after_budget_stop_sha256"] == at.run_record.sha256(stopped)


@pytest.mark.parametrize("kw, match", [({"repeats": 2}, "is at 1 repeats"), ({"budget": 499.999}, "at most Rs 500 minus")])
def test_the_rerun_refuses_anything_else(te, tmp_path, kw, match):
    dry_record, stopped, _ = budget_stopped(te, tmp_path)
    te["test_calls"].clear()
    with pytest.raises(at.AgentTableError, match=match):
        go_test(te, "evaluation", billing_tier="tier-1", dry_run_record=dry_record, after_budget_stop=stopped,
                client=fake_client(tmp_path / "again"), now=datetime(2026, 10, 9, 1, tzinfo=timezone.utc), **kw)
    assert te["test_calls"] == []


def test_after_budget_stop_needs_a_budget_stop_from_this_commit(te, tmp_path):
    _, dry_record, _ = dry(te)
    (_, complete_record), _ = paid(te, tmp_path, dry_record)
    with pytest.raises(at.AgentTableError, match="didn't stop on the budget"):
        go_test(te, "evaluation", billing_tier="tier-1", dry_run_record=dry_record,
                after_budget_stop=complete_record, client=fake_client(tmp_path / "x"),
                now=datetime(2026, 10, 9, 2, tzinfo=timezone.utc))
    doc = json.loads(complete_record.read_text())
    doc["metrics"].update(complete=False, stop_kind="budget")
    doc["commit"] = "0" * 40
    complete_record.write_text(json.dumps(doc))
    with pytest.raises(at.AgentTableError, match="this commit"):
        go_test(te, "evaluation", billing_tier="tier-1", dry_run_record=dry_record,
                after_budget_stop=complete_record, client=fake_client(tmp_path / "y"),
                now=datetime(2026, 10, 9, 3, tzinfo=timezone.utc))


def test_a_rerun_that_stops_too_ends_the_run(te, tmp_path):
    dry_record, stopped, _ = budget_stopped(te, tmp_path)
    (_, rerun), _ = go_test(te, "evaluation", billing_tier="tier-1", dry_run_record=dry_record,
                            after_budget_stop=stopped, client=stopping_client(after_calls=1),
                            now=datetime(2026, 10, 9, 4, tzinfo=timezone.utc))
    assert json.loads(rerun.read_text())["metrics"]["stop_kind"] == "budget"
    with pytest.raises(at.AgentTableError, match="stop and tell Raj"):
        go_test(te, "evaluation", billing_tier="tier-1", dry_run_record=dry_record, after_budget_stop=rerun,
                client=fake_client(tmp_path / "z"), now=datetime(2026, 10, 9, 5, tzinfo=timezone.utc))


def test_after_budget_stop_is_refused_on_the_dry_run_and_on_dev(te, tmp_path):
    with pytest.raises(at.AgentTableError, match="only for the paid run"):
        go_test(te, "dry-run", after_budget_stop=tmp_path / "x_test_agent_run.json")
    with pytest.raises(at.AgentTableError, match="only for --split test"):
        go_test(te, "dry-run", split="dev", after_budget_stop=tmp_path / "x_test_agent_run.json")


def test_omitted_repeats_default_to_what_the_dry_run_allows(te, tmp_path, monkeypatch):
    m, _, _ = dry(te)
    cap = (m["projection"]["1"]["expected_inr"] + m["projection"]["2"]["expected_inr"]) / 2
    monkeypatch.setattr(at, "TEST_PROJECTION_CAP", cap)                 # only 1 repeat fits
    _, dry_record, _ = dry(te, now=datetime(2026, 10, 9, 6, tzinfo=timezone.utc))
    (_, record), _ = paid(te, tmp_path, dry_record, now=datetime(2026, 10, 9, 7, tzinfo=timezone.utc))
    assert json.loads(record.read_text())["config"]["repeats"] == 1


def test_main_passes_after_budget_stop(monkeypatch):
    seen = []
    monkeypatch.setattr(at, "run", lambda mode, **kw: seen.append(kw))
    # the dry-run form: a paid form would read .env, which the test guard forbids
    assert at.main(["--dry-run", "--split", "test", "--library-as-of", LIB, "--prompt-sha256", "h",
                    "--fingerprint-record", "f.json", "--after-budget-stop", "r.json"]) == 0
    assert seen[0]["after_budget_stop"] == at.Path("r.json") and seen[0]["repeats"] is None
