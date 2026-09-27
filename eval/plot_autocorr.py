"""Autocorrelation of the fitted model's T² and SPE on the fit pool (PLAN week 2, Learn).

    python -m eval.plot_autocorr --warmup 9 [--model data/models/pca_static.npz]
                                 [--out data/plots/autocorr_fit.png] [--max-lag 40]

Exploration only: saves a PNG (data/ is gitignored) and prints only its path. Nothing
from the plot is a reported number (those come from run records).

Each run is scored on its own after the warm-up, and lag pairs never cross a run
boundary. The mean and variance are pooled over all runs, not taken per run.
"""

import argparse
import sys
from pathlib import Path

import numpy as np

from app.detector import pca
from dataset import loader
from eval.fit_pca import DEFAULT_OUT as DEFAULT_MODEL, MAX_WARMUP
from ingest import tags as tagmap

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLOT = REPO_ROOT / "data" / "plots" / "autocorr_fit.png"


def pooled_acf(series, max_lag):
    """Autocorrelation at lags 0..max_lag of several runs of one statistic.

    r(h) = mean over lag-h pairs inside the same run of (x_t - m)(x_t+h - m), divided by
    the mean of (x - m)², with m the pooled mean. Raises ValueError if some lag has no
    pairs (every run shorter than it) or the pooled variance is zero."""
    series = [np.asarray(s, dtype=np.float64) for s in series]
    pooled = np.concatenate(series)
    m = pooled.mean()
    var = np.mean((pooled - m) ** 2)
    if not var > 0:
        raise ValueError("the pooled variance is zero")
    r = np.empty(max_lag + 1)
    for h in range(max_lag + 1):
        total, pairs = 0.0, 0
        for s in series:
            if len(s) > h:
                d = s - m
                total += np.dot(d[:len(s) - h], d[h:])
                pairs += len(s) - h
        if pairs == 0:
            raise ValueError(f"no run is longer than lag {h}")
        r[h] = total / pairs / var
    return r


def run(warmup, model_path=DEFAULT_MODEL, out=DEFAULT_PLOT, max_lag=40):
    import matplotlib
    matplotlib.use("Agg")                       # files only, no window
    import matplotlib.pyplot as plt

    if not 0 <= warmup <= MAX_WARMUP:
        raise ValueError(f"warm-up must be 0..{MAX_WARMUP} samples, got {warmup}")
    model = pca.load(model_path)
    fit_runs = loader.load_normal("fit")
    cols = tagmap.column_indices(fit_runs.columns, model.tags)
    t2_runs, spe_runs = [], []
    for k in sorted(fit_runs.runs):
        t2, spe = pca.scores(model, fit_runs.runs[k][warmup:, cols])
        t2_runs.append(t2)
        spe_runs.append(spe)
    lags = np.arange(max_lag + 1)
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.axhline(0, color="0.6", lw=0.8)
    for name, runs in (("T²", t2_runs), ("SPE", spe_runs)):
        ax.plot(lags, pooled_acf(runs, max_lag), marker="o", ms=3, label=name)
    ax.set_xlabel("lag (samples of 3 min)")
    ax.set_ylabel("autocorrelation")
    ax.set_title(f"Fit pool, {len(fit_runs.runs)} runs, warm-up {warmup}, k = {model.k}")
    ax.legend()
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)
    print(f"saved {out}")
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--warmup", type=int, required=True)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--out", type=Path, default=DEFAULT_PLOT)
    parser.add_argument("--max-lag", type=int, default=40)
    args = parser.parse_args(argv)
    try:
        run(args.warmup, args.model, args.out, args.max_lag)
    except (ValueError, FileNotFoundError, loader.LoaderError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
