"""Decision 73's five pass criteria for the LangGraph spike, one group each.

    pytest -q spikes/langgraph

Most tests fail with NotImplementedError until Raj implements spikes/langgraph/nodes.py.
The harness tests (wiring, the record store, the tracing guard, verdict checks) pass now.

Times are in 2020 on purpose: a node that read the clock would give an as_of years away
from notified_at + 30 or + 60 min.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from spikes.langgraph import cli, nodes
from spikes.langgraph import graph as hg
from spikes.langgraph.records import RecordStore

REPO = Path(__file__).resolve().parents[2]
NOTIFIED = "2020-01-01T08:00:00+00:00"
PLUS_30 = "2020-01-01T08:30:00+00:00"
PLUS_60 = "2020-01-01T09:00:00+00:00"


@pytest.fixture
def world(tmp_path):
    g, records = cli.open_graph(tmp_path)
    return {"dir": tmp_path, "graph": g, "records": records}


def run_cli(folder, *args):
    """One step in a fresh Python process; returns its JSON."""
    out = subprocess.run([sys.executable, "-m", "spikes.langgraph.cli", str(folder), *args],
                         cwd=REPO, capture_output=True, text=True,
                         env={**os.environ, "PYTHONPATH": os.pathsep.join(
                             [str(REPO)] + [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p])})
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


# ---------- 1. fixed graph ----------

def test_the_wiring_is_fixed_in_code(world):
    view = world["graph"].get_graph()
    assert set(view.nodes) == {"__start__", "__end__", *hg.NODES}
    edges = {(e.source, e.target, e.conditional) for e in view.edges}
    assert edges == {("__start__", "evidence", False), ("evidence", "match", False),
                     ("match", "propose", True), ("match", "decline", True), ("decline", "__end__", False),
                     ("propose", "approval", False), ("approval", "act", True), ("approval", "__end__", True),
                     ("act", "__end__", False)}


@pytest.mark.parametrize("decision", ["propose", "decline"])
def test_route_reads_only_the_decision(decision):
    assert nodes.route({"decision": decision}) == decision


@pytest.mark.parametrize("verdict, branch", [("approve", "act"), ("reject", "end")])
def test_after_approval(verdict, branch):
    assert nodes.after_approval({"approval": verdict}) == branch


def test_no_agreeing_entry_declines_without_approval_or_action(world):
    s = hg.start(world["graph"], "unknown-1", NOTIFIED)
    assert s["values"]["decision"] == "decline" and s["values"]["outcome"] == "declined"
    assert "proposal" not in s["values"] and s["next"] == []
    assert world["records"].all() == []


def test_an_agreeing_entry_is_proposed(world):
    s = hg.start(world["graph"], "ep-1", NOTIFIED)
    v = s["values"]
    assert v["ranking"][0] == "toy-warm-supply" and v["decision"] == "propose"
    assert v["proposal"] == {"entry": "toy-warm-supply", "action_id": "check-toy-supply",
                             "key": "ep-1:provisional:check-toy-supply"}


# ---------- 2. approval pause and resume ----------

def test_pauses_before_the_action(world):
    s = hg.start(world["graph"], "ep-1", NOTIFIED)
    assert s["next"] == ["approval"] and hg.waiting(world["graph"], "ep-1")
    assert world["records"].all() == []


def test_approve_acts(world):
    hg.start(world["graph"], "ep-1", NOTIFIED)
    s = hg.decide(world["graph"], "ep-1", "approve")
    assert s["values"]["outcome"] == "acted" and s["values"]["done"] == "ep-1:provisional:check-toy-supply"
    assert s["next"] == []
    ((key, payload),) = world["records"].all()
    assert key == "ep-1:provisional:check-toy-supply"
    assert payload == {"episode": "ep-1", "stage": "provisional", "entry": "toy-warm-supply",
                       "action_id": "check-toy-supply", "as_of": PLUS_30}


def test_reject_ends_without_the_action(world):
    hg.start(world["graph"], "ep-1", NOTIFIED)
    s = hg.decide(world["graph"], "ep-1", "reject")
    assert s["values"]["approval"] == "reject" and s["next"] == []
    assert "done" not in s["values"] and world["records"].all() == []


def test_only_approve_or_reject(world):
    with pytest.raises(hg.SpikeError):
        hg.decide(world["graph"], "ep-1", "yes please")


def test_approval_node_refuses_another_verdict(world):
    hg.start(world["graph"], "ep-1", NOTIFIED)
    with pytest.raises(ValueError):
        world["graph"].invoke(hg.Command(resume="supervisor says ok"), hg.config("ep-1"))
    assert world["records"].all() == []


# ---------- 3. state saved and reloaded in a new process ----------

def test_a_new_process_resumes_with_identical_state(tmp_path):
    started = run_cli(tmp_path, "start", "ep-1", NOTIFIED)           # process A pauses
    reloaded = run_cli(tmp_path, "state", "ep-1")                    # process B reads it back
    assert reloaded == started and reloaded["next"] == ["approval"]
    done = run_cli(tmp_path, "decide", "ep-1", "approve")            # process C resumes it
    assert done["values"]["outcome"] == "acted"
    assert [k for k, _ in run_cli(tmp_path, "records")] == ["ep-1:provisional:check-toy-supply"]


# ---------- 4. re-entry at +60 min ----------

def test_provisional_as_of_is_from_the_state(world):
    assert hg.start(world["graph"], "ep-1", NOTIFIED)["values"]["as_of"] == PLUS_30


def test_re_entry_takes_as_of_from_the_saved_state(world):
    hg.start(world["graph"], "ep-1", NOTIFIED)
    hg.decide(world["graph"], "ep-1", "approve")
    s = hg.re_enter(world["graph"], "ep-1")
    v = s["values"]
    assert v["stage"] == "revised" and v["as_of"] == PLUS_60 and v["notified_at"] == NOTIFIED
    assert v["reading"] == {"RX-FV-206": "high", "RX-TI-204": "normal"}          # the revised reading
    assert s["next"] == ["approval"]
    assert v["proposal"]["key"] == "ep-1:revised:check-toy-supply"                 # a new action key


def test_re_entry_in_a_new_process(tmp_path):
    run_cli(tmp_path, "start", "ep-1", NOTIFIED)
    run_cli(tmp_path, "decide", "ep-1", "reject")
    s = run_cli(tmp_path, "reenter", "ep-1")
    assert s["values"]["as_of"] == PLUS_60 and s["values"]["reading"]["RX-TI-204"] == "normal"


def test_re_entry_refused_while_waiting_or_before_start(world):
    with pytest.raises(hg.SpikeError):
        hg.re_enter(world["graph"], "ep-1")
    hg.start(world["graph"], "ep-1", NOTIFIED)
    with pytest.raises(hg.SpikeError):
        hg.re_enter(world["graph"], "ep-1")


def test_an_episode_starts_once(world):
    hg.start(world["graph"], "ep-1", NOTIFIED)
    with pytest.raises(hg.SpikeError):
        hg.start(world["graph"], "ep-1", NOTIFIED)


# ---------- 5. exactly once ----------

def test_the_store_writes_a_key_once(tmp_path):
    store = RecordStore(tmp_path / "r.db")
    assert store.insert_once("k", {"a": 1}) is True
    assert store.insert_once("k", {"a": 2}) is False
    assert RecordStore(tmp_path / "r.db").all() == [("k", {"a": 1})]          # another handle sees it


def test_resume_called_twice_writes_once(world):
    hg.start(world["graph"], "ep-1", NOTIFIED)
    hg.decide(world["graph"], "ep-1", "approve")
    try:
        hg.decide(world["graph"], "ep-1", "approve")                # nothing is waiting any more
    except Exception:                                                # refusing is fine; a second write isn't
        pass
    assert len(world["records"].all()) == 1


class Crash(Exception):
    """The process stops after act's write, before LangGraph saves the step."""


def test_a_crash_after_the_write_still_leaves_one_record(tmp_path, monkeypatch):
    g, records = cli.open_graph(tmp_path)
    hg.start(g, "ep-1", NOTIFIED)
    real = RecordStore.insert_once

    def write_then_crash(self, key, payload):
        real(self, key, payload)
        raise Crash()

    monkeypatch.setattr(RecordStore, "insert_once", write_then_crash)
    with pytest.raises(Crash):
        hg.decide(g, "ep-1", "approve")
    monkeypatch.undo()
    assert len(records.all()) == 1                                   # the write happened
    assert hg.snapshot(g, "ep-1")["next"] == ["act"]                 # but the step wasn't saved
    s = run_cli(tmp_path, "retry", "ep-1")                           # a new process runs act again
    assert s["values"]["outcome"] == "acted" and s["next"] == []
    assert len(run_cli(tmp_path, "records")) == 1                    # still one record


# ---------- the harness's guard ----------

def test_refuses_to_run_with_tracing_on(tmp_path, monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    with pytest.raises(hg.SpikeError):
        cli.open_graph(tmp_path)


def test_spike_is_outside_app_and_eval():
    for d in ("app", "eval"):
        for p in (REPO / d).rglob("*.py"):
            assert "spikes" not in p.read_text(), p
