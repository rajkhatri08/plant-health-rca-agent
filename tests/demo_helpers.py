"""A synthetic public demo for the tests (week 6 S9): a pca_v3-style bundle, two episodes' streams
with analyzers (each with one clear alert, at different places), the committed library, Raj's real
prompt template, and a FakeClient behind the cache. Never the API, never data/."""

import csv
import json

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
SAMPLES = 90
EPISODE_STEPS = {"1": (30, 4.0, 11), "2": (50, -4.0, 23)}   # (step sample, size, seed) per episode
THRESHOLDS = {"provisional": "-1", "revised": "-1"}      # low, so the matcher proposes and the LLM is called
DECLINE = json.dumps({"decision": "decline", "entry_ref": None, "family": None, "confidence": "low",
                      "cited_evidence": [], "action_ids": [], "rationale": "The evidence doesn't single out an entry."})


def write_stream(path, step_from, size, seed):
    x = held_runs(numbers=[1], samples=SAMPLES, seed=seed).runs[1]
    x[step_from - 1:, tagmap.column_indices(VARIABLES, FAST)] += np.float32(size)
    pubs = ex.publications(x, VARIABLES, ex.analyzer_intervals())
    with open(path, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(replay.HEADER)
        w.writerows(ex.stream_rows(x, VARIABLES, FAST, pubs))
    return path


def make_world(tmp_path, folder=None):
    """(bundle, {episode: csv path}): a v3-style bundle and both episodes' streams, under folder
    (default tmp_path / "demo") with demo.EPISODES's file names."""
    b = bm.load(add_normals(add_watch(make_bundle(tmp_path / "pca_v3"))))
    folder = folder or tmp_path / "demo"
    folder.mkdir(parents=True, exist_ok=True)
    streams = {e: write_stream(folder / demo.EPISODES[e], *EPISODE_STEPS[e]) for e in demo.EPISODES}
    return b, streams


def config_for(b, streams):
    notified = {e: demo.notification_time(b, tools.load_history(p, b).stream) for e, p in streams.items()}
    return {"library_as_of": LIB, "thresholds": THRESHOLDS, "k": 2, "prompt_sha256": "test",
            "schema_version": ag.sc.SCHEMA_VERSION, "settings": llm.SETTINGS.as_dict(), "notes": demo.NOTES,
            "bundle": b.name, "episodes": {e: {"stream": demo.EPISODES[e],
                                               "notified_at": notified[e].strftime(replay.TS_FORMAT)}
                                           for e in streams}}


def build_demo_dir(tmp_path, answer=DECLINE):
    """(demo dir, bundle, {episode: csv path}, fake client): the streams, demo.json and llm_cache/
    as the builder writes them, the answers from a FakeClient."""
    b, streams = make_world(tmp_path)
    demo_dir = streams["1"].parent
    cfg = config_for(b, streams)
    fake = llm.FakeClient(lambda p, s, r: answer)
    client = llm.CachedClient(fake, demo_dir / demo.CACHE)
    for e, path in streams.items():
        demo.build_views(b, store.load(), tools.load_history(path, b), client, diagnosis.render, cfg,
                         notified_at=replay.parse_ts(cfg["episodes"][e]["notified_at"]), episode=e,
                         workdir=tmp_path / f"build_{e}")
    (demo_dir / demo.CONFIG).write_text(json.dumps(cfg, indent=2, sort_keys=True))
    return demo_dir, b, streams, fake
