"""The DPCA fit driver eval/fit_dpca.py (decision 63), on synthetic runs (never data/)."""

import hashlib
import json

import numpy as np
import pytest

import dataset.loader as loader_mod
from app.detector import dpca
from dataset.convert import VARIABLES
from dataset.loader import Runs
from eval import fit_dpca, fit_pca, run_record
from ingest import tags as tagmap
from tests.test_fit_pca import FAST, two_factor_runs

WARMUP = 9


def lag_one_runs(numbers=range(1, 11), samples=200, seed=0):
    """One white-noise factor f. The first 17 fast tags follow f_t and the other 16 follow
    f_{t-1}, each with small noise. At l lags the matrix holds f_t .. f_{t-l-1}, so
    k(l) = l + 2 and r(l) = 33(l+1) - (l + 2) = 31, 63, 95 for l = 0, 1, 2.
    r_new = 31, 63 - 2*31 = 1, 95 - (3*31 + 2*1) = 0: stop at l* = 2, so L = 1."""
    rng = np.random.default_rng(seed)
    cols = tagmap.column_indices(VARIABLES, FAST)
    runs = {}
    for k in numbers:
        f = rng.normal(size=samples + 1)                  # f[1:] is f_t, f[:-1] is f_{t-1}
        data = rng.normal(size=(samples, len(VARIABLES)))
        for j, c in enumerate(cols):
            data[:, c] = (f[1:] if j < 17 else f[:-1]) + 0.3 * rng.normal(size=samples)
        runs[k] = data.astype(np.float32)
    return Runs(name="fault_free_training", fault=0, pool="fit", columns=VARIABLES, runs=runs)


def use(monkeypatch, fake):
    monkeypatch.setattr(loader_mod, "load_normal",
                        lambda pool: fake if pool == "fit" else pytest.fail(f"loaded {pool}"))


def the_record(repo):
    (path,) = (repo / "eval" / "runs").glob("*_fit_dpca.json")
    return json.loads(path.read_text())


def test_run_matrices_keep_warm_up_and_order():
    from tests.test_fit_pca import encoded_runs
    mats = fit_dpca.run_matrices(encoded_runs(), 2, FAST)
    cols = np.array(tagmap.column_indices(VARIABLES, FAST), dtype=float)
    assert len(mats) == 3 and all(m.shape == (6, 33) and m.dtype == np.float64 for m in mats)
    for m, k in zip(mats, (1, 2, 3)):                     # run-number order, sample 1 first
        assert np.array_equal(m[0], k * 10000 + 100 + cols)


def test_lag_one_plant_gives_one_lag(tmp_path, monkeypatch, capsys, git_repo):
    use(monkeypatch, lag_one_runs())
    out = tmp_path / "models" / "dpca.npz"
    model, choice = fit_dpca.run(WARMUP, out, repo_root=git_repo)
    assert choice.lags == 1 and not choice.capped
    assert (choice.k, choice.r, choice.r_new) == ((2, 3, 4), (31, 63, 95), (31, 1, 0))
    assert model.tags == dpca.lagged_tags(FAST, 1) and model.k == 3
    printed = capsys.readouterr().out
    assert "L = 1" in printed and "X 1910 x 66" in printed      # 10 runs x (200 - 9)


def test_record_holds_the_evidence(tmp_path, monkeypatch, git_repo):
    use(monkeypatch, lag_one_runs())
    out = tmp_path / "models" / "dpca.npz"
    model, choice = fit_dpca.run(WARMUP, out, repo_root=git_repo)
    rec = the_record(git_repo)
    assert rec["dirty"] is False
    assert rec["config"]["detector"] == "pca_dynamic" and rec["config"]["lags"] == 1
    assert rec["config"]["tags"] == FAST and rec["config"]["warmup"] == WARMUP
    assert rec["config"]["l_max"] == dpca.L_MAX
    assert rec["seeds"] == {"parallel_analysis": fit_pca.PA_SEED}
    m = rec["metrics"]
    assert m["lag_rule"] == {"k": [2, 3, 4], "r": [31, 63, 95], "r_new": [31, 1, 0]}
    assert m["lags"] == 1 and m["capped"] is False and m["static_equivalent"] is False
    assert m["k"] == 3 and m["runs"] == 10 and m["samples"] == 1910
    # Ranks 1..8 (k = 3: up to 5 on each side of the cut); the full list is in the model.
    assert m["eigenvalues_near_k"]["first_rank"] == 1
    assert m["eigenvalues_near_k"]["values"] == pytest.approx(model.all_eigenvalues[:8].tolist())
    assert rec["outputs"]["model"]["sha256"] == hashlib.sha256(out.read_bytes()).hexdigest()


def test_evidence_is_the_lag_rule_on_the_same_data(tmp_path, monkeypatch, git_repo):
    # Each l gets a fresh generator with the static fit's seed (decision 63).
    fake = lag_one_runs(seed=3)
    use(monkeypatch, fake)
    _, choice = fit_dpca.run(WARMUP, tmp_path / "dpca.npz", repo_root=git_repo)
    mats = fit_dpca.run_matrices(fake, WARMUP, FAST)
    direct = dpca.choose_lags(lambda l: dpca.relation_count(
        mats, tuple(FAST), l, WARMUP, np.random.default_rng(fit_pca.PA_SEED),
        fit_pca.PA_SHUFFLES, fit_pca.PA_PERCENTILE))
    assert choice == direct


def test_static_plant_gives_the_static_model(tmp_path, monkeypatch, capsys, git_repo):
    # Two factors at time t only: r_new(1) = (66 - 4) - 2 * (33 - 2) = 0, so L = 0 and the
    # DPCA model is the static fit on the same rows, array for array.
    use(monkeypatch, two_factor_runs())
    model, choice = fit_dpca.run(WARMUP, tmp_path / "dpca.npz", repo_root=git_repo)
    assert choice.lags == 0 and choice.k == (2, 4)
    assert "DPCA equals static PCA" in capsys.readouterr().out
    assert the_record(git_repo)["metrics"]["static_equivalent"] is True
    static = fit_pca.run(WARMUP, tmp_path / "pca.npz", repo_root=git_repo)
    assert model.tags == static.tags
    for name in ("mean", "scale", "loadings", "eigenvalues", "all_eigenvalues"):
        assert np.array_equal(getattr(model, name), getattr(static, name))


def test_refuses_existing_output_before_loading(tmp_path, monkeypatch):
    out = tmp_path / "dpca.npz"
    out.write_bytes(b"old")
    monkeypatch.setattr(loader_mod, "load_normal", lambda pool: pytest.fail("loaded data"))
    with pytest.raises(FileExistsError):
        fit_dpca.run(WARMUP, out)
    assert out.read_bytes() == b"old"


@pytest.mark.parametrize("warmup", [-1, 10, 3])      # 3: L_max = 4 wouldn't fit (decision 52)
def test_refuses_bad_warmup_before_loading(tmp_path, monkeypatch, warmup):
    monkeypatch.setattr(loader_mod, "load_normal", lambda pool: pytest.fail("loaded data"))
    with pytest.raises(ValueError):
        fit_dpca.run(warmup, tmp_path / "dpca.npz")


def test_refuses_dirty_tree_before_loading(tmp_path, monkeypatch, git_repo):
    (git_repo / "code.py").write_text("x = 2\n")
    monkeypatch.setattr(loader_mod, "load_normal", lambda pool: pytest.fail("loaded data"))
    with pytest.raises(run_record.RunRecordError):
        fit_dpca.run(WARMUP, tmp_path / "dpca.npz", repo_root=git_repo)


def test_main_reports_errors(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(loader_mod, "load_normal", lambda pool: pytest.fail("loaded data"))
    assert fit_dpca.main(["--warmup", "10", "--out", str(tmp_path / "dpca.npz")]) == 1
    assert "warm-up" in capsys.readouterr().err