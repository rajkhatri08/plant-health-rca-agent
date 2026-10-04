"""Synthetic bundles and historian CSVs for the bundle, replay and API tests."""

import csv
import hashlib
import json

import numpy as np

from app.detector import pca
from eval import fit_pca
from ingest import export_replay
from tests.test_fit_pca import FAST, two_factor_runs

SHA_A = "a" * 64
SHA_B = "b" * 64


def make_bundle(folder, *, warmup=3, n=2, gap=1, t2_lim=6.0, spe_lim=40.0):
    """A self-consistent bundle folder from a two-factor model on the real fast tags."""
    folder.mkdir(parents=True)
    runs = two_factor_runs(samples=120)
    model = pca.fit(fit_pca.fit_matrix(runs, warmup, FAST), FAST, 2)
    pca.save(model, folder / "model.npz")
    limits = {"detector": "pca_static",
              "model_sha256": hashlib.sha256((folder / "model.npz").read_bytes()).hexdigest(),
              "warmup": warmup, "lags": 0, "n": n, "gap": gap, "q": 99.0,
              "t2_lim": t2_lim, "spe_lim": spe_lim,
              "fit_record_sha256": SHA_A, "calibration_record_sha256": SHA_B}
    (folder / "limits.json").write_text(json.dumps(limits))
    return folder


SHA_C = "c" * 64


def add_watch(folder, p=99.0):
    """Give a make_bundle folder a watch.json (a pca_v2-style bundle). Each group's W_g and
    each tag's W_i is the p-th percentile of its RBC on other normal runs, after warm-up,
    the same form as the Watch calibration."""
    from app.detector import bundle as bm
    from app.detector import groups, rbc
    b = bm.load(folder)
    lim, model = b.limits, b.model
    table = groups.load(model.tags)
    M = rbc.index_matrix(model, lim["t2_lim"], lim["spe_lim"])
    runs = two_factor_runs(numbers=range(40, 50), samples=120, seed=21)
    from dataset.convert import VARIABLES
    from ingest import tags as tagmap
    cols = tagmap.column_indices(VARIABLES, FAST)
    X = [runs.runs[k][:, cols] for k in sorted(runs.runs)]
    g = np.vstack([rbc.group_rbc(model, M, x, list(table.values()))[lim["warmup"]:] for x in X])
    t = np.vstack([rbc.tag_rbc(model, M, x)[lim["warmup"]:] for x in X])
    w_g, w_t = np.percentile(g, p, axis=0), np.percentile(t, p, axis=0)
    watch = {"detector": lim["detector"], "model_sha256": b.model_sha256, "limits_sha256": SHA_C,
             "warmup": lim["warmup"], "p": p, "cap": 0.02,
             "groups": {name: {"tags": [model.tags[i] for i in cols_], "w": float(w)}
                        for (name, cols_), w in zip(table.items(), w_g)},
             "tags": {tag: float(w) for tag, w in zip(model.tags, w_t)},
             "watch_record_sha256": SHA_A}
    (folder / "watch.json").write_text(json.dumps(watch))
    return folder


SHA_D = "d" * 64


def add_normals(folder, band=(0.5, 99.5)):
    """Give a make_bundle + add_watch folder a normals.json (a pca_v3-style bundle). Each
    register tag's band is its central 99% over other normal runs after warm-up, the same
    form as eval/evidence_normals.py; analyzers are read as stored (here unheld noise)."""
    from app.detector import bundle as bm
    from dataset.convert import VARIABLES
    from ingest import tags as tagmap
    lim = bm.load(folder).limits
    tags = [r["tag"] for r in tagmap.register()]
    cols = tagmap.column_indices(VARIABLES, tags)
    runs = two_factor_runs(numbers=range(60, 70), samples=120, seed=33)
    X = np.vstack([runs.runs[k][lim["warmup"]:, cols] for k in sorted(runs.runs)]).astype(np.float64)
    lo, hi = np.percentile(X, band[0], axis=0), np.percentile(X, band[1], axis=0)
    doc = {"pool": "calibration", "runs": 10, "warmup": lim["warmup"], "band": list(band),
           "tags": {t: [float(a), float(b)] for t, a, b in zip(tags, lo, hi)},
           "normals_record_sha256": SHA_D}
    (folder / "normals.json").write_text(json.dumps(doc))
    return folder


def edit_normals(folder, **changes):
    path = folder / "normals.json"
    path.write_text(json.dumps({**json.loads(path.read_text()), **changes}))


def edit_watch(folder, **changes):
    path = folder / "watch.json"
    path.write_text(json.dumps({**json.loads(path.read_text()), **changes}))


def edit_limits(folder, **changes):
    path = folder / "limits.json"
    limits = {**json.loads(path.read_text()), **changes}
    path.write_text(json.dumps(limits))


def stream_run(samples=60, seed=5, shift_from=30, shift=4.0):
    """One run (raw columns) with a step on the fast tags from sample shift_from."""
    runs = two_factor_runs(numbers=[1], samples=samples, seed=seed)
    from dataset.convert import VARIABLES
    from ingest import tags as tagmap
    cols = tagmap.column_indices(VARIABLES, FAST)
    x = runs.runs[1]
    x[shift_from - 1:, cols] += shift
    return x, VARIABLES


def write_csv(path, values, columns, rows_filter=None):
    """A historian CSV via the exporter's own row generator; rows_filter may edit rows."""
    rows = list(export_replay.historian_rows(values, columns, FAST))
    if rows_filter:
        rows = rows_filter(rows)
    with open(path, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["ts", "tag", "value", "quality"])
        w.writerows(rows)
    return path