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


# ---------- pca_v2: with --watch ----------

from eval import calibrate_watch as cw  # noqa: E402
from tests.test_calibrate_watch import WGRID  # noqa: E402


@pytest.fixture
def watched(calibrated):
    watch = calibrated["out"].parent / "watch.json"
    cw.run(calibrated["model_path"], calibrated["out"], watch, repo_root=calibrated["repo"], q_grid=WGRID)
    return {**calibrated, "watch": watch, "bundle": calibrated["repo"] / "app" / "bundles" / "pca_v2"}


def build_v2(c):
    return build_bundle.run(c["model_path"], c["out"], c["bundle"], watch=c["watch"], repo_root=c["repo"])


def test_v2_bundle_holds_the_watch_file_and_its_record(watched):
    out = build_v2(watched)
    assert sorted(p.name for p in out.iterdir()) == ["limits.json", "model.npz", "watch.json"]
    got = json.loads((out / "watch.json").read_text())
    doc = json.loads(watched["watch"].read_text())
    (rec,) = (watched["repo"] / "eval" / "runs").glob("*_calibrate_watch.json")
    assert got == {**doc, "watch_record_sha256": run_record.sha256(rec)}
    b = bm.load(out)
    assert b.watch == got and bm.self_test(b)


def test_v2_refuses_a_watch_file_without_its_record(watched):
    doc = json.loads(watched["watch"].read_text())
    watched["watch"].write_text(json.dumps({**doc, "p": 50.0}))
    with pytest.raises(drv.CalibrationError, match="calibrate_watch"):
        build_v2(watched)
    assert not watched["bundle"].exists()


def test_v2_refuses_a_watch_file_for_other_limits(watched, tmp_path):
    # Other limits for the same model, with their own calibrate_pca record, so only the
    # watch file's limits checksum can catch the mismatch.
    other = tmp_path / "other_limits.json"
    lim = json.loads(watched["out"].read_text())
    other.write_text(json.dumps({**lim, "q": 99.9, "t2_lim": lim["t2_lim"] * 2}))
    runs = watched["repo"] / "eval" / "runs"
    (rec,) = runs.glob("*_calibrate_pca.json")
    doc = json.loads(rec.read_text())
    doc["outputs"]["limits"]["sha256"] = run_record.sha256(other)
    (runs / "20260101T000000Z_calibrate_pca.json").write_text(json.dumps(doc))
    with pytest.raises(drv.CalibrationError, match="other limits"):
        build_bundle.run(watched["model_path"], other, watched["bundle"], watch=watched["watch"],
                         repo_root=watched["repo"])
    assert not watched["bundle"].exists()


def test_main_defaults_to_v2_with_watch(monkeypatch):
    seen = {}
    monkeypatch.setattr(build_bundle, "run", lambda m, l, out, watch=None: seen.update(out=out, watch=watch))
    assert build_bundle.main(["--watch", "w.json"]) == 0
    assert seen["out"] == build_bundle.DEFAULT_V2 and str(seen["watch"]) == "w.json"
    assert build_bundle.main([]) == 0
    assert seen["out"] == build_bundle.DEFAULT_V1 and seen["watch"] is None
    assert build_bundle.DEFAULT_V1.name == "pca_v1" and build_bundle.DEFAULT_V2.name == "pca_v2"
