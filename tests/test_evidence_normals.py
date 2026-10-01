"""eval/evidence_normals.py on synthetic runs (never data/)."""

import json

import numpy as np
import pytest

import dataset.loader as loader_mod
from dataset.convert import VARIABLES
from dataset.loader import Runs
from eval import evidence_normals as en
from eval import masked, run_record
from ingest import tags as tagmap
from tests.test_fit_pca import two_factor_runs

TAGS = [r["tag"] for r in tagmap.register()]


@pytest.fixture
def calib(monkeypatch, git_repo, tmp_path):
    runs = two_factor_runs(numbers=range(1, 21), samples=60, seed=3)
    calls = []

    def load_normal(pool):
        calls.append(pool)
        if pool != "calibration":
            pytest.fail(f"evidence normals loaded normal pool {pool}")
        return runs

    monkeypatch.setattr(loader_mod, "load_normal", load_normal)
    monkeypatch.setattr(loader_mod, "load_faulty", lambda *a: pytest.fail("loaded faulty runs"))
    return {"runs": runs, "calls": calls, "repo": git_repo, "out": tmp_path / "models" / "normals.json"}


def compute(c, **kw):
    return en.run(c["out"], repo_root=c["repo"], **kw)


def test_bands_are_the_masked_rules_bands_for_all_52_tags(calib):
    doc = compute(calib)
    cols = tagmap.column_indices(VARIABLES, TAGS)
    direct = masked.normal_bands([calib["runs"].runs[k] for k in sorted(calib["runs"].runs)], cols)
    assert list(doc["tags"]) == TAGS and len(TAGS) == 52
    assert doc["tags"] == {t: list(direct[c]) for t, c in zip(TAGS, cols)}
    assert doc["band"] == [0.5, 99.5] and doc["warmup"] == 9 and doc["pool"] == "calibration"
    assert json.loads(calib["out"].read_text()) == doc
    assert calib["calls"] == ["calibration"]


def test_record_and_load_round_trip(calib):
    doc = compute(calib)
    (path,) = (calib["repo"] / "eval" / "runs").glob("*_evidence_normals.json")
    rec = json.loads(path.read_text())
    assert rec["metrics"]["bands"] == doc["tags"] and rec["config"]["tags"] == 52
    record, bands = en.load_normals(calib["out"], calib["repo"])
    assert record == path and bands == {t: tuple(b) for t, b in doc["tags"].items()}


def test_load_refuses_a_file_without_its_record(calib):
    compute(calib)
    doc = json.loads(calib["out"].read_text())
    doc["tags"]["RX-TI-204"] = [0.0, 1.0]
    calib["out"].write_text(json.dumps(doc))
    with pytest.raises(en.NormalsError):
        en.load_normals(calib["out"], calib["repo"])


def test_refuses_existing_output_and_dirty_tree_before_loading(calib):
    calib["out"].parent.mkdir(parents=True)
    calib["out"].write_text("{}")
    with pytest.raises(FileExistsError):
        compute(calib)
    calib["out"].unlink()
    (calib["repo"] / "code.py").write_text("x = 2\n")
    with pytest.raises(run_record.RunRecordError):
        compute(calib)
    assert calib["calls"] == []


def test_refuses_an_empty_band(calib, monkeypatch):
    flat = Runs("fault_free_training", 0, "calibration", VARIABLES,
                {k: v.copy() for k, v in calib["runs"].runs.items()})
    col = tagmap.column_indices(VARIABLES, ["SP-AI-412"])[0]
    for v in flat.runs.values():
        v[:, col] = np.float32(13.8)
    monkeypatch.setattr(loader_mod, "load_normal", lambda pool: flat)
    with pytest.raises(en.NormalsError, match="SP-AI-412"):
        compute(calib)
    assert not calib["out"].exists()
