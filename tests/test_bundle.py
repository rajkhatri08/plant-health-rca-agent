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

# ---------- watch.json (pca_v2, decisions 64-66) ----------

from tests.replay_helpers import SHA_A, add_watch, edit_watch  # noqa: E402


@pytest.fixture
def v2(tmp_path):
    return add_watch(make_bundle(tmp_path / "pca_v2"))


def test_v2_bundle_passes_and_carries_watch(v2):
    b = bm.load(v2)
    assert b.watch is not None and list(b.watch["groups"])[0] == "feed"
    assert bm.self_test(b) is True


def test_v1_bundle_has_no_watch(folder):
    assert bm.load(folder).watch is None


def _groups_reordered(w):
    return dict(reversed(list(w["groups"].items())))


@pytest.mark.parametrize("edit", [
    lambda w: {"model_sha256": SHA_A},                                   # another model
    lambda w: {"watch_record_sha256": "not-a-sha"},
    lambda w: {"limits_sha256": None},
    lambda w: {"warmup": w["warmup"] + 1},                               # differs from limits
    lambda w: {"detector": "pca_dynamic"},
    lambda w: {"p": 0.0}, lambda w: {"p": 100.5}, lambda w: {"p": True},
    lambda w: {"groups": _groups_reordered(w)},                          # register order
    lambda w: {"groups": {**w["groups"], "feed": {**w["groups"]["feed"], "w": 0.0}}},
    lambda w: {"groups": {**w["groups"], "feed": {**w["groups"]["feed"], "w": float("nan")}}},
    lambda w: {"groups": {**w["groups"], "feed": {**w["groups"]["feed"],
                                                  "tags": w["groups"]["feed"]["tags"][::-1]}}},
    lambda w: {"tags": dict(list(w["tags"].items())[1:])},               # a tag missing
    lambda w: {"tags": {**w["tags"], FAST[0]: -1.0}},
])
def test_bad_watch_is_refused(v2, edit):
    import json
    edit_watch(v2, **edit(json.loads((v2 / "watch.json").read_text())))
    with pytest.raises(bm.BundleError):
        bm.self_test(bm.load(v2))


def test_watch_key_missing_is_refused(v2):
    import json
    path = v2 / "watch.json"
    w = json.loads(path.read_text())
    del w["tags"]
    path.write_text(json.dumps(w))
    with pytest.raises(bm.BundleError, match="lacks"):
        bm.self_test(bm.load(v2))


def test_watch_needs_a_static_model(v2):
    edit_limits(v2, lags=1)                       # 1 + n 2 - 1 <= warm-up 3, so only Watch refuses
    with pytest.raises(bm.BundleError, match="static PCA"):
        bm.self_test(bm.load(v2))


def test_watch_groups_must_match_the_register(v2, tmp_path):
    # A register that moves one tag to another group: the watch file no longer fits.
    import yaml
    reg = yaml.safe_load(bm.REGISTER.read_text())
    for r in reg["tags"]:
        if r["tag"] == "CD-TI-301":
            r["group"] = "separator"
    path = tmp_path / "tags.yaml"
    path.write_text(yaml.safe_dump(reg))
    with pytest.raises(bm.BundleError, match="group"):
        bm.self_test(bm.load(v2), register=path)
