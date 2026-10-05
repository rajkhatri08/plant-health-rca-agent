"""A synthetic public demo for the tests (week 6 S9): a pca_v3-style bundle, a stream with
analyzers and one clear alert, the committed library, Raj's real prompt template, and a
FakeClient behind the cache. Never the API, never data/."""

import csv
import json
from fractions import Fraction

import numpy as np

from app.agent import demo, llm, tools
from app.agent import graph as ag
from app.agent.prompts import diagnosis
from app.detector import bundle as bm
from app.detector import replay
from app.library import store
from dataset.convert import VARIABLES
from ingest import export_replay as ex
from ingest import tags as tagmap
from tests.replay_helpers import add_normals, add_watch, make_bundle
from tests.test_export_replay import held_runs
from tests.test_fit_pca import FAST

LIB = "2026-10-05T00:00:00+00:00"
SAMPLES, STEP_FROM = 90, 30
THRESHOLDS = {"provisional": "-1", "revised": "-1"}      # low, so the matcher proposes and the LLM is called
DECLINE = json.dumps({"decision": "decline", "entry_ref": None, "family": None, "confidence": "low",
                      "cited_evidence": [], "action_ids": [], "rationale": "The evidence doesn't single out an entry."})


def make_world(tmp_path):
    """(bundle, csv path) for a v3-style bundle and a stream that alerts at the step."""
    b = bm.load(add_normals(add_watch(make_bundle(tmp_path / "pca_v3"))))
    x = held_runs(numbers=[1], samples=SAMPLES, seed=11).runs[1]
    x[STEP_FROM - 1:, tagmap.column_indices(VARIABLES, FAST)] += np.float32(4.0)
    path = tmp_path / "run_v2.csv"
    pubs = ex.publications(x, VARIABLES, ex.analyzer_intervals())
    with open(path, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(replay.HEADER)
        w.writerows(ex.stream_rows(x, VARIABLES, FAST, pubs))
    return b, path


def config_for(b, csv_path):
    history = tools.load_history(csv_path, b)
    notified = demo.notification_time(b, history.stream)
    return {"library_as_of": LIB, "thresholds": THRESHOLDS, "k": 2, "prompt_sha256": "test",
            "schema_version": ag.sc.SCHEMA_VERSION, "settings": llm.SETTINGS.as_dict(), "notes": demo.NOTES,
            "notified_at": notified.strftime(replay.TS_FORMAT), "bundle": b.name, "stream": csv_path.name}


def build_demo_dir(tmp_path, answer=DECLINE):
    """(demo dir, bundle, csv path, fake client): demo.json and llm_cache/ as the builder writes
    them, the answers from a FakeClient."""
    b, csv_path = make_world(tmp_path)
    cfg = config_for(b, csv_path)
    demo_dir = tmp_path / "demo"
    demo_dir.mkdir()
    fake = llm.FakeClient(lambda p, s, r: answer)
    history = tools.load_history(csv_path, b)
    demo.build_views(b, store.load(), history, llm.CachedClient(fake, demo_dir / demo.CACHE), diagnosis.render, cfg,
                     notified_at=replay.parse_ts(cfg["notified_at"]), workdir=tmp_path / "build")
    (demo_dir / demo.CONFIG).write_text(json.dumps(cfg, indent=2, sort_keys=True))
    return demo_dir, b, csv_path, fake


def thresholds(cfg):
    return {st: Fraction(t) for st, t in cfg["thresholds"].items()}
