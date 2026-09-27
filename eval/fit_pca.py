"""Fit the static PCA detector on the fit pool (decision 49; PROTOCOL, Detection).

    python -m eval.fit_pca --warmup W [--out data/models/pca_static.npz]

Loads the fit pool through dataset.loader, keeps the 33 fast tags (plant names), drops
each run's first W samples, picks k by parallel analysis, fits, and saves the arrays
(.npz, no pickles). Prints only shapes, k and the cumulative explained variance.
"""

import argparse
import sys
from pathlib import Path

import numpy as np

from app.detector import pca
from dataset import loader
from ingest import tags as tagmap

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "data" / "models" / "pca_static.npz"
PA_SEED = 20260927
PA_SHUFFLES = 20
PA_PERCENTILE = 95
MAX_WARMUP = 9                # PROTOCOL: warm-up is under 10 samples


def fit_matrix(runs, warmup, tag_names):
    """Stack every run's samples after warm-up, in run-number order, with columns in
    tag_names order. Returns a float64 array (samples x tags)."""
    if not 0 <= warmup <= MAX_WARMUP:
        raise ValueError(f"warm-up must be 0..{MAX_WARMUP} samples, got {warmup}")
    cols = tagmap.column_indices(runs.columns, tag_names)
    blocks = [runs.runs[k][warmup:, cols] for k in sorted(runs.runs)]
    return np.vstack(blocks).astype(np.float64)


def run(warmup, out=DEFAULT_OUT):
    out = Path(out)
    if out.exists():
        raise FileExistsError(f"{out} already exists; delete it to refit")
    if not 0 <= warmup <= MAX_WARMUP:
        raise ValueError(f"warm-up must be 0..{MAX_WARMUP} samples, got {warmup}")
    tag_names = tuple(tagmap.fast_tags())
    fit_runs = loader.load_normal("fit")
    X = fit_matrix(fit_runs, warmup, tag_names)
    k = pca.parallel_analysis(X, tag_names, np.random.default_rng(PA_SEED),
                              n_shuffles=PA_SHUFFLES, percentile=PA_PERCENTILE)
    if k < 1:
        raise ValueError("parallel analysis kept no components")
    model = pca.fit(X, tag_names, k)
    out.parent.mkdir(parents=True, exist_ok=True)
    pca.save(model, out)
    print(f"fit pool: {len(fit_runs.runs)} runs, warm-up {warmup}, X {X.shape[0]} x {X.shape[1]}")
    print(f"parallel analysis ({PA_SHUFFLES} shuffles, {PA_PERCENTILE}th percentile, "
          f"seed {PA_SEED}): k = {k}")
    print(f"cumulative explained variance at k: {pca.cumulative_explained(model):.3f} (sanity figure)")
    print(f"saved {out}")
    return model


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--warmup", type=int, required=True, help="samples skipped per run")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    try:
        run(args.warmup, args.out)
    except (ValueError, FileExistsError, loader.LoaderError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())