"""ingest/tags.py and the fit driver eval/fit_pca.py, on synthetic runs (never data/)."""

import numpy as np
import pytest

import dataset.loader as loader_mod
from dataset.convert import VARIABLES
from dataset.loader import Runs
from eval import fit_pca
from ingest import tags as tagmap

FAST = tagmap.fast_tags()


def test_fast_tags_are_the_33_non_analyzers_in_register_order():
    reg = tagmap.register()
    assert len(FAST) == 33
    assert FAST == [r["tag"] for r in reg if r["kind"] in ("measurement", "valve")]


def test_column_indices_follow_the_tag_map():
    m = tagmap.tag_map()
    idx = tagmap.column_indices(VARIABLES, ["RX-TI-204", "FD-FV-105"])
    assert [VARIABLES[i] for i in idx] == [m_raw for m_raw, t in m.items() if t == "RX-TI-204"] + \
        [m_raw for m_raw, t in m.items() if t == "FD-FV-105"]


def test_column_indices_refuse_unknown_tag():
    with pytest.raises(KeyError):
        tagmap.column_indices(VARIABLES, ["RX-TI-999"])


def encoded_runs(numbers=(3, 1, 2), samples=6):
    # value = run * 10000 + sample * 100 + raw column index
    runs = {}
    for k in numbers:
        s = np.arange(1, samples + 1)[:, None]
        c = np.arange(len(VARIABLES))[None, :]
        runs[k] = (k * 10000 + s * 100 + c).astype(np.float32)
    return Runs(name="fault_free_training", fault=0, pool="fit", columns=VARIABLES, runs=runs)


def test_fit_matrix_drops_warmup_and_orders_rows_and_columns():
    X = fit_pca.fit_matrix(encoded_runs(), warmup=2, tag_names=FAST)
    assert X.shape == (3 * 4, 33) and X.dtype == np.float64
    cols = tagmap.column_indices(VARIABLES, FAST)
    # Rows: runs 1, 2, 3 in order, samples 3..6 each (warm-up 2 dropped).
    expected_rows = [(k, s) for k in (1, 2, 3) for s in range(3, 7)]
    for row, (k, s) in zip(X, expected_rows):
        assert np.array_equal(row, k * 10000 + s * 100 + np.array(cols, dtype=float))


@pytest.mark.parametrize("warmup", [-1, 10])
def test_fit_matrix_refuses_warmup_outside_protocol(warmup):
    with pytest.raises(ValueError):
        fit_pca.fit_matrix(encoded_runs(), warmup=warmup, tag_names=FAST)


def test_run_refuses_existing_output(tmp_path, monkeypatch):
    out = tmp_path / "pca.npz"
    out.write_bytes(b"old")
    monkeypatch.setattr(loader_mod, "load_normal", lambda pool: pytest.fail("loaded data"))
    with pytest.raises(FileExistsError):
        fit_pca.run(3, out)
    assert out.read_bytes() == b"old"


def test_run_refuses_bad_warmup_before_loading(tmp_path, monkeypatch):
    monkeypatch.setattr(loader_mod, "load_normal", lambda pool: pytest.fail("loaded data"))
    assert fit_pca.main(["--warmup", "10", "--out", str(tmp_path / "pca.npz")]) == 1


def two_factor_runs(numbers=range(1, 11), samples=200, seed=0):
    # Every fast tag follows one of two factors plus small noise, so parallel analysis
    # should keep exactly 2 components.
    rng = np.random.default_rng(seed)
    cols = tagmap.column_indices(VARIABLES, FAST)
    runs = {}
    for k in numbers:
        f = rng.normal(size=(samples, 2))
        data = rng.normal(size=(samples, len(VARIABLES)))
        for j, c in enumerate(cols):
            data[:, c] = f[:, j % 2] + 0.3 * rng.normal(size=samples)
        runs[k] = data.astype(np.float32)
    return Runs(name="fault_free_training", fault=0, pool="fit", columns=VARIABLES, runs=runs)


def test_run_fits_and_saves(tmp_path, monkeypatch, capsys):
    # Needs Raj's app/detector/pca.py; fails with NotImplementedError until then.
    fake = two_factor_runs()
    monkeypatch.setattr(loader_mod, "load_normal", lambda pool: fake if pool == "fit" else pytest.fail(pool))
    out = tmp_path / "models" / "pca.npz"
    model = fit_pca.run(3, out)
    assert out.is_file()
    assert model.k == 2 and model.tags == tuple(FAST)
    printed = capsys.readouterr().out
    assert "k = 2" in printed and "X 1970 x 33" in printed  # 10 runs x (200 - 3)