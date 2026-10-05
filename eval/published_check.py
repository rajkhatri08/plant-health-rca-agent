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

Post-hoc diagnostic (decision 56, Result; dev only, changes no verdict):
    python -m eval.published_check --far-matched eval/runs/<stamp>_published_check.json
scales both theoretical limits by one factor c* (Raj's far_matched_factor) so that our FAR on
the normal dev runs equals the paper's (6.13% at k = 9, 6.38% at k = 17), and reports every
fault's rate at c* beside the paper's and the check's. Writes a published_check_far_matched
record with no verdict field.

The limits and the rates are Raj's (t2_limit_f, spe_limit_jm, flagged, per_sample_rate);
the driver is Claude's. Open data only: it never loads the test split. Writes a
published_check record (aggregates only) and a Markdown table under data/tables/.
"""

import argparse
import json
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
    if not (1 <= k < n) or not (0 < alpha < 1):
        raise ValueError(f"need 1 <= k < n and 0 < alpha < 1 (k={k}, n={n}, alpha={alpha})")
    from scipy import stats
    return float(k * (n ** 2 - 1) / (n * (n - k)) * stats.f.ppf(alpha, k, n - k))


def spe_limit_jm(residual_eigenvalues, alpha=ALPHA) -> float:
    """The paper's eq. 2, Jackson-Mudholkar, over the discarded eigenvalues λ_j (j > k):
    θ_i = Σ λ_j^i (i = 1, 2, 3); h0 = 1 - 2 θ1 θ3 / (3 θ2²); c_alpha the standard normal
    alpha quantile;
        SPElim = θ1 · [c_alpha · sqrt(2 θ2 h0²) / θ1 + 1 + θ2 h0 (h0 - 1) / θ1²] ^ (1 / h0).
    Raises ValueError on no residual eigenvalues, a non-positive one, or alpha outside (0, 1)."""
    lam = np.asarray(residual_eigenvalues, dtype=float)
    if lam.size == 0:
        raise ValueError("no residual eigenvalues")
    if not np.all(np.isfinite(lam)) or np.any(lam <= 0):
        raise ValueError("every residual eigenvalue must be positive and finite")
    if not (0 < alpha < 1):
        raise ValueError(f"alpha must be in (0, 1), not {alpha}")
    from scipy import stats
    th1, th2, th3 = (float(np.sum(lam ** i)) for i in (1, 2, 3))
    h0 = 1 - 2 * th1 * th3 / (3 * th2 ** 2)
    c = stats.norm.ppf(alpha)
    return float(th1 * (c * np.sqrt(2 * th2 * h0 ** 2) / th1 + 1 + th2 * h0 * (h0 - 1) / th1 ** 2) ** (1 / h0))


def flagged(t2, spe, t2_lim, spe_lim) -> np.ndarray:
    """One 0/1 int per sample: 1 when T² > t2_lim or SPE > spe_lim (strictly; either one is
    enough, as in the paper). Raises ValueError if t2 and spe differ in length."""
    t2, spe = np.asarray(t2, dtype=float), np.asarray(spe, dtype=float)
    if t2.shape != spe.shape:
        raise ValueError(f"t2 and spe differ in length ({t2.shape} vs {spe.shape})")
    return ((t2 > t2_lim) | (spe > spe_lim)).astype(int)          # either statistic, strictly


def per_sample_rate(flags_by_run, first) -> float:
    """The share of flagged samples over samples first .. end of every run, pooled
    (first is 1-based: onset + 1 for a detection rate, the first scored sample for a false
    alarm rate). flags_by_run maps a run number to its 0/1 array over the whole run.
    Raises ValueError if there are no runs, first < 1, or first is past a run's end."""
    if not flags_by_run:
        raise ValueError("no runs")
    if first < 1:
        raise ValueError(f"first is 1-based, not {first}")
    hits = total = 0
    for run in sorted(flags_by_run):
        flags = np.asarray(flags_by_run[run])
        if first > len(flags):
            raise ValueError(f"first {first} is past run {run}'s end ({len(flags)} samples)")
        part = flags[first - 1:]
        hits += int(part.sum())
        total += part.size
    return hits / total                                              # pooled over samples


def far_matched_factor(ratios_by_run, target_percent, first) -> float:
    """The post-hoc diagnostic's common factor c* (decision 56, Result; Raj implements this).

    ratios_by_run maps a run number to its per-sample ratio r = max(T²/T²lim, SPE/SPElim) over
    the whole run, at the theoretical limits. At factor c a sample is flagged when r > c (both
    limits scaled by c), so the false alarm rate FAR(c) is the share of samples with r > c,
    falling as c rises. c* is the (100 - target_percent)th percentile (numpy's default linear
    method) of the samples first .. end of every run, pooled (first is 1-based), so FAR(c*)
    is the target to within one sample. Raises ValueError if there are no runs, the target
    isn't in (0, 100), first < 1, or first is past a run's end."""
    raise NotImplementedError("Raj implements far_matched_factor (week 7 S2, post hoc)")


def ratio(t2, spe, t2_lim, spe_lim) -> np.ndarray:
    """Per sample, max(T²/T²lim, SPE/SPElim): the plant ratio of app/detector/alerting.py."""
    from app.detector import alerting
    return alerting.plant_ratio(t2, spe, t2_lim, spe_lim)


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


# ---------- the post-hoc diagnostic: limits scaled to the paper's FAR (decision 56, Result) ----------

FAR_MATCHED_KS = (9, 17)
POST_HOC_NOTE = ("post hoc, dev only: changes no verdict; decision 56's result under the pre-registered rule "
                 "stands")


def load_source(path, repo_root, warmup, paper_path):
    """(repo path, record) of the published_check run the diagnostic reads alongside: clean,
    same warm-up, alpha and paper file."""
    path = Path(path)
    if not path.name.endswith("_published_check.json"):
        raise PublishedCheckError(f"{path} isn't a published_check run record")
    rec = json.loads(path.read_text())
    cfg = rec["config"]
    if rec.get("dirty") is not False:
        raise PublishedCheckError(f"{path} was made on a dirty tree")
    if (cfg["warmup"], cfg["alpha"], cfg["paper_sha256"]) != (warmup, ALPHA, run_record.sha256(paper_path)):
        raise PublishedCheckError(f"{path} used another warm-up, alpha or paper file")
    if not all(str(k) in rec["metrics"]["k"] for k in FAR_MATCHED_KS):
        raise PublishedCheckError(f"{path} doesn't hold k = {FAR_MATCHED_KS}")
    return _rel(path, repo_root), rec


def run_far_matched(source, *, warmup=9, paper_path=PAPER, allow_dirty=False, repo_root=None, tables_dir=None,
                    now=None, out=print):
    """Both theoretical limits scaled by one factor c* so that our FAR on the normal dev runs
    equals the paper's (Tables 5 and 8), then every fault's per-sample rate at c* beside the
    paper's and beside the check's own rate. Post hoc: no verdict."""
    repo_root = Path(repo_root or run_record.REPO_ROOT)
    commit, dirty = run_record.check_clean(repo_root, allow_dirty)    # before any loading
    paper = load_paper(paper_path)
    source_rel, src = load_source(source, repo_root, warmup, paper_path)
    now = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    tables_dir = Path(tables_dir or DEFAULT_TABLES)
    table_path = tables_dir / f"{now.strftime('%Y%m%dT%H%M%SZ')}_published_check_far_matched.md"
    if table_path.exists():
        raise FileExistsError(f"{table_path} already exists")

    tags = tuple(tagmap.fast_tags())
    fit_runs = loader.load_normal("fit")
    X = fit_pca.fit_matrix(fit_runs, warmup, tags)
    n = X.shape[0]
    models, limits = {}, {}
    for k in FAR_MATCHED_KS:
        models[k] = pca.fit(X, tags, k)
        limits[k] = (t2_limit_f(k, n, ALPHA), spe_limit_jm(models[k].all_eigenvalues[k:], ALPHA))
    del X, fit_runs

    normal = loader.load_normal("dev")
    factor, scaled, far = {}, {}, {}
    for k in FAR_MATCHED_KS:
        scored = drv.score_runs(models[k], normal)
        target = float(paper["far_percent"][COMPARED[k]])
        factor[k] = far_matched_factor({r: ratio(t2, spe, *limits[k]) for r, (t2, spe) in scored.items()},
                                       target, warmup + 1)
        scaled[k] = (factor[k] * limits[k][0], factor[k] * limits[k][1])
        far[k] = per_sample_rate({r: flagged(t2, spe, *scaled[k]) for r, (t2, spe) in scored.items()}, warmup + 1)
    fdr = {k: {} for k in FAR_MATCHED_KS}
    for f in FAULTS:
        runs = loader.load_faulty(f, "dev")
        if sorted(runs.runs) != sorted(normal.runs):
            raise PublishedCheckError(f"fault {f}'s dev run numbers aren't the normal dev numbers")
        for k in FAR_MATCHED_KS:
            scored = drv.score_runs(models[k], runs)
            fdr[k][f] = per_sample_rate({r: flagged(t2, spe, *scaled[k]) for r, (t2, spe) in scored.items()},
                                        ONSET + 1)
    del normal

    results = {"k": {}}
    for k in FAR_MATCHED_KS:
        key = COMPARED[k]
        check = src["metrics"]["k"][str(k)]["fdr_percent"]
        faults = {}
        for f in FAULTS:
            ours, theirs = 100 * fdr[k][f], float(paper["fdr_percent"][key][f])
            faults[str(f)] = {"ours": ours, "paper": theirs, "difference": ours - theirs,
                              "check_rate": float(check[str(f)]), "change_from_check": ours - float(check[str(f)]),
                              "judged_in_check": f in DETECTABLE}
        within = sum(abs(faults[str(f)]["difference"]) <= TOLERANCE for f in DETECTABLE)
        results["k"][str(k)] = {"factor": factor[k], "t2_limit": scaled[k][0], "spe_limit": scaled[k][1],
                                "theoretical": {"t2_limit": limits[k][0], "spe_limit": limits[k][1]},
                                "target_far_percent": float(paper["far_percent"][key]),
                                "far_percent": 100 * far[k], "paper_table": key, "faults": faults,
                                "fault_10": faults["10"],
                                "reading_only_within_tolerance": {"within": within, "of": len(DETECTABLE)}}
    config = {"post_hoc": True, "note": POST_HOC_NOTE, "ks": list(FAR_MATCHED_KS), "alpha": ALPHA,
              "warmup": warmup, "fit_samples": n, "fdr_from_sample": ONSET + 1, "far_from_sample": warmup + 1,
              "matching_rule": "c* = the (100 - target)th percentile of the pooled per-sample max(T²/T²lim, "
                               "SPE/SPElim) on the normal dev runs after the warm-up; both limits scaled by c*",
              "source_record": source_rel, "source_sha256": run_record.sha256(source),
              "paper": _rel(paper_path, repo_root), "paper_sha256": run_record.sha256(paper_path)}
    tables_dir.mkdir(parents=True, exist_ok=True)
    table_path.write_text(markdown_far_matched(results, config))
    record = run_record.write("published_check_far_matched", config=config, seeds={}, metrics=results,
                              outputs={"table": table_path}, commit=commit, dirty=dirty, repo_root=repo_root,
                              now=now)
    for k in FAR_MATCHED_KS:
        e = results["k"][str(k)]
        f10 = e["fault_10"]
        out(f"k = {k}: c* = {e['factor']:.4f}, FAR {e['far_percent']:.2f}% (paper {e['target_far_percent']}%); "
            f"fault 10 {f10['ours']:.1f}% vs paper {f10['paper']}% (check {f10['check_rate']:.1f}%)")
    out(f"post hoc, no verdict\ntable: {table_path}\nrun record: {record}")
    return results, record


def markdown_far_matched(results, config) -> str:
    lines = ["# Published-number check: FAR-matched diagnostic (post hoc)", "",
             f"{config['note'][0].upper()}{config['note'][1:]}. Matching rule: {config['matching_rule']}. "
             f"Source check: `{config['source_record']}`.", ""]
    for k in config["ks"]:
        e = results["k"][str(k)]
        lines += [f"## k = {k} (paper {e['paper_table']})", "",
                  f"c* = {e['factor']:.4f}: T²lim {e['theoretical']['t2_limit']:.3f} → {e['t2_limit']:.3f}, "
                  f"SPElim {e['theoretical']['spe_limit']:.3f} → {e['spe_limit']:.3f}. FAR {e['far_percent']:.2f}% "
                  f"(target {e['target_far_percent']}%).", "",
                  "| Fault | Ours at c* | Paper | Difference | Check (99%) | Change from check |",
                  "|---|---|---|---|---|---|"]
        for f in FAULTS:
            r = e["faults"][str(f)]
            lines.append(f"| {f}{'' if r['judged_in_check'] else ' (not judged)'} | {_p(r['ours'])} | "
                         f"{_p(r['paper'])} | {r['difference']:+.2f} | {_p(r['check_rate'])} | "
                         f"{r['change_from_check']:+.2f} |")
        w = e["reading_only_within_tolerance"]
        lines += ["", f"For reading only (no verdict): {w['within']} of {w['of']} detectable faults within "
                      f"{TOLERANCE:g} points at c*.", ""]
    return "\n".join(lines)


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
    parser.add_argument("--far-matched", type=Path, default=None, metavar="PUBLISHED_CHECK_RECORD",
                        help="the post-hoc diagnostic (decision 56): limits scaled to the paper's FAR, "
                             "read beside this published_check record; no verdict")
    args = parser.parse_args(argv)
    try:
        if args.far_matched is not None:
            run_far_matched(args.far_matched, warmup=args.warmup, allow_dirty=args.allow_dirty)
        else:
            run(warmup=args.warmup, ks=args.k, allow_dirty=args.allow_dirty)
    except (ValueError, FileExistsError, FileNotFoundError, loader.LoaderError, run_record.RunRecordError,
            drv.CalibrationError, PublishedCheckError, NotImplementedError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
