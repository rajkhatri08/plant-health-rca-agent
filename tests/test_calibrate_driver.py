"""eval/calibrate_driver.py on synthetic runs (never data/), with a small grid for speed."""

import hashlib
import json

import pytest

import dataset.loader as loader_mod
from app.detector import pca
from dataset import selection
from dataset.convert import VARIABLES
from dataset.loader import Runs
from eval import calibrate as cal
from eval import calibrate_driver as drv
from eval import fit_pca, run_record
from ingest import tags as tagmap
from tests.test_fit_pca import FAST, two_factor_runs

WARMUP = 3                                   # small, so n_range is 1..4
GRID = (90.0, 99.0, 99.9)
GAPS = range(0, 3)
SELECTION = [2, 4, 6, 8, 10]


def faulty_runs(fault, numbers=range(1, 13), samples=120):
    """Two-factor runs with a step on every fast tag after sample 20, larger per fault."""
    runs = two_factor_runs(numbers=numbers, samples=samples, seed=100 + fault)
    cols = tagmap.column_indices(VARIABLES, FAST)
    for k in runs.runs:
        runs.runs[k][20:, cols] += 0.5 * fault
    return Runs(name="faulty_training", fault=fault, pool="forest_ceiling", columns=VARIABLES,
                runs=runs.runs)


@pytest.fixture
def setup(tmp_path, monkeypatch, git_repo):
    """A fitted model, its fit record, and patched loaders that refuse dev."""
    fit = two_factor_runs(samples=120)
    model = pca.fit(fit_pca.fit_matrix(fit, WARMUP, FAST), FAST, 2)
    model_path = tmp_path / "pca.npz"
    pca.save(model, model_path)
    runs_dir = git_repo / "eval" / "runs"
    runs_dir.mkdir(parents=True)
    fit_rec = {"config": {"warmup": WARMUP},
               "outputs": {"model": {"sha256": run_record.sha256(model_path)}}}
    (runs_dir / "20260927T000000Z_fit_pca.json").write_text(json.dumps(fit_rec))

    calls = []
    calib = two_factor_runs(numbers=range(1, 21), samples=120, seed=7)

    def load_normal(pool):
        calls.append(("normal", pool))
        if pool != "calibration":
            pytest.fail(f"calibration driver loaded normal pool {pool}")
        return calib

    def load_faulty(fault, pool):
        calls.append(("faulty", fault, pool))
        if pool != "forest_ceiling" or fault not in cal.SELECTION_FAULTS:
            pytest.fail(f"calibration driver loaded fault {fault} from {pool}")
        return faulty_runs(fault)

    monkeypatch.setattr(loader_mod, "load_normal", load_normal)
    monkeypatch.setattr(loader_mod, "load_faulty", load_faulty)
    monkeypatch.setattr(selection, "load", lambda repo_root=None: {"seed": 7, "numbers": SELECTION})
    return {"model_path": model_path, "model": model, "calib": calib, "calls": calls,
            "repo": git_repo, "out": tmp_path / "models" / "limits.json"}


def run(s, **kw):
    return drv.run(s["model_path"], s["out"], repo_root=s["repo"], q_grid=GRID, gap_range=GAPS, **kw)


def the_record(s):
    (path,) = (s["repo"] / "eval" / "runs").glob("*_calibrate_pca.json")
    return json.loads(path.read_text())


def test_limits_file_and_record(setup):
    doc = run(setup)
    on_disk = json.loads(setup["out"].read_text())
    assert on_disk == doc
    assert doc["detector"] == "pca_static" and doc["warmup"] == WARMUP and doc["lags"] == 0
    assert doc["model_sha256"] == hashlib.sha256(setup["model_path"].read_bytes()).hexdigest()
    rec = the_record(setup)
    assert rec["dirty"] is False
    assert rec["config"]["fit_record"] == "eval/runs/20260927T000000Z_fit_pca.json"
    assert rec["config"]["n_range"] == [1, 2, 3, 4] and rec["config"]["gap_range"] == [0, 1, 2]
    assert rec["config"]["calibration_runs"] == 20 and rec["config"]["selection_runs"] == 5
    assert rec["seeds"] == {"selection": 7}
    assert rec["outputs"]["limits"]["sha256"] == hashlib.sha256(setup["out"].read_bytes()).hexdigest()
    assert len(rec["metrics"]["settings"]) == 4 * 3
    assert set(rec["metrics"]["selection_rates"]) == {f"fault_{f:02d}" for f in cal.SELECTION_FAULTS}


def test_chosen_setting_follows_choose_on_the_recorded_table(setup):
    doc = run(setup)
    rec = the_record(setup)
    candidates = {}
    for key, row in rec["metrics"]["settings"].items():
        n, g = (int(x) for x in key[1:].split("_g"))
        candidates[(n, g)] = (row["q"], row["score"] if row["score"] is not None else 0.0)
    assert cal.choose(candidates) == (doc["n"], doc["gap"], doc["q"])


def test_limits_are_the_calibration_percentiles(setup):
    doc = run(setup)
    model, calib = setup["model"], setup["calib"]
    cols = tagmap.column_indices(calib.columns, model.tags)
    scored = [pca.scores(model, calib.runs[k][:, cols]) for k in sorted(calib.runs)]
    expected = cal.limits_at([s[0] for s in scored], [s[1] for s in scored], doc["q"], WARMUP)
    assert (doc["t2_lim"], doc["spe_lim"]) == pytest.approx(expected)


def test_every_eligible_setting_meets_the_budget_and_floor_is_flagged(setup):
    run(setup)
    rec = the_record(setup)
    for row in rec["metrics"]["settings"].values():
        if row["q"] is None:
            assert row["score"] is None and row["at_floor"] is None
        else:
            assert 0 <= row["budget_share"] <= 1.0
            assert row["at_floor"] == (row["q"] == GRID[0])
    assert rec["metrics"]["calibration"]["per_24h"] <= 1.0


def test_only_calibration_and_selection_data_are_loaded(setup):
    run(setup)
    assert ("normal", "calibration") in setup["calls"]
    assert {c[1] for c in setup["calls"] if c[0] == "faulty"} == set(cal.SELECTION_FAULTS)
    assert all(c[-1] in ("calibration", "forest_ceiling") for c in setup["calls"])


def test_refuses_existing_output_before_loading(setup):
    setup["out"].parent.mkdir(parents=True)
    setup["out"].write_text("old")
    with pytest.raises(FileExistsError):
        run(setup)
    assert setup["calls"] == [] and setup["out"].read_text() == "old"


def test_refuses_dirty_tree_before_loading(setup):
    (setup["repo"] / "code.py").write_text("x = 2\n")
    with pytest.raises(run_record.RunRecordError):
        run(setup)
    assert setup["calls"] == []


@pytest.mark.parametrize("records", [0, 2])
def test_needs_exactly_one_fit_record_for_the_model(setup, records):
    runs_dir = setup["repo"] / "eval" / "runs"
    (existing,) = runs_dir.glob("*_fit_pca.json")
    if records == 0:
        existing.unlink()
    else:
        (runs_dir / "20260928T000000Z_fit_pca.json").write_text(existing.read_text())
    with pytest.raises(drv.CalibrationError):
        run(setup)
    assert setup["calls"] == []


def test_refuses_selection_numbers_missing_from_the_pool(setup, monkeypatch):
    monkeypatch.setattr(selection, "load", lambda repo_root=None: {"seed": 7, "numbers": [2, 99]})
    with pytest.raises(drv.CalibrationError):
        run(setup)


def test_main_reports_errors(setup, capsys):
    setup["out"].parent.mkdir(parents=True)
    setup["out"].write_text("old")
    assert drv.main(["--model", str(setup["model_path"]), "--out", str(setup["out"])]) == 1
    assert "already exists" in capsys.readouterr().err