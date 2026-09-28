"""eval/build_bundle.py: calibrate on synthetic runs, then build and self-test a bundle."""

import json

import pytest

from app.detector import bundle as bm
from eval import build_bundle, calibrate_driver as drv, run_record
from tests.test_calibrate_driver import GAPS, GRID, dpca_setup, setup  # noqa: F401 (fixtures)


@pytest.fixture
def calibrated(setup):
    drv.run(setup["model_path"], setup["out"], repo_root=setup["repo"], q_grid=GRID, gap_range=GAPS)
    return {**setup, "bundle": setup["repo"] / "app" / "bundles" / "pca_v1"}


def build(c):
    return build_bundle.run(c["model_path"], c["out"], c["bundle"], repo_root=c["repo"])


def test_bundle_holds_model_limits_and_record_checksums(calibrated):
    out = build(calibrated)
    assert sorted(p.name for p in out.iterdir()) == ["limits.json", "model.npz"]
    lim = json.loads((out / "limits.json").read_text())
    calib = json.loads(calibrated["out"].read_text())
    assert {k: lim[k] for k in calib} == calib
    runs = calibrated["repo"] / "eval" / "runs"
    (fit,) = runs.glob("*_fit_pca.json")
    (cal,) = runs.glob("*_calibrate_pca.json")
    assert lim["fit_record_sha256"] == run_record.sha256(fit)
    assert lim["calibration_record_sha256"] == run_record.sha256(cal)
    assert (out / "model.npz").read_bytes() == calibrated["model_path"].read_bytes()
    assert bm.self_test(bm.load(out))


def test_refuses_existing_bundle(calibrated):
    calibrated["bundle"].mkdir(parents=True)
    (calibrated["bundle"] / "keep").write_text("old")
    with pytest.raises(FileExistsError):
        build(calibrated)
    assert (calibrated["bundle"] / "keep").read_text() == "old"


def test_refuses_limits_without_a_calibration_record(calibrated):
    lim = json.loads(calibrated["out"].read_text())
    calibrated["out"].write_text(json.dumps({**lim, "q": 1.0}))
    with pytest.raises(drv.CalibrationError):
        build(calibrated)
    assert not calibrated["bundle"].exists()


def test_failed_self_test_leaves_nothing_behind(calibrated, tmp_path):
    reg = tmp_path / "tags.yaml"
    reg.write_text("tags:\n- {tag: XX-TI-001, kind: measurement}\n")
    with pytest.raises(bm.BundleError):
        build_bundle.run(calibrated["model_path"], calibrated["out"], calibrated["bundle"],
                         repo_root=calibrated["repo"], register=reg)
    assert not calibrated["bundle"].exists()
    assert list(calibrated["bundle"].parent.iterdir()) == []      # no temp folder left


def test_refuses_a_dpca_model(dpca_setup):
    # The replay scores unlagged samples, so the demo bundle stays static (decision 63).
    drv.run(dpca_setup["model_path"], dpca_setup["out"], repo_root=dpca_setup["repo"],
            q_grid=GRID, gap_range=GAPS)
    c = {**dpca_setup, "bundle": dpca_setup["repo"] / "app" / "bundles" / "pca_v1"}
    with pytest.raises(drv.CalibrationError, match="static PCA only"):
        build(c)
    assert not c["bundle"].exists()
