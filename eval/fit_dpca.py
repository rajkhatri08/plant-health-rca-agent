"""Choose the DPCA lag count and fit DPCA on the fit pool (decision 63; PROTOCOL, Detection).

    python -m eval.fit_dpca --warmup W [--out data/models/pca_dynamic.npz] [--allow-dirty]

Loads the fit pool through dataset.loader and keeps the 33 fast tags (plant names). Runs
the lag rule (app/detector/dpca.choose_lags): at each l, parallel analysis on the l-lagged
matrix with a fresh generator seeded like the static fit, on the same rows (samples
W+1..T of every run). Then fits PCA on the L-lagged matrix, keeping k(L) from the rule
(no second parallel analysis), and saves the arrays (.npz, no pickles). Writes a fit_dpca
run record with L, whether it was capped, k, r and r_new at every l evaluated, and the
eigenvalues around the cut at k (the full list is in the saved model).
Refuses a dirty tree unless --allow-dirty. Prints only shapes, the evidence, L, k, the
cumulative explained variance and the record's path.
"""

import argparse
import sys
from pathlib import Path

import numpy as np

from app.detector import dpca, pca
from dataset import loader
from eval import fit_pca, run_record
from ingest import tags as tagmap

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "data" / "models" / "pca_dynamic.npz"
DETECTOR = "pca_dynamic"
NEAR_K = 5                                  # eigenvalues recorded on each side of the cut at k


def run_matrices(runs, warmup, tag_names):
    """Every run's samples (warm-up included, since lags may read it), in run-number
    order, with columns in tag_names order. Returns a list of float64 arrays."""
    if not 0 <= warmup <= fit_pca.MAX_WARMUP:
        raise ValueError(f"warm-up must be 0..{fit_pca.MAX_WARMUP} samples, got {warmup}")
    cols = tagmap.column_indices(runs.columns, tag_names)
    return [runs.runs[k][:, cols].astype(np.float64) for k in sorted(runs.runs)]


def run(warmup, out=DEFAULT_OUT, *, allow_dirty=False, repo_root=None, l_max=dpca.L_MAX):
    out = Path(out)
    if out.exists():
        raise FileExistsError(f"{out} already exists; delete it to refit")
    if not 0 <= warmup <= fit_pca.MAX_WARMUP:
        raise ValueError(f"warm-up must be 0..{fit_pca.MAX_WARMUP} samples, got {warmup}")
    if l_max > warmup:
        raise ValueError(f"L_max ({l_max}) can't be more than the warm-up ({warmup}) (decision 52)")
    commit, dirty = run_record.check_clean(repo_root, allow_dirty)    # before any loading
    tag_names = tuple(tagmap.fast_tags())
    fit_runs = loader.load_normal("fit")
    runs = run_matrices(fit_runs, warmup, tag_names)

    def count(l):                               # a fresh generator per l (decision 63)
        return dpca.relation_count(runs, tag_names, l, warmup,
                                   np.random.default_rng(fit_pca.PA_SEED),
                                   fit_pca.PA_SHUFFLES, fit_pca.PA_PERCENTILE)

    choice = dpca.choose_lags(count, l_max)
    L, k = choice.lags, choice.k[choice.lags]
    if k < 1:
        raise ValueError(f"parallel analysis kept no components at L = {L}")
    X = dpca.stack_lagged(runs, L, warmup)
    model = pca.fit(X, dpca.lagged_tags(tag_names, L), k)
    lo = max(k - NEAR_K, 0)
    metrics = {"runs": len(runs), "samples": X.shape[0], "lags": L, "capped": choice.capped,
               "static_equivalent": L == 0,
               "lag_rule": {"k": list(choice.k), "r": list(choice.r), "r_new": list(choice.r_new)},
               "k": k, "cumulative_explained": pca.cumulative_explained(model),
               # m(L+1) eigenvalues can pass the record's 64-number limit; the full list is in
               # the saved model (pinned by its SHA-256). These show how close the cut at k is.
               "eigenvalues_near_k": {"first_rank": lo + 1,
                                      "values": model.all_eigenvalues[lo:k + NEAR_K]}}
    run_record.clean_metrics(metrics)           # refuse before saving, so no model is orphaned
    out.parent.mkdir(parents=True, exist_ok=True)
    pca.save(model, out)
    print(f"fit pool: {len(runs)} runs, warm-up {warmup}; lag rule with L_max {l_max}")
    for l, (k_l, r_l, new_l) in enumerate(zip(choice.k, choice.r, choice.r_new)):
        print(f"  l = {l}: k {k_l}, r {r_l}, r_new {new_l}")
    print(f"L = {L}{' (capped at L_max)' if choice.capped else ''}"
          f"{'; DPCA equals static PCA' if L == 0 else ''}")
    print(f"X {X.shape[0]} x {X.shape[1]}, k = {k}; cumulative explained variance at k: "
          f"{pca.cumulative_explained(model):.3f} (sanity figure)")
    print(f"saved {out}")
    record = run_record.write(
        "fit_dpca",
        config={"detector": DETECTOR, "pool": "fit", "warmup": warmup, "lags": L,
                "tags": list(tag_names), "l_max": l_max, "pa_shuffles": fit_pca.PA_SHUFFLES,
                "pa_percentile": fit_pca.PA_PERCENTILE},
        seeds={"parallel_analysis": fit_pca.PA_SEED},
        metrics=metrics,
        outputs={"model": out}, commit=commit, dirty=dirty, repo_root=repo_root)
    print(f"run record: {record}")
    return model, choice


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--warmup", type=int, required=True, help="samples not scored per run")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--allow-dirty", action="store_true",
                        help="run on a dirty tree; the record says dirty: true")
    args = parser.parse_args(argv)
    try:
        run(args.warmup, args.out, allow_dirty=args.allow_dirty)
    except (ValueError, FileExistsError, loader.LoaderError, run_record.RunRecordError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())