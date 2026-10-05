"""eval/published_check.py (decision 56; week 7 S2), on synthetic numbers and runs only.

The limit and rate tests call Raj's functions and fail with NotImplementedError until he
implements them. The paper file, the comparison and the driver tests pass now: the driver
tests replace the four functions with simple stand-ins, so they check what the driver
loads, fits, passes and records, not the numbers.
"""

import json

import numpy as np
import pytest
import yaml
from scipy import stats

import dataset.loader as loader_mod
from dataset.convert import VARIABLES
from dataset.loader import Runs
from eval import fit_pca
from eval import published_check as pc
from ingest import tags as tagmap
from tests.test_fit_pca import FAST, two_factor_runs


def eq3(k, n, alpha):
    """The paper's eq. 3, written out here as the reference."""
    return k * (n * n - 1) / (n * (n - k)) * stats.f.ppf(alpha, k, n - k)


def eq2(lams, alpha):
    """The paper's eq. 2 (Jackson-Mudholkar), written out here as the reference."""
    lam = np.asarray(lams, dtype=float)
    t1, t2, t3 = (float(np.sum(lam ** i)) for i in (1, 2, 3))
    h0 = 1 - 2 * t1 * t3 / (3 * t2 ** 2)
    c = stats.norm.ppf(alpha)
    return t1 * (c * np.sqrt(2 * t2 * h0 ** 2) / t1 + 1 + t2 * h0 * (h0 - 1) / t1 ** 2) ** (1 / h0)


# ---------- the paper file ----------

def test_the_paper_file_holds_tables_4_and_7_and_the_assumption():
    doc = pc.load_paper()
    assert doc["settings"]["components"] == {"headline": 9, "alternative": 17}
    assert doc["assumptions"]["significance"] == 0.99 and pc.ALPHA == 0.99
    assert [doc["fdr_percent"]["k9"][f] for f in (1, 5, 10, 15)] == [99.88, 33.63, 60.5, 14.13]
    assert [doc["fdr_percent"]["k17"][f] for f in (1, 5, 10, 15)] == [100, 34.75, 71, 17.25]
    assert doc["far_percent"] == {"k9": 6.13, "k17": 6.38}


def test_a_paper_file_missing_a_fault_is_refused(tmp_path):
    doc = yaml.safe_load(pc.PAPER.read_text())
    del doc["fdr_percent"]["k17"][7]
    bad = tmp_path / "paper.yaml"
    bad.write_text(yaml.safe_dump(doc))
    with pytest.raises(pc.PublishedCheckError, match="k17"):
        pc.load_paper(bad)


# ---------- Raj's limits (fail until implemented) ----------

@pytest.mark.parametrize("k, n", [(9, 122750), (17, 122750), (12, 122750), (2, 50)])
def test_t2_limit_is_eq_3(k, n):
    assert pc.t2_limit_f(k, n, 0.99) == pytest.approx(eq3(k, n, 0.99), rel=1e-9)


def test_t2_limit_tends_to_the_chi_square_quantile_at_large_n():
    # 21.669 at n = 122,750 against chi2(0.99, 9) = 21.666
    assert pc.t2_limit_f(9, 122750, 0.99) == pytest.approx(stats.chi2.ppf(0.99, 9), rel=1e-3)


def test_t2_limit_rises_with_alpha_and_with_k():
    assert pc.t2_limit_f(9, 1000, 0.99) > pc.t2_limit_f(9, 1000, 0.95)
    assert pc.t2_limit_f(17, 1000, 0.99) > pc.t2_limit_f(9, 1000, 0.99)


@pytest.mark.parametrize("k, n, alpha", [(0, 100, 0.99), (100, 100, 0.99), (120, 100, 0.99),
                                         (9, 100, 1.0), (9, 100, 0.0), (9, 100, -0.5)])
def test_t2_limit_refusals(k, n, alpha):
    with pytest.raises(ValueError):
        pc.t2_limit_f(k, n, alpha)


@pytest.mark.parametrize("lams", [[3, 2, 1, 0.5, 0.25], [0.9] * 24, list(np.linspace(1.0, 0.05, 21))])
def test_spe_limit_is_eq_2(lams):
    assert pc.spe_limit_jm(np.array(lams), 0.99) == pytest.approx(eq2(lams, 0.99), rel=1e-9)


def test_spe_limit_by_hand():
    # [3, 2, 1, 0.5, 0.25]: theta = 6.75, 14.3125, 36.1406; h0 = 0.2207; limit 26.796
    assert pc.spe_limit_jm([3, 2, 1, 0.5, 0.25], 0.99) == pytest.approx(26.7963, abs=1e-3)


def test_spe_limit_with_equal_eigenvalues_is_near_the_chi_square_quantile():
    # 24 eigenvalues of 1: SPE is about chi2 with 24 degrees of freedom; JM gives 43.004 vs 42.980
    assert pc.spe_limit_jm(np.ones(24), 0.99) == pytest.approx(stats.chi2.ppf(0.99, 24), rel=5e-3)


def test_spe_limit_scales_with_the_eigenvalues():
    lams = np.array([3, 2, 1, 0.5, 0.25])
    assert pc.spe_limit_jm(4 * lams, 0.99) == pytest.approx(4 * pc.spe_limit_jm(lams, 0.99), rel=1e-9)


@pytest.mark.parametrize("lams, alpha", [([], 0.99), ([1.0, 0.0], 0.99), ([1.0, -0.2], 0.99), ([1.0], 1.0)])
def test_spe_limit_refusals(lams, alpha):
    with pytest.raises(ValueError):
        pc.spe_limit_jm(np.array(lams, dtype=float), alpha)


# ---------- Raj's per-sample rates (fail until implemented) ----------

def test_flagged_is_strict_and_either_statistic():
    t2 = np.array([1.0, 2.0, 2.5, 0.0, 3.0])
    spe = np.array([0.0, 5.0, 1.0, 6.0, 9.0])
    # limits 2.0 and 5.0: sample 2 equals both (not flagged), 3 is T² only, 4 is SPE only, 5 both
    assert pc.flagged(t2, spe, 2.0, 5.0).tolist() == [0, 0, 1, 1, 1]


def test_flagged_refuses_different_lengths():
    with pytest.raises(ValueError):
        pc.flagged(np.zeros(3), np.zeros(4), 1.0, 1.0)


def test_per_sample_rate_pools_samples_from_first_on():
    flags = {1: np.array([1, 1, 0, 1, 0]), 2: np.array([0, 1, 1, 1, 1])}
    # from sample 3: run 1 has 0,1,0 and run 2 has 1,1,1, so 4 of 6
    assert pc.per_sample_rate(flags, 3) == pytest.approx(4 / 6)
    assert pc.per_sample_rate(flags, 1) == pytest.approx(7 / 10)
    assert pc.per_sample_rate({1: np.array([0, 0, 1])}, 3) == 1.0


@pytest.mark.parametrize("flags, first", [({}, 1), ({1: np.zeros(5)}, 0), ({1: np.zeros(5)}, 6)])
def test_per_sample_rate_refusals(flags, first):
    with pytest.raises(ValueError):
        pc.per_sample_rate(flags, first)


# ---------- the comparison (passes now) ----------

def test_compare_judges_only_the_detectable_faults():
    paper = pc.load_paper()["fdr_percent"]["k9"]
    ours = {f: float(paper[f]) for f in pc.FAULTS}
    ours[3] = paper[3] + 40                    # not judged: still agrees
    ours[10] = paper[10] - 10.0                # exactly 10 points: within
    ours[5] = paper[5] + 10.5                  # a miss
    c = pc.compare(ours, paper)
    assert c["misses"] == [5] and c["within"] == 11 and c["of"] == 12 and c["verdict"] == "doesn't agree"
    assert c["faults"]["3"]["judged"] is False and c["faults"]["3"]["within"] is False
    assert c["faults"]["10"]["within"] is True and c["faults"]["5"]["difference"] == pytest.approx(10.5)
    ours[5] = paper[5]
    assert pc.compare(ours, paper)["verdict"] == "agrees"


def test_detectable_faults_exclude_3_9_15():
    assert pc.DETECTABLE == (1, 2, 4, 5, 6, 7, 8, 10, 11, 12, 13, 14)


# ---------- the driver (stand-ins for Raj's four functions; passes now) ----------

SAMPLES = 60


def faulty(normal, fault):
    cols = tagmap.column_indices(VARIABLES, FAST)
    runs = {k: v.copy() for k, v in normal.runs.items()}
    if fault not in (3, 9, 15):
        for k in runs:
            runs[k][20:, cols] += np.float32(0.5 * fault)          # from sample 21
    return Runs("faulty_training", fault, "dev", VARIABLES, runs)


@pytest.fixture
def drive(git_repo, monkeypatch, tmp_path):
    fit_runs = two_factor_runs(numbers=range(1, 11), samples=SAMPLES, seed=1)
    normal = two_factor_runs(numbers=range(101, 106), samples=SAMPLES, seed=2)
    calls, seen = [], {"fit": [], "rate": [], "t2": [], "spe": []}

    def load_normal(pool):
        calls.append(("normal", pool))
        return {"fit": fit_runs, "dev": normal}.get(pool) or pytest.fail(f"loaded normal {pool}")

    def load_faulty(fault, pool):
        calls.append(("faulty", fault, pool))
        if pool != "dev":
            pytest.fail(f"loaded fault {fault} from {pool}")
        return faulty(normal, fault)

    monkeypatch.setattr(loader_mod, "load_normal", load_normal)
    monkeypatch.setattr(loader_mod, "load_faulty", load_faulty)
    monkeypatch.setattr(loader_mod, "load_testing", lambda *a, **kw: pytest.fail("loaded the test split"))
    real_fit = pc.pca.fit

    def spy_fit(X, tags, k):
        seen["fit"].append((X.copy(), k))
        return real_fit(X, tags, k)

    monkeypatch.setattr(pc.pca, "fit", spy_fit)
    monkeypatch.setattr(pc, "t2_limit_f", lambda k, n, alpha: seen["t2"].append((k, n, alpha)) or 5.0 * k)
    monkeypatch.setattr(pc, "spe_limit_jm", lambda lams, alpha: seen["spe"].append((len(lams), alpha)) or 4.0)
    monkeypatch.setattr(pc, "flagged", lambda t2, spe, a, b: ((t2 > a) | (spe > b)).astype(int))

    def rate(flags_by_run, first):
        seen["rate"].append(first)
        return float(np.mean(np.concatenate([f[first - 1:] for f in flags_by_run.values()])))

    monkeypatch.setattr(pc, "per_sample_rate", rate)
    return {"repo": git_repo, "calls": calls, "seen": seen, "fit_runs": fit_runs, "tables": tmp_path / "tables"}


def go(d, **kw):
    return pc.run(repo_root=d["repo"], tables_dir=d["tables"], out=lambda s: None, **kw)


def test_the_driver_fits_the_production_matrix_at_each_k(drive):
    go(drive)
    X = fit_pca.fit_matrix(drive["fit_runs"], 9, tuple(tagmap.fast_tags()))
    assert [k for _, k in drive["seen"]["fit"]] == [9, 12, 17]
    assert all(np.array_equal(Xs, X) for Xs, _ in drive["seen"]["fit"])
    assert drive["seen"]["t2"] == [(k, X.shape[0], 0.99) for k in (9, 12, 17)]
    assert drive["seen"]["spe"] == [(33 - k, 0.99) for k in (9, 12, 17)]          # the discarded eigenvalues


def test_the_driver_loads_open_dev_data_only(drive):
    go(drive)
    assert drive["calls"] == ([("normal", "fit"), ("normal", "dev")]
                              + [("faulty", f, "dev") for f in range(1, 16)])


def test_fdr_starts_after_onset_and_far_after_the_warm_up(drive):
    go(drive)
    rates = drive["seen"]["rate"]
    assert rates[:3] == [10, 10, 10]                                        # FAR, one per k
    assert rates[3:] == [21] * (15 * 3)                                    # FDR per fault and k


def test_the_record_compares_k9_and_k17_and_holds_k12_alongside(drive):
    results, record = go(drive)
    rec = json.loads(record.read_text())
    assert rec["name"] == "published_check" and rec["config"]["alpha_assumed"] is True
    assert rec["config"]["ks"] == [9, 12, 17] and rec["config"]["paper"] == pc.PAPER.name
    assert rec["config"]["fdr_from_sample"] == 21 and rec["config"]["far_from_sample"] == 10
    assert len(rec["config"]["known_differences"]) == 4
    k = rec["metrics"]["k"]
    assert k["9"]["comparison"]["paper_table"] == "k9" and k["17"]["comparison"]["paper_table"] == "k17"
    assert "comparison" not in k["12"] and set(k["12"]["alongside_k9_table"]) == {str(f) for f in range(1, 16)}
    assert k["9"]["comparison"]["paper_far_percent"] == 6.13 and k["17"]["comparison"]["paper_far_percent"] == 6.38
    assert rec["metrics"]["headline"]["k"] == 9 and rec["metrics"]["headline"]["verdict"] in ("agrees", "doesn't agree")
    assert 0 <= k["9"]["far_percent"] <= 100
    table = next(drive["tables"].glob("*_published_check.md")).read_text()
    assert table.startswith("# Published-number check") and "Known differences" in table


def test_the_headline_k_must_be_run_and_a_dirty_tree_is_refused(drive):
    with pytest.raises(pc.PublishedCheckError, match="headline"):
        go(drive, ks=(12, 17))
    (drive["repo"] / "code.py").write_text("x = 2\n")
    with pytest.raises(Exception, match="dirty"):
        go(drive)
    assert drive["calls"] == []


# ---------- the post-hoc FAR-matched diagnostic (decision 56, Result) ----------
# Raj's far_matched_factor (fails with NotImplementedError until implemented):

def test_far_matched_factor_by_hand():
    # samples 2..6 pooled: [1, 2, 3, 4, 5]; a 40% target is the 60th percentile, 3.4,
    # and 2 of the 5 (4 and 5) are above it: FAR 40%
    assert pc.far_matched_factor({1: np.array([9.0, 1, 2, 3, 4, 5])}, 40.0, 2) == pytest.approx(3.4)


def test_far_at_the_factor_is_the_target_to_within_one_sample():
    rng = np.random.default_rng(0)
    ratios = {k: rng.gamma(2.0, 0.3, size=500) for k in range(1, 11)}
    pooled = np.concatenate([r[9:] for r in ratios.values()])
    for target in (6.13, 6.38, 1.86):
        c = pc.far_matched_factor(ratios, target, 10)
        far = 100 * np.mean(pooled > c)
        assert abs(far - target) <= 100 / pooled.size + 1e-12


def test_far_matched_factor_pools_runs_and_skips_samples_before_first():
    ratios = {1: np.array([100.0, 1, 2]), 2: np.array([100.0, 3, 4, 5])}
    assert pc.far_matched_factor(ratios, 40.0, 2) == pytest.approx(np.percentile([1, 2, 3, 4, 5], 60))


def test_a_lower_target_needs_a_higher_factor():
    rng = np.random.default_rng(1)
    ratios = {1: rng.gamma(2.0, 0.3, size=2000)}
    assert pc.far_matched_factor(ratios, 1.0, 1) > pc.far_matched_factor(ratios, 6.13, 1)


@pytest.mark.parametrize("ratios, target, first", [({}, 6.0, 1), ({1: np.ones(5)}, 0.0, 1),
                                                    ({1: np.ones(5)}, 100.0, 1), ({1: np.ones(5)}, 6.0, 0),
                                                    ({1: np.ones(5)}, 6.0, 6)])
def test_far_matched_factor_refusals(ratios, target, first):
    with pytest.raises(ValueError):
        pc.far_matched_factor(ratios, target, first)


def test_ratio_is_the_plant_ratio():
    t2, spe = np.array([1.0, 4.0, 2.0]), np.array([3.0, 1.0, 8.0])
    assert pc.ratio(t2, spe, 2.0, 4.0).tolist() == [0.75, 2.0, 2.0]


# The driver (stand-ins for Raj's functions; passes now):

def write_source(repo, **change):
    rec = {"name": "published_check", "dirty": False,
           "config": {"warmup": 9, "alpha": 0.99, "paper_sha256": pc.run_record.sha256(pc.PAPER)},
           "metrics": {"k": {str(k): {"fdr_percent": {str(f): 50.0 for f in range(1, 16)}} for k in (9, 12, 17)}}}
    for key, value in change.items():
        if key == "config":
            rec["config"].update(value)
        else:
            rec[key] = value
    path = repo / "eval" / "runs" / change.pop("name", "20261005T165013Z_published_check.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec))
    return path


@pytest.fixture
def matched(drive, monkeypatch):
    seen = {"factor": [], "flag_limits": []}

    def factor(ratios_by_run, target, first):
        seen["factor"].append((target, first, len(ratios_by_run)))
        return 0.8

    monkeypatch.setattr(pc, "far_matched_factor", factor)

    def flag(t2, spe, a, b):
        seen["flag_limits"].append((a, b))
        return ((t2 > a) | (spe > b)).astype(int)

    monkeypatch.setattr(pc, "flagged", flag)
    return {**drive, "matched_seen": seen}


def go_matched(d, source, **kw):
    return pc.run_far_matched(source, repo_root=d["repo"], tables_dir=d["tables"], out=lambda s: None, **kw)


def test_the_factor_is_matched_to_the_papers_far_on_normal_dev(matched):
    go_matched(matched, write_source(matched["repo"]))
    assert matched["matched_seen"]["factor"] == [(6.13, 10, 5), (6.38, 10, 5)]     # 5 normal dev runs
    assert [k for _, k in matched["seen"]["fit"]] == [9, 17]                       # k = 12 isn't run


def test_both_limits_are_scaled_by_the_factor(matched):
    go_matched(matched, write_source(matched["repo"]))
    limits = set(matched["matched_seen"]["flag_limits"])
    assert limits == {(0.8 * 5.0 * 9, 0.8 * 4.0), (0.8 * 5.0 * 17, 0.8 * 4.0)}       # c* x (T²lim, SPElim)
    assert matched["seen"]["rate"][:2] == [10, 10] and set(matched["seen"]["rate"][2:]) == {21}


def test_the_record_is_post_hoc_with_no_verdict(matched):
    results, record = go_matched(matched, write_source(matched["repo"]))
    rec = json.loads(record.read_text())
    assert rec["name"] == "published_check_far_matched" and rec["config"]["post_hoc"] is True
    assert "changes no verdict" in rec["config"]["note"]
    assert "verdict" not in json.dumps(rec["metrics"]) and "misses" not in json.dumps(rec["metrics"])
    assert rec["config"]["source_record"] == "eval/runs/20261005T165013Z_published_check.json"
    assert len(rec["config"]["source_sha256"]) == 64
    e = rec["metrics"]["k"]["9"]
    assert e["factor"] == 0.8 and e["target_far_percent"] == 6.13 and e["paper_table"] == "k9"
    assert e["fault_10"]["paper"] == 60.5 and e["fault_10"]["check_rate"] == 50.0
    assert e["faults"]["10"]["change_from_check"] == pytest.approx(e["faults"]["10"]["ours"] - 50.0)
    assert set(e["reading_only_within_tolerance"]) == {"within", "of"}
    assert rec["metrics"]["k"]["17"]["target_far_percent"] == 6.38
    table = next(matched["tables"].glob("*_far_matched.md")).read_text()
    assert table.startswith("# Published-number check: FAR-matched diagnostic (post hoc)") and "no verdict" in table


def test_the_diagnostic_loads_open_dev_data_only(matched):
    go_matched(matched, write_source(matched["repo"]))
    assert matched["calls"] == ([("normal", "fit"), ("normal", "dev")]
                                + [("faulty", f, "dev") for f in range(1, 16)])


@pytest.mark.parametrize("change", [{"dirty": True}, {"config": {"alpha": 0.95}}, {"config": {"warmup": 5}},
                                    {"config": {"paper_sha256": "0" * 64}}, {"name": "x_other.json"}])
def test_a_wrong_source_record_is_refused_before_loading(matched, change):
    with pytest.raises(pc.PublishedCheckError):
        go_matched(matched, write_source(matched["repo"], **change))
    assert matched["calls"] == []


def test_main_routes_the_diagnostic(monkeypatch):
    seen = []
    monkeypatch.setattr(pc, "run_far_matched", lambda source, **kw: seen.append(("matched", str(source))))
    monkeypatch.setattr(pc, "run", lambda **kw: seen.append(("check",)))
    assert pc.main(["--far-matched", "r.json"]) == 0 and pc.main([]) == 0
    assert seen == [("matched", "r.json"), ("check",)]
