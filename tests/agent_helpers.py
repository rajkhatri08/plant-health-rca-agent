"""Shared pieces for the graph tests and their command line (tests/agent_cli.py).

- FakeTools: evidence() and retrieve() with the real tools' output forms. The evidence is
  hand-built per history, so the matcher's outcome on the committed library is known
  (tests/test_agent_graph.py checks each scenario's ranking first):
    H_DRIFT  reaction-rate-drift fits (fit 1, no contradiction): the matcher proposes
    H_QUIET  every entry has a required contradiction: a hard decline
  The revised reading appears only when as_of is at least notified_at + 60 min.
- ANSWERS: scripted LLM answers by name; FakeClient answers with one of them.
- render: a test template (not Raj's): the evidence, the candidates and the note as JSON.
- open_graph(folder, ...): the real graph on these, with SQLite checkpoints, records and an
  LLM cache in folder, as the command line opens it in another process.

Times are in 2020 on purpose: a node that read the clock would be years off.
"""

import json
from datetime import datetime, timedelta
from fractions import Fraction
from pathlib import Path

from app.agent import graph as ag
from app.agent import llm, records
from app.detector import bundle, features
from app.library import store
from shared import leak_scan

NOTIFIED = "2020-01-01T08:00:00+00:00"
PLUS_30 = "2020-01-01T08:30:00+00:00"
PLUS_60 = "2020-01-01T09:00:00+00:00"
LIBRARY_AS_OF = "2026-10-05T00:00:00+00:00"       # after mixed-feed-temperature-wander's r2 approval
THRESHOLDS = {"provisional": Fraction(1, 3), "revised": Fraction(5, 11)}   # the dev record's (decision 72)

H_DRIFT = ag.opaque_id("h", "drift")
H_QUIET = ag.opaque_id("h", "quiet")
EP = ag.opaque_id("ep", "test-episode", 1)
DRIFT_REF = "reaction-rate-drift@r1"
DRIFT_CANDIDATES = ["reaction-rate-drift@r1", "reactor-cooling-water-temperature-wander@r1"]


def _reading(plant, tags=(), loops=(), masked=False):
    tags, loops = dict(tags), dict(loops)
    return {"tags": {t: tags.get(t, "normal") for t in plant.fast_tags},
            "loops": {i: loops.get(i, "held") for i in plant.loops},
            "analyzers": {a: "normal" for a in plant.analyzers}, "masked": masked}


def scenarios():
    plant = features.plant_from_files(bundle.fast_tags())
    drift_loops = {"CP-FIC-501": "compensating"}
    return {
        H_DRIFT: {"location": {"top_group": "reactor", "top_tags": ["RX-PI-202", "SP-PI-403", "ST-PI-602"]},
                  "provisional": _reading(plant, {"RX-PI-202": "low", "SP-PI-403": "low", "ST-PI-602": "low"},
                                          drift_loops),
                  "revised": _reading(plant, {"RX-PI-202": "low"}, drift_loops)},
        H_QUIET: {"location": {"top_group": "compressor", "top_tags": ["CP-FI-501", "CP-JI-502", "CP-FV-503"]},
                  "provisional": _reading(plant), "revised": _reading(plant)},
    }


class FakeTools:
    """The tools' interface on hand-built evidence and the real library."""

    def __init__(self, library):
        self.library, self.histories, self.calls = library, scenarios(), []

    def evidence(self, history_id, notified_at, as_of):
        for t in (notified_at, as_of):
            assert isinstance(t, datetime) and t.tzinfo is not None, "times must be aware datetimes"
        self.calls.append(("evidence", history_id, notified_at.isoformat(), as_of.isoformat()))
        f = self.histories[history_id]
        feats = {"location": f["location"], "provisional": f["provisional"]}
        if as_of >= notified_at + timedelta(minutes=60):
            feats["revised"] = f["revised"]
        return {"notified_at": notified_at.isoformat(), "as_of": as_of.isoformat(), "features": feats}

    def retrieve(self, entry_ids, as_of):
        assert isinstance(as_of, datetime) and as_of.tzinfo is not None
        self.calls.append(("retrieve", tuple(entry_ids), as_of.isoformat()))
        entries, missing = [], []
        for e in dict.fromkeys(entry_ids):
            got = self.library.get(e, as_of)
            (missing.append(e) if got is None else entries.append(store.agent_view(got)))
        out = {"as_of": as_of.isoformat(), "entries": entries, "not_in_force": missing}
        leak_scan.check(json.dumps(out, sort_keys=True), "retrieve")
        return out


def _cite(*pairs):
    return [{"item": i, "state": s} for i, s in pairs]


ANSWERS = {
    "propose": {"decision": "propose", "entry_ref": DRIFT_REF, "family": "reaction kinetics", "confidence": "high",
                "cited_evidence": _cite(("provisional.tags.RX-PI-202", "low"), ("location.top_group", "reactor")),
                "action_ids": ["check-reaction-conditions", "escalate-to-process-engineer"],
                "rationale": "RX-PI-202 and SP-PI-403 are low while CP-FIC-501 compensates."},
    "decline": {"decision": "decline", "entry_ref": None, "family": None, "confidence": "low",
                "cited_evidence": _cite(("provisional.tags.RX-PI-202", "low")), "action_ids": [],
                "rationale": "The evidence is too weak to name a mechanism."},
    "not_in_library": {"decision": "not_in_library", "entry_ref": None, "family": "reaction kinetics",
                       "confidence": "medium", "cited_evidence": _cite(("location.top_group", "reactor")),
                       "action_ids": [], "rationale": "A kinetics change, but not the drift the entry describes."},
    "unfaithful": {"decision": "propose", "entry_ref": DRIFT_REF, "family": "reaction kinetics",
                   "confidence": "high",
                   "cited_evidence": _cite(("provisional.tags.RX-PI-202", "high"), ("location.top_group", "reactor")),
                   "action_ids": ["check-reaction-conditions"], "rationale": "RX-PI-202 is high."},
}


def answer_for(name):
    if name == "not_json":
        return lambda p, s, r: "this is not JSON"
    if name == "api_error":
        return lambda p, s, r: llm.LLMError("the API failed 3 times: APIError 503")
    doc = json.dumps(ANSWERS[name])
    return lambda p, s, r: doc


def render(features_, candidates, operator_note):
    return json.dumps({"evidence": features_, "candidates": candidates, "note": operator_note}, sort_keys=True)


def open_graph(folder, answer="propose", thresholds=THRESHOLDS, render_fn=render, fake=None):
    """(graph, deps, fake client) on folder's checkpoints.db, records.db and cache/."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    library = store.load()
    fake = fake or llm.FakeClient(answer_for(answer))
    rec = records.RecordStore(folder / "records.db")
    deps = ag.Deps(tools=FakeTools(library), library=library, client=llm.CachedClient(fake, folder / "cache"),
                   records=rec, render=render_fn, thresholds=thresholds, k=2)
    return ag.build(ag.open_checkpointer(folder / "checkpoints.db"), deps), deps, fake


def cache_entries(folder):
    return sorted(Path(folder, "cache").rglob("*.json"))