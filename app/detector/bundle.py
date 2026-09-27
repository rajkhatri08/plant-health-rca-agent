"""A versioned detector bundle and its startup self-test (decision 21).

A bundle is a folder, e.g. app/bundles/pca_v1/, holding:
- model.npz    the PCA arrays (app/detector/pca.py; no pickles)
- limits.json  limits, persistence and grouping (decisions 53-55), the model's SHA-256,
               and the SHA-256 of the fit and calibration run records it came from

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

from app.detector import pca

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BUNDLE = REPO_ROOT / "app" / "bundles" / "pca_v1"
REGISTER = REPO_ROOT / "library" / "tags.yaml"
FAST_KINDS = ("measurement", "valve")
LIMIT_KEYS = ("detector", "model_sha256", "warmup", "lags", "n", "gap", "q", "t2_lim", "spe_lim",
              "fit_record_sha256", "calibration_record_sha256")
_SHA = re.compile(r"^[0-9a-f]{64}$")


class BundleError(RuntimeError):
    pass


@dataclass(frozen=True)
class Bundle:
    name: str
    model: pca.PCAModel
    limits: dict
    model_sha256: str


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
    return Bundle(name=folder.name, model=pca.load(model_path),
                  limits=json.loads(limits_path.read_text()), model_sha256=sha256(model_path))


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
    return True