"""app/detector/bundle.py: load and self-test (decision 21; week 1 finding 3)."""

import numpy as np
import pytest

from app.detector import bundle as bm
from app.detector import pca
from tests.replay_helpers import edit_limits, make_bundle
from tests.test_fit_pca import FAST


@pytest.fixture
def folder(tmp_path):
    return make_bundle(tmp_path / "pca_v1")


def test_good_bundle_passes(folder):
    b = bm.load(folder)
    assert b.name == "pca_v1" and b.model.tags == tuple(FAST)
    assert bm.self_test(b) is True


def test_fast_tags_come_from_the_register():
    assert bm.fast_tags() == tuple(FAST)


@pytest.mark.parametrize("name", ["model.npz", "limits.json"])
def test_missing_file(folder, name):
    (folder / name).unlink()
    with pytest.raises(bm.BundleError):
        bm.load(folder)


@pytest.mark.parametrize("changes", [
    {"model_sha256": "c" * 64},                   # limits for a different model
    {"fit_record_sha256": "not-a-sha"},
    {"calibration_record_sha256": None},
    {"n": 0}, {"n": 5},                           # 5 - 1 > warm-up 3 (decision 52)
    {"gap": -1}, {"warmup": 2.5}, {"lags": True},
    {"t2_lim": 0.0}, {"spe_lim": float("inf")}, {"t2_lim": "6"},
])
def test_bad_limits_are_refused(folder, changes):
    edit_limits(folder, **changes)
    with pytest.raises(bm.BundleError):
        bm.self_test(bm.load(folder))


def test_missing_limit_key(folder):
    import json
    path = folder / "limits.json"
    limits = json.loads(path.read_text())
    del limits["q"]
    path.write_text(json.dumps(limits))
    with pytest.raises(bm.BundleError):
        bm.self_test(bm.load(folder))


def resave(folder, **changes):
    """Rewrite model.npz with changed arrays and point limits.json at it, so only the
    array checks can catch the change."""
    m = pca.load(folder / "model.npz")
    fields = {f: getattr(m, f) for f in ("tags", "mean", "scale", "loadings", "eigenvalues",
                                         "all_eigenvalues")}
    fields.update(changes)
    pca.save(pca.PCAModel(**fields), folder / "model.npz")
    edit_limits(folder, model_sha256=bm.sha256(folder / "model.npz"))


def test_model_file_changed_without_limits(folder):
    m = pca.load(folder / "model.npz")
    pca.save(pca.PCAModel(m.tags, m.mean + 1, m.scale, m.loadings, m.eigenvalues,
                          m.all_eigenvalues), folder / "model.npz")
    with pytest.raises(bm.BundleError):
        bm.self_test(bm.load(folder))


def bad_arrays(m):
    return {
        "tags reordered": {"tags": tuple(reversed(m.tags))},
        "mean short": {"mean": m.mean[:-1]},
        "scale zero": {"scale": np.where(np.arange(len(m.scale)) == 0, 0.0, m.scale)},
        "nan": {"mean": np.where(np.arange(len(m.mean)) == 0, np.nan, m.mean)},
        "eigen mismatch": {"eigenvalues": m.eigenvalues * 1.01},
        "not descending": {"all_eigenvalues": m.all_eigenvalues[::-1],
                           "eigenvalues": m.all_eigenvalues[::-1][:m.k]},
        "not orthonormal": {"loadings": m.loadings * 2},
        "loadings shape": {"loadings": m.loadings[:, :1]},
    }


@pytest.mark.parametrize("case", ["tags reordered", "mean short", "scale zero", "nan",
                                  "eigen mismatch", "not descending", "not orthonormal",
                                  "loadings shape"])
def test_bad_model_arrays_are_refused(folder, case):
    resave(folder, **bad_arrays(pca.load(folder / "model.npz"))[case])
    with pytest.raises(bm.BundleError):
        bm.self_test(bm.load(folder))


def test_register_mismatch_is_refused(folder, tmp_path):
    reg = tmp_path / "tags.yaml"
    reg.write_text("tags:\n- {tag: XX-TI-001, kind: measurement}\n")
    with pytest.raises(bm.BundleError):
        bm.self_test(bm.load(folder), reg)