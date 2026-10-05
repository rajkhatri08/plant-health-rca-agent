"""The published-number check (decision 56; PROTOCOL, Detection), on dev only (week 7 S2).

    python -m eval.published_check [--warmup 9] [--k 9 12 17] [--allow-dirty]

Reproduces Yin et al. (2012)'s per-sample PCA detection rates (eval/published/yin2012.yaml)
with our code on our dev runs. It checks the method, not identical data. For each k:
- PCA on the fit pool's 33 fast tags after the warm-up: the same matrix as the production
  fit (fit_pca.fit_matrix), kept at k components (pca.fit)
- theoretical limits at the assumed 99% (the paper doesn't state its level): T² from the F
  distribution (the paper's eq. 3), SPE by Jackson-Mudholkar (eq. 2), with n the fit
  samples and the discarded eigenvalues
- a sample is flagged when either statistic exceeds its limit; no persistence, no grouping
- FDR per fault: the share of flagged samples after onset (from sample 21 of each dev run,
  pooled over the 50 dev runs); FAR: the share of flagged samples on the normal dev runs
  after the warm-up

The comparison (Raj, S2): k = 9 against Table 4 (the headline) and k = 17 against Table 7,
each agreeing when every one of the 12 detectable faults (not 3, 9 or 15) is within 10
points; every miss is listed for Raj to explain in decision 56. Our k = 12 is reported
alongside Table 4 with no verdict, and FAR beside Tables 5 and 8 with no criterion.

Known differences, recorded in the run record: our dev runs are training runs (fault after
sample 20, 480 post-onset samples, against the paper's 800 after sample 160); our fit pool
is 250 runs against the paper's one normal run; the significance level is assumed; the
FAR skips the warm-up (PROTOCOL).

The limits and the rates are Raj's (t2_limit_f, spe_limit_jm, flagged, per_sample_rate);
the driver is Claude's. Open data only: it never loads the test split. Writes a
published_check record (aggregates only) and a Markdown table under data/tables/.
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import yaml

from app.detector import pca
from dataset import loader
from eval import calibrate_driver as drv
from eval import fit_pca, metrics, run_record
from ingest import tags as tagmap

ALPHA = 0.99                                  # assumed: the paper doesn't state it (Raj, S2)
KS = (9, 12, 17)
COMPARED = {9: "k9", 17: "k17"}               # k -> the paper's table key (Tables 4 and 7)
HEADLINE_K = 9
TOLERANCE = 10.0                              # points, per fault (Raj, S2)
FAULTS = tuple(range(1, 16))
DETECTABLE = tuple(f for f in FAULTS if f not in (3, 9, 15))
ONSET = metrics.TRAIN_ONSET                   # dev runs are training runs
PAPER = run_record.REPO_ROOT / "eval" / "published" / "yin2012.yaml"
DEFAULT_TABLES = run_record.REPO_ROOT / "data" / "tables"
KNOWN_DIFFERENCES = [
    "dev runs are training runs: the fault after sample 20, 480 post-onset samples (paper: after 160, 800)",
    "the fit pool is 250 normal runs (paper: one normal run)",
    "the significance level is assumed at 99% (not stated in the paper)",
    "FAR skips each normal run's warm-up samples (PROTOCOL's skip rule)",
]


class PublishedCheckError(RuntimeError):
    pass


# ---------- Raj's: the theoretical limits and the per-sample rates ----------

def t2_limit_f(k, n, alpha=ALPHA) -> float:
    """The paper's eq. 3: T²lim = k (n² - 1) / (n (n - k)) · F_alpha(k, n - k), where F_alpha
    is the alpha quantile of the F distribution with (k, n - k) degrees of freedom and n is
    the number of fit samples. Raises ValueError unless 1 <= k < n and 0 < alpha < 1."""
    raise NotImplementedError("Raj implements t2_limit_f (week 7 S2)")


def spe_limit_jm(residual_eigenvalues, alpha=ALPHA) -> float:
    """The paper's eq. 2, Jackson-Mudholkar, over the discarded eigenvalues λ_j (j > k):
    θ_i = Σ λ_j^i (i = 1, 2, 3); h0 = 1 - 2 θ1 θ3 / (3 θ2²); c_alpha the standard normal
    alpha quantile;
        SPElim = θ1 · [c_alpha · sqrt(2 θ2 h0²) / θ1 + 1 + θ2 h0 (h0 - 1) / θ1²] ^ (1 / h0).
    Raises ValueError on no residual eigenvalues, a non-positive one, or alpha outside (0, 1)."""
    raise NotImplementedError("Raj implements spe_limit_jm (week 7 S2)")


def flagged(t2, spe, t2_lim, spe_lim) -> np.ndarray:
    """One 0/1 int per sample: 1 when T² > t2_lim or SPE > spe_lim (strictly; either one is
    enough, as in the paper). Raises ValueError if t2 and spe differ in length."""
    raise NotImplementedError("Raj implements flagged (week 7 S2)")


def per_sample_rate(flags_by_run, first) -> float:
    """The share of flagged samples over samples first .. end of every run, pooled
    (first is 1-based: onset + 1 for a detection rate, the first scored sample for a false
    alarm rate). flags_by_run maps a run number to its 0/1 array over the whole run.
    Raises ValueError if there are no runs, first < 1, or first is past a run's end."""
    raise NotImplementedError("Raj implements per_sample_rate (week 7 S2)")


# ---------- the comparison (Claude's) ----------

def load_paper(path=PAPER) -> dict:
    doc = yaml.safe_load(Path(path).read_text())
    for key in ("k9", "k17"):
        got = sorted(int(f) for f in doc["fdr_percent"][key])
        if got != list(FAULTS):
            raise PublishedCheckError(f"{path}: {key} must give faults 1-15, got {got}")
    return doc


def compare(ours_percent, theirs_percent, tolerance=TOLERANCE, detectable=DETECTABLE) -> dict:
    """Per fault: ours, theirs, ours - theirs and whether it's within tolerance; the verdict
    is "agrees" only if every detectable fault is within it. Misses list the detectable
    faults outside it (the others are reported, never judged)."""
    faults = {}
    for f in FAULTS:
        ours, theirs = float(ours_percent[f]), float(theirs_percent[f])
        faults[str(f)] = {"ours": ours, "paper": theirs, "difference": ours - theirs,
                          "within": abs(ours - theirs) <= tolerance, "judged": f in detectable}
    misses = [f for f in detectable if not faults[str(f)]["within"]]
    return {"faults": faults, "misses": misses, "within": len(detectable) - len(misses),
            "of": len(detectable), "verdict": "agrees" if not misses else "doesn't agree"}


# ---------- the run ----------

def run(*, warmup=9, ks=KS, paper_path=PAPER, allow_dirty=False, repo_root=None, tables_dir=None, now=None,
        out=print):
    ks = tuple(sorted(set(ks)))
    if HEADLINE_K not in ks:
        raise PublishedCheckError(f"k = {HEADLINE_K} is the check's headline; it must be among --k")
    repo_root = Path(repo_root or run_record.REPO_ROOT)
    commit, dirty = run_record.check_clean(repo_root, allow_dirty)    # before any loading
    paper = load_paper(paper_path)
    now = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    tables_dir = Path(tables_dir or DEFAULT_TABLES)
    table_path = tables_dir / f"{now.strftime('%Y%m%dT%H%M%SZ')}_published_check.md"
    if table_path.exists():
        raise FileExistsError(f"{table_path} already exists")

    tags = tuple(tagmap.fast_tags())
    fit_runs = loader.load_normal("fit")
    X = fit_pca.fit_matrix(fit_runs, warmup, tags)
    n, n_fit_runs = X.shape[0], len(fit_runs.runs)
    models, limits = {}, {}
    for k in ks:
        models[k] = pca.fit(X, tags, k)
        limits[k] = (t2_limit_f(k, n, ALPHA), spe_limit_jm(models[k].all_eigenvalues[k:], ALPHA))
    del X, fit_runs

    def rates(runs, first):
        out_ = {}
        for k in ks:
            scored = drv.score_runs(models[k], runs)
            out_[k] = per_sample_rate({r: flagged(t2, spe, *limits[k]) for r, (t2, spe) in scored.items()}, first)
        return out_

    normal = loader.load_normal("dev")
    far = rates(normal, warmup + 1)
    fdr = {k: {} for k in ks}
    for f in FAULTS:
        runs = loader.load_faulty(f, "dev")
        if sorted(runs.runs) != sorted(normal.runs):
            raise PublishedCheckError(f"fault {f}'s dev run numbers aren't the normal dev numbers")
        for k, r in rates(runs, ONSET + 1).items():
            fdr[k][f] = r
    del normal

    results = {"k": {}}
    for k in ks:
        ours = {f: 100 * fdr[k][f] for f in FAULTS}
        entry = {"t2_limit": limits[k][0], "spe_limit": limits[k][1], "far_percent": 100 * far[k],
                 "fdr_percent": {str(f): v for f, v in ours.items()},
                 "cumulative_explained": pca.cumulative_explained(models[k])}
        if k in COMPARED:
            key = COMPARED[k]
            entry["comparison"] = {"paper_table": key, **compare(ours, paper["fdr_percent"][key]),
                                   "paper_far_percent": float(paper["far_percent"][key])}
        else:                                                        # ours (k = 12): alongside Table 4
            entry["alongside_k9_table"] = {str(f): ours[f] - float(paper["fdr_percent"]["k9"][f]) for f in FAULTS}
        results["k"][str(k)] = entry
    head = results["k"][str(HEADLINE_K)]["comparison"]
    results["headline"] = {"k": HEADLINE_K, "verdict": head["verdict"], "within": head["within"], "of": head["of"],
                           "misses": head["misses"]}

    config = {"ks": list(ks), "headline_k": HEADLINE_K, "compared": {str(k): v for k, v in COMPARED.items()},
              "alpha": ALPHA, "alpha_assumed": True, "warmup": warmup, "fit_samples": n,
              "fit_runs": n_fit_runs, "onset": ONSET, "fdr_from_sample": ONSET + 1,
              "far_from_sample": warmup + 1, "tolerance_points": TOLERANCE, "detectable": list(DETECTABLE),
              "tags": "fast (33)", "paper": _rel(paper_path, repo_root),
              "paper_sha256": run_record.sha256(paper_path), "known_differences": KNOWN_DIFFERENCES}
    tables_dir.mkdir(parents=True, exist_ok=True)
    table_path.write_text(markdown(results, config))
    record = run_record.write("published_check", config=config, seeds={}, metrics=results,
                              outputs={"table": table_path}, commit=commit, dirty=dirty, repo_root=repo_root,
                              now=now)
    h = results["headline"]
    out(f"k = {HEADLINE_K} vs Table 4: {h['verdict']} ({h['within']} of {h['of']} detectable faults within "
        f"{TOLERANCE:g} points; misses {h['misses'] or 'none'})")
    if 17 in ks:
        c = results["k"]["17"]["comparison"]
        out(f"k = 17 vs Table 7: {c['verdict']} ({c['within']} of {c['of']}; misses {c['misses'] or 'none'})")
    out(f"table: {table_path}\nrun record: {record}")
    return results, record


def _rel(path, repo_root):
    path, root = Path(path).resolve(), Path(repo_root).resolve()
    return path.relative_to(root).as_posix() if path.is_relative_to(root) else path.name


def _p(x):
    return f"{x:.2f}"


def markdown(results, config) -> str:
    ks = config["ks"]
    lines = ["# Published-number check (decision 56)", "",
             f"Our static PCA on the dev runs against the paper's per-sample PCA rates. Theoretical limits at "
             f"{config['alpha']:.0%} (assumed), either statistic, no persistence. FDR from sample "
             f"{config['fdr_from_sample']}; FAR on the normal dev runs from sample {config['far_from_sample']}. "
             f"Agreement: every detectable fault within {config['tolerance_points']:g} points.", "",
             "Known differences: " + "; ".join(config["known_differences"]) + ".", ""]
    header = ["Fault"]
    for k in ks:
        header += [f"k = {k}"] + ([f"paper ({results['k'][str(k)]['comparison']['paper_table']})", "difference"]
                                  if "comparison" in results["k"][str(k)] else ["vs Table 4"])
    lines += ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for f in FAULTS:
        cells = [f"{f}{'' if f in DETECTABLE else ' (not judged)'}"]
        for k in ks:
            e = results["k"][str(k)]
            cells.append(_p(e["fdr_percent"][str(f)]))
            if "comparison" in e:
                c = e["comparison"]["faults"][str(f)]
                mark = "" if c["within"] or not c["judged"] else " (miss)"
                cells += [_p(c["paper"]), f"{c['difference']:+.2f}{mark}"]
            else:
                cells.append(f"{e['alongside_k9_table'][str(f)]:+.2f}")
        lines.append("| " + " | ".join(cells) + " |")
    far = ["FAR (normal dev)"]
    for k in ks:
        e = results["k"][str(k)]
        far.append(_p(e["far_percent"]))
        far += [_p(e["comparison"]["paper_far_percent"]), ""] if "comparison" in e else [""]
    lines.append("| " + " | ".join(far) + " |")
    lines.append("")
    for k in ks:
        e = results["k"][str(k)]
        lines.append(f"- k = {k}: T²lim {e['t2_limit']:.3f}, SPElim {e['spe_limit']:.3f}, cumulative explained "
                     f"{e['cumulative_explained']:.3f}"
                     + (f"; {e['comparison']['verdict']} ({e['comparison']['within']} of {e['comparison']['of']}, "
                        f"misses {e['comparison']['misses'] or 'none'})" if "comparison" in e else ""))
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--warmup", type=int, default=9)
    parser.add_argument("--k", type=int, nargs="+", default=list(KS))
    parser.add_argument("--allow-dirty", action="store_true",
                        help="run on a dirty tree; the record says dirty: true")
    args = parser.parse_args(argv)
    try:
        run(warmup=args.warmup, ks=args.k, allow_dirty=args.allow_dirty)
    except (ValueError, FileExistsError, FileNotFoundError, loader.LoaderError, run_record.RunRecordError,
            drv.CalibrationError, PublishedCheckError, NotImplementedError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
