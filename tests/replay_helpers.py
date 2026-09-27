"""Synthetic bundles and historian CSVs for the bundle, replay and API tests."""

import csv
import hashlib
import json

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