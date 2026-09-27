"""eval/plot_autocorr.py: the pooled autocorrelation on hand-built runs, and one smoke
run of the plot on synthetic data (never data/)."""

import numpy as np
import pytest

import dataset.loader as loader_mod
from app.detector import pca
from eval import plot_autocorr
from tests.test_fit_pca import FAST, two_factor_runs


def test_lag_zero_is_one():
    r = plot_autocorr.pooled_acf([[1.0, 3.0, 2.0, 5.0]], 2)
    assert r[0] == pytest.approx(1.0)


def test_alternating_run_is_minus_one_at_lag_one():
    # m = 0, var = 1, every lag-1 product is -1; lag-2 products are +1.
    r = plot_autocorr.pooled_acf([[1.0, -1.0, 1.0, -1.0]], 2)
    assert r == pytest.approx([1.0, -1.0, 1.0])


def test_pairs_never_cross_run_boundaries():
    # Two flat runs at 0 and 2: pooled m = 1, every deviation is ±1 with the same sign
    # inside a run, so r(h) = 1 at every lag. Joining the runs would put a -1 product at
    # the boundary and give r(1) = (6 - 1) / 7 / 1 < 1.
    r = plot_autocorr.pooled_acf([[0.0] * 4, [2.0] * 4], 3)
    assert r == pytest.approx([1.0, 1.0, 1.0, 1.0])


def test_short_runs_add_no_pairs_at_long_lags():
    # Run B (length 2) adds nothing at lag 2; only run A's pair (x1, x3) counts.
    # A = [1, -1, 1], B = [-1, 1]: pooled m = 0.2.
    a, b = [1.0, -1.0, 1.0], [-1.0, 1.0]
    m = np.mean(a + b)
    var = np.mean((np.array(a + b) - m) ** 2)
    expected_lag2 = (a[0] - m) * (a[2] - m) / var
    assert plot_autocorr.pooled_acf([a, b], 2)[2] == pytest.approx(expected_lag2)


def test_ar1_decays_geometrically():
    rng = np.random.default_rng(0)
    x = np.zeros(200_000)
    e = rng.normal(size=x.size)
    for t in range(1, x.size):
        x[t] = 0.8 * x[t - 1] + e[t]
    r = plot_autocorr.pooled_acf([x], 3)
    assert r == pytest.approx([1.0, 0.8, 0.64, 0.512], abs=0.01)


def test_refuses_zero_variance_and_lags_longer_than_every_run():
    with pytest.raises(ValueError):
        plot_autocorr.pooled_acf([[2.0, 2.0, 2.0]], 1)
    with pytest.raises(ValueError):
        plot_autocorr.pooled_acf([[1.0, 2.0], [3.0, 1.0]], 2)


def test_plot_smoke(tmp_path, monkeypatch, capsys):
    runs = two_factor_runs()
    monkeypatch.setattr(loader_mod, "load_normal", lambda pool: runs if pool == "fit" else pytest.fail(pool))
    from eval import fit_pca
    X = fit_pca.fit_matrix(runs, 3, FAST)
    model_path = tmp_path / "pca.npz"
    pca.save(pca.fit(X, FAST, 2), model_path)
    out = tmp_path / "plots" / "acf.png"
    plot_autocorr.run(3, model_path, out, max_lag=5)
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert capsys.readouterr().out.strip() == f"saved {out}"


def test_main_refuses_bad_warmup_before_loading(tmp_path, monkeypatch):
    monkeypatch.setattr(loader_mod, "load_normal", lambda pool: pytest.fail("loaded data"))
    assert plot_autocorr.main(["--warmup", "10", "--model", str(tmp_path / "m.npz")]) == 1
