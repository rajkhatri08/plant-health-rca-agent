"""A versioned detector bundle and its startup self-test (decision 21).

A bundle is a folder, e.g. app/bundles/pca_v1/, holding:
- model.npz    the PCA arrays (app/detector/pca.py; no pickles)
- limits.json  limits, persistence and grouping (decisions 53-55), the model's SHA-256,
               and the SHA-256 of the fit and calibration run records it came from
- watch.json   (from pca_v2 on) the Watch boundaries (decisions 64-66): the shared
               percentile p, each group's tags and W_g, each tag's W_i, the model's
               SHA-256 and the SHA-256 of the calibrate_watch run record. Without it the
               bundle gives the thin slice's bands (Unknown, Alert, Normal).

Runtime code: no imports from dataset/, eval/ or ingest/. The tag list is checked
against the agent-visible register, library/tags.yaml.

self_test() refuses a bundle whose files don't fit together, so the app never scores
with a half-copied or mismatched model. It raises BundleError naming the first problem.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml

from app.detector import groups as groups_mod
from app.detector import pca, rbc

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BUNDLE = REPO_ROOT / "app" / "bundles" / "pca_v1"
REGISTER = REPO_ROOT / "library" / "tags.yaml"
FAST_KINDS = ("measurement", "valve")
LIMIT_KEYS = ("detector", "model_sha256", "warmup", "lags", "n", "gap", "q", "t2_lim", "spe_lim",
              "fit_record_sha256", "calibration_record_sha256")
WATCH_KEYS = ("detector", "model_sha256", "limits_sha256", "warmup", "p", "cap", "groups", "tags",
              "watch_record_sha256")
_SHA = re.compile(r"^[0-9a-f]{64}$")


class BundleError(RuntimeError):
    pass


@dataclass(frozen=True)
class Bundle:
    name: str
    model: pca.PCAModel
    limits: dict
    model_sha256: str
    watch: dict | None = None             # watch.json, when the bundle has Watch boundaries


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fast_tags(register=REGISTER):
    """The detector's tags, in register order: every measurement and valve."""
    rows = yaml.safe_load(Path(register).read_text())["tags"]
    return tuple(r["tag"] for r in rows if r["kind"] in FAST_KINDS)


def load(folder=DEFAULT_BUNDLE):
    folder = Path(folder)
    model_path, limits_path = folder / "model.npz", folder / "limits.json"
    for p in (model_path, limits_path):
        if not p.is_file():
            raise BundleError(f"bundle file missing: {p.name}")
    watch_path = folder / "watch.json"
    watch = json.loads(watch_path.read_text()) if watch_path.is_file() else None
    return Bundle(name=folder.name, model=pca.load(model_path),
                  limits=json.loads(limits_path.read_text()), model_sha256=sha256(model_path),
                  watch=watch)


def _positive(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and np.isfinite(v) and v > 0


def _check_watch(bundle, register):
    """The Watch file fits the model, the limits and the register; raise BundleError if not."""
    m, lim, w = bundle.model, bundle.limits, bundle.watch
    missing = [k for k in WATCH_KEYS if k not in w]
    if missing:
        raise BundleError(f"watch.json lacks {missing}")
    if w["model_sha256"] != bundle.model_sha256:
        raise BundleError("watch.json was calibrated for another model")
    for key in ("limits_sha256", "watch_record_sha256"):
        if not (isinstance(w[key], str) and _SHA.match(w[key])):
            raise BundleError(f"watch.json {key} isn't a SHA-256")
    if w["warmup"] != lim["warmup"] or w["detector"] != lim["detector"]:
        raise BundleError("watch.json's warm-up or detector differs from limits.json")
    if lim["lags"] != 0:
        raise BundleError("Watch needs static PCA: RBC isn't built for lagged models (decision 64)")
    if not (_positive(w["p"]) and w["p"] <= 100):
        raise BundleError("watch.json p must be in (0, 100]")
    try:
        table = groups_mod.load(m.tags, register)
    except groups_mod.GroupError as e:
        raise BundleError(f"groups: {e}") from None
    if list(w["groups"]) != list(table):
        raise BundleError("watch.json's groups aren't the register's groups, in order")
    for g, cols in table.items():
        entry = w["groups"][g]
        if entry.get("tags") != [m.tags[i] for i in cols]:
            raise BundleError(f"watch.json group {g} doesn't hold the register's tags, in model order")
        if not _positive(entry.get("w")):
            raise BundleError(f"watch.json group {g} boundary must be a finite number > 0")
    if list(w["tags"]) != list(m.tags) or not all(_positive(v) for v in w["tags"].values()):
        raise BundleError("watch.json tag boundaries must cover the model's tags, each finite and > 0")
    # Known answer: at the fit mean nothing is abnormal, so every group's RBC is 0.
    M = rbc.index_matrix(m, lim["t2_lim"], lim["spe_lim"])
    at_mean = rbc.group_rbc(m, M, m.mean[None, :], list(table.values()))
    if not np.all(np.abs(at_mean) < 1e-9):
        raise BundleError("group RBC at the fit mean isn't 0")


def self_test(bundle, register=REGISTER):
    """Check that the bundle fits together; raise BundleError on the first problem."""
    m, lim = bundle.model, bundle.limits

    missing = [k for k in LIMIT_KEYS if k not in lim]
    if missing:
        raise BundleError(f"limits.json lacks {missing}")
    if lim["model_sha256"] != bundle.model_sha256:
        raise BundleError("model.npz isn't the model these limits were calibrated for")
    for key in ("model_sha256", "fit_record_sha256", "calibration_record_sha256"):
        if not (isinstance(lim[key], str) and _SHA.match(lim[key])):
            raise BundleError(f"limits.json {key} isn't a SHA-256")
    for key in ("warmup", "lags", "n", "gap"):
        if isinstance(lim[key], bool) or not isinstance(lim[key], int) or lim[key] < 0:
            raise BundleError(f"limits.json {key} must be a non-negative integer")
    if lim["n"] < 1 or lim["lags"] + lim["n"] - 1 > lim["warmup"]:
        raise BundleError("persistence doesn't fit the warm-up (decision 52)")
    for key in ("t2_lim", "spe_lim"):
        if not (isinstance(lim[key], (int, float)) and np.isfinite(lim[key]) and lim[key] > 0):
            raise BundleError(f"limits.json {key} must be a finite number > 0")

    if m.tags != fast_tags(register):
        raise BundleError("the model's tags aren't the register's measurements and valves, in order")
    n_tags, k = len(m.tags), m.k
    shapes = {"mean": (m.mean.shape, (n_tags,)), "scale": (m.scale.shape, (n_tags,)),
              "loadings": (m.loadings.shape, (n_tags, k)), "eigenvalues": (m.eigenvalues.shape, (k,)),
              "all_eigenvalues": (m.all_eigenvalues.shape, (n_tags,))}
    for name, (got, want) in shapes.items():
        if got != want:
            raise BundleError(f"model {name} has shape {got}, expected {want}")
    arrays = (m.mean, m.scale, m.loadings, m.eigenvalues, m.all_eigenvalues)
    if not all(np.isfinite(a).all() for a in arrays):
        raise BundleError("model holds NaN or inf")
    if not (m.scale > 0).all():
        raise BundleError("model has a zero or negative scale")
    if k < 1 or not np.array_equal(m.eigenvalues, m.all_eigenvalues[:k]):
        raise BundleError("kept eigenvalues aren't the leading eigenvalues")
    if (np.diff(m.all_eigenvalues) > 1e-12).any() or not (m.eigenvalues > 0).all():
        raise BundleError("eigenvalues aren't positive and descending")
    if not np.allclose(m.loadings.T @ m.loadings, np.eye(k), atol=1e-8):
        raise BundleError("loadings aren't orthonormal")
    # Known answer: the fit mean is the centre of the model, so both statistics are 0.
    t2, spe = pca.scores(m, m.mean[None, :])
    if not (abs(t2[0]) < 1e-9 and abs(spe[0]) < 1e-9):
        raise BundleError("scoring the fit mean doesn't give T² = SPE = 0")
    if bundle.watch is not None:
        _check_watch(bundle, register)
    return True