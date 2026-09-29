"""Parity on a real dev run (opt-in: `pytest -q -m opendata`): the committed replay
stream through the committed pca_v2 bundle equals the evaluation scoring path on the
same dev run, loaded from the open data. Decision 19: one scoring engine.

Builder side: the run's fault and number come from eval/replay_source.yaml, never from
app/. Skipped until app/bundles/pca_v2 is built (Raj runs build_bundle), or when data/
is absent.
"""

from pathlib import Path

import numpy as np
import pytest
import yaml

from app.detector import bundle as bm
from app.detector import rbc, replay
from dataset import loader
from eval import calibrate_driver as drv
from eval import calibrate_watch as cw
from eval import metrics

REPO = Path(__file__).resolve().parents[1]
V2 = REPO / "app" / "bundles" / "pca_v2"
SOURCE = REPO / "eval" / "replay_source.yaml"
RATIO_REL = 1e-9

pytestmark = [pytest.mark.opendata,
              pytest.mark.skipif(not V2.exists(), reason="pca_v2 not built yet"),
              pytest.mark.skipif(not SOURCE.exists(), reason="replay stream not exported")]


def test_replay_equals_the_evaluation_path_on_the_dev_run():
    b = bm.load(V2)
    assert bm.self_test(b)
    src = yaml.safe_load(SOURCE.read_text())
    try:
        runs = loader.load_faulty(src["fault"], src["pool"])
    except (loader.LoaderError, FileNotFoundError) as e:
        pytest.skip(f"open data not available: {e}")
    one = type(runs)(runs.name, runs.fault, runs.pool, runs.columns, {src["run"]: runs.runs[src["run"]]})
    lim = b.limits
    scored = drv.score_runs(b.model, one)
    track = drv.tracks(scored, (lim["t2_lim"], lim["spe_lim"]), lim["n"], lim["gap"], lim["warmup"])[src["run"]]
    t2, spe = scored[src["run"]]
    ratio = np.maximum(t2 / lim["t2_lim"], spe / lim["spe_lim"])
    names = list(b.watch["groups"])
    by_group, _ = cw.rbc_runs(b.model, lim, one, names)
    g_ratio = by_group[src["run"]] / np.array([b.watch["groups"][g]["w"] for g in names])

    stream = replay.read_csv(REPO / src["csv"], b.model.tags)
    rows = replay.status(b, stream, stream.ts[-1])
    w = lim["warmup"]
    assert len(rows) == len(track) == src["samples"]
    for i, r in enumerate(rows):
        if i < w:
            assert r["band"] == "Unknown" and r["reason"] == "warm-up"
            continue
        want = "Alert" if track[i] else ("Watch" if (g_ratio[i] > 1).any() else "Normal")
        assert r["band"] == want, f"sample {i + 1}"
        assert r["ratio"] == pytest.approx(ratio[i], rel=RATIO_REL)
        assert [r["groups"][g]["ratio"] for g in names] == pytest.approx(g_ratio[i].tolist(), rel=RATIO_REL)
    for t in metrics.notifications(track, w):
        assert rows[t - 1]["attributed"] == names[rbc.rank_at(g_ratio, t, lim["n"])[1][0]]
