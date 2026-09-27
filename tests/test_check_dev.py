"""eval/check_dev.py on synthetic runs: calibrate with the driver first, then read dev."""

import json

import pytest

import dataset.loader as loader_mod
from eval import calibrate_driver as drv
from eval import check_dev, metrics, run_record
from tests.test_calibrate_driver import GAPS, GRID, setup  # noqa: F401 (fixture)
from tests.test_fit_pca import two_factor_runs


@pytest.fixture
def calibrated(setup, monkeypatch):
    drv.run(setup["model_path"], setup["out"], repo_root=setup["repo"], q_grid=GRID, gap_range=GAPS)
    dev = two_factor_runs(numbers=range(101, 111), samples=120, seed=11)
    calls = []

    def load_normal(pool):
        calls.append(pool)
        if pool != "dev":
            pytest.fail(f"dev check loaded normal pool {pool}")
        return dev

    monkeypatch.setattr(loader_mod, "load_normal", load_normal)
    monkeypatch.setattr(loader_mod, "load_faulty", lambda *a: pytest.fail("dev check loaded faulty runs"))
    return {**setup, "dev": dev, "dev_calls": calls}


def check(c, **kw):
    return check_dev.run(c["out"], c["model_path"], repo_root=c["repo"], n_boot=50, **kw)


def test_reading_matches_a_direct_count_and_is_recorded(calibrated):
    count, hours, per_24h, (low, high) = check(calibrated)
    lim = json.loads(calibrated["out"].read_text())
    scored = drv.score_runs(calibrated["model"], calibrated["dev"])
    alert = drv.tracks(scored, (lim["t2_lim"], lim["spe_lim"]), lim["n"], lim["gap"], lim["warmup"])
    direct = metrics.false_alerts_per_24h([metrics.ScoredRun(0, k, a) for k, a in alert.items()],
                                          lim["warmup"])
    assert (count, hours, per_24h) == pytest.approx(direct)
    assert hours == pytest.approx(10 * (120 - lim["warmup"]) * 3 / 60)
    assert low <= high
    (path,) = (calibrated["repo"] / "eval" / "runs").glob("*_dev_false_alerts.json")
    rec = json.loads(path.read_text())
    assert rec["config"]["pool"] == "dev" and rec["seeds"] == {"bootstrap": check_dev.BOOTSTRAP_SEED}
    assert rec["config"]["calibration_record"].endswith("_calibrate_pca.json")
    assert rec["metrics"]["notifications"] == count and rec["metrics"]["ci95"] == pytest.approx([low, high])


def test_loads_only_normal_dev(calibrated):
    check(calibrated)
    assert calibrated["dev_calls"] == ["dev"]


def test_same_seed_same_interval(calibrated):
    first = check(calibrated)[3]
    # Records are never overwritten, and two runs in one second share a name.
    for p in (calibrated["repo"] / "eval" / "runs").glob("*_dev_false_alerts.json"):
        p.unlink()
    assert check(calibrated)[3] == first


def test_refuses_a_different_model(calibrated, tmp_path):
    other = tmp_path / "other.npz"
    other.write_bytes(calibrated["model_path"].read_bytes() + b"x")
    with pytest.raises(drv.CalibrationError):
        check_dev.run(calibrated["out"], other, repo_root=calibrated["repo"], n_boot=50)
    assert calibrated["dev_calls"] == []


def test_refuses_limits_without_a_calibration_record(calibrated):
    lim = json.loads(calibrated["out"].read_text())
    lim["q"] = 50.0
    calibrated["out"].write_text(json.dumps(lim))       # no longer the recorded file
    with pytest.raises(drv.CalibrationError):
        check(calibrated)
    assert calibrated["dev_calls"] == []


def test_refuses_dirty_tree_before_loading(calibrated):
    (calibrated["repo"] / "code.py").write_text("x = 2\n")
    with pytest.raises(run_record.RunRecordError):
        check(calibrated)
    assert calibrated["dev_calls"] == []