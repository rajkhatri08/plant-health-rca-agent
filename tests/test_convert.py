"""dataset/convert.py against a fake repo and synthetic raw files only."""

import hashlib
import json
import subprocess

import numpy as np
import pandas as pd
import pytest
import yaml

import dataset.convert as convert_mod
from dataset.convert import ConversionError, route
from tests.conftest import make_columns

SENTINEL = 98765.4321


def _files(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()) if root.exists() else []


# --- isolation ---

def test_defaults_point_nowhere(tmp_path):
    for p in (convert_mod.REPO_ROOT, convert_mod.DEFAULT_RAW_DIR, convert_mod.DEFAULT_SEALED_DIR):
        assert p.is_relative_to(tmp_path) and not p.exists()


def test_cli_with_defaults_cannot_reach_anything(capsys):
    assert convert_mod.main(["fault_free_training"]) == 1
    assert "error" in capsys.readouterr().err


# --- routing ---

@pytest.mark.parametrize("name", convert_mod.NAMES)
@pytest.mark.parametrize("fault", range(21))
def test_route_rule(name, fault):
    expected = "open" if (name == "fault_free_training" and fault == 0) or (
        name == "faulty_training" and 1 <= fault <= 15) else "sealed"
    assert route(name, fault) == expected


def test_all_four_files_route_correctly(fake_repo):
    for name in convert_mod.NAMES:
        fake_repo.add_raw(name)
        fake_repo.convert(name)

    assert _files(fake_repo.root / "data") == [
        "conversion_report_fault_free_training.json",
        "conversion_report_faulty_training.json",
        "fault_free_training.parquet",
        "faulty_training/fault_01.parquet",
        "faulty_training/fault_02.parquet",
    ]
    assert _files(fake_repo.sealed) == [
        "conversion_report_fault_free_testing.json",
        "conversion_report_faulty_testing.json",
        "conversion_report_faulty_training.json",
        "fault_free_testing.parquet",
        "faulty_testing/fault_01.parquet",
        "faulty_testing/fault_02.parquet",
        "faulty_testing/fault_16.parquet",
        "faulty_training/fault_16.parquet",
    ]
    # No test-split output or quarantined fault ever lands in open data.
    for f in _files(fake_repo.root / "data"):
        assert "testing" not in f
        assert not any(f"fault_{n}" in f for n in range(16, 21))


def test_parquet_contents(fake_repo):
    cols = make_columns("faulty_training")
    fake_repo.add_raw("faulty_training", cols)
    fake_repo.convert("faulty_training")
    df = pd.read_parquet(fake_repo.root / "data" / "faulty_training" / "fault_02.parquet")
    assert list(df.columns) == list(convert_mod.COLUMNS)
    assert all(df[c].dtype == np.int16 for c in convert_mod.ID_COLUMNS)
    assert all(df[c].dtype == np.float32 for c in convert_mod.VARIABLES)
    assert len(df) == 2 * 3 and set(df.faultNumber) == {2}
    # Sorted by run, then sample.
    assert list(zip(df.simulationRun, df["sample"])) == [(1, 1), (1, 2), (1, 3), (2, 1), (2, 2), (2, 3)]
    # Values follow their rows through the sort.
    m = (cols["faultNumber"] == 2) & (cols["simulationRun"] == 2) & (cols["sample"] == 3)
    assert df.xmv_11.iloc[-1] == np.float32(cols["xmv_11"][m][0])


@pytest.mark.parametrize("name, fault", [("faulty_training", 16), ("faulty_testing", 1),
                                         ("fault_free_testing", 0), ("faulty_training", 0)])
def test_open_write_refuses_disallowed(fake_repo, name, fault):
    path = fake_repo.root / "data" / "x.parquet"
    with pytest.raises(ConversionError, match="refusing"):
        convert_mod._write_open(None, name, fault, path, fake_repo.root)
    assert not path.exists()


def test_open_write_refuses_outside_data(fake_repo):
    with pytest.raises(ConversionError, match="outside"):
        convert_mod._write_open(None, "faulty_training", 1, fake_repo.root / "x.parquet",
                                fake_repo.root)


def test_sealed_write_refuses_inside_repo(fake_repo):
    inside = fake_repo.root / "sealed"
    with pytest.raises(ConversionError, match="outside the sealed folder"):
        convert_mod._write_sealed(None, inside / "x.parquet", inside, fake_repo.root)


# --- guards ---

def test_sealed_dir_inside_repo_refused(fake_repo):
    fake_repo.add_raw("faulty_testing")
    with pytest.raises(ConversionError, match="outside the repo"):
        convert_mod.convert("faulty_testing", repo_root=fake_repo.root, raw_dir=fake_repo.raw,
                            sealed_dir=fake_repo.root / "sealed")
    assert _files(fake_repo.root / "sealed") == []


def test_existing_output_refused(fake_repo):
    fake_repo.add_raw("fault_free_training")
    fake_repo.convert("fault_free_training")
    with pytest.raises(ConversionError, match="already exist"):
        fake_repo.convert("fault_free_training")


def test_md5_mismatch_stops_before_parsing(fake_repo, monkeypatch):
    fake_repo.add_raw("faulty_training")
    fake_repo.manifest["raw_files"]["faulty_training"]["md5"] = "f" * 32
    fake_repo.save_manifest()
    monkeypatch.setattr(convert_mod, "read_frame", lambda *a, **k: pytest.fail("parsed"))
    with pytest.raises(ConversionError, match="MD5 mismatch"):
        fake_repo.convert("faulty_training")


def test_crosscheck_only_for_fault_free_training(fake_repo):
    fake_repo.add_raw("faulty_training")
    with pytest.raises(ConversionError, match="only for fault_free_training"):
        fake_repo.convert("faulty_training", crosscheck=True)


# --- validation ---

def _expect_failure(fake_repo, name, cols, match, **kwargs):
    fake_repo.add_raw(name, cols, **kwargs)
    with pytest.raises(ConversionError, match=match):
        fake_repo.convert(name)
    assert _files(fake_repo.root / "data") == [] and _files(fake_repo.sealed) == []


def test_non_integer_id(fake_repo):
    cols = make_columns("faulty_training")
    cols["sample"][0] += 0.5
    _expect_failure(fake_repo, "faulty_training", cols, "int16")


def test_id_out_of_int16_range(fake_repo):
    cols = make_columns("faulty_training")
    cols["simulationRun"][cols["simulationRun"] == 2] = 40000
    _expect_failure(fake_repo, "faulty_training", cols, "int16")


def test_wrong_run_count(fake_repo):
    cols = make_columns("faulty_training")
    cols["simulationRun"][cols["faultNumber"] == 1] = 1  # fault 1: one run, same row count
    _expect_failure(fake_repo, "faulty_training", cols, "fault 1: 1 runs, expected 2")


def test_wrong_total_rows(fake_repo):
    _expect_failure(fake_repo, "faulty_training", make_columns("faulty_training", runs=3), "rows")


def test_wrong_sample_count(fake_repo):
    _expect_failure(fake_repo, "faulty_testing",
                    make_columns("faulty_testing", samples=5), "rows")


def test_gap_in_sample_numbers(fake_repo):
    cols = make_columns("faulty_training", shuffle=False)
    cols["sample"][2] = 4  # run 1 of fault 1 has samples 1, 2, 4
    _expect_failure(fake_repo, "faulty_training", cols, "samples 1..3")


def test_run_with_extra_samples_and_run_with_fewer(fake_repo):
    cols = make_columns("faulty_training", shuffle=False)
    cols["simulationRun"][2] = 2  # fault 1: run 1 gets 2 samples, run 2 gets 4
    _expect_failure(fake_repo, "faulty_training", cols, "samples 1..3")


def test_wrong_fault_set(fake_repo):
    _expect_failure(fake_repo, "faulty_training",
                    make_columns("faulty_training", faults=[1, 2, 17]), "fault numbers")


def test_missing_column(fake_repo):
    cols = make_columns("fault_free_training")
    del cols["xmv_11"]
    _expect_failure(fake_repo, "fault_free_training", cols, "column mismatch")


def test_extra_column(fake_repo):
    cols = make_columns("fault_free_training")
    cols["xmv_12"] = cols["xmv_11"]
    _expect_failure(fake_repo, "fault_free_training", cols, "column mismatch")


def test_wrong_object_name(fake_repo):
    _expect_failure(fake_repo, "fault_free_training", make_columns("fault_free_training"),
                    "object named", object_name="something_else")


# --- reports, access log, dirty flag ---

def test_reports(fake_repo, capsys):
    fake_repo.add_raw("faulty_training")
    snippet = fake_repo.convert("faulty_training")
    open_report = json.loads((fake_repo.root / "data" / "conversion_report_faulty_training.json").read_text())
    sealed_path = fake_repo.sealed / "conversion_report_faulty_training.json"
    sealed_report = json.loads(sealed_path.read_text())

    for report in (open_report, sealed_report):
        assert {"commit", "dirty", "versions", "raw_md5", "rows", "faults", "nonfinite", "files"} <= set(report)
        assert set(report["versions"]) == {"python", "pyreadr", "pandas", "pyarrow", "numpy", "pyyaml"}
    # Each side describes only its own faults.
    assert set(open_report["faults"]) == {"1", "2"}
    assert set(sealed_report["faults"]) == {"16"}
    assert open_report["rows"] == 12 and sealed_report["rows"] == 6
    for rel, f in open_report["files"].items():
        assert hashlib.sha256((fake_repo.root / "data" / rel).read_bytes()).hexdigest() == f["sha256"]

    assert snippet["sealed_reports"] == {
        "faulty_training": hashlib.sha256(sealed_path.read_bytes()).hexdigest()}
    assert snippet["open_reports"]["faulty_training"]["files"] == open_report["files"]
    printed = capsys.readouterr().out
    assert yaml.safe_load(printed.split("(conversion section):\n", 1)[1]) == snippet


def test_access_log_one_line_per_run_including_failures(fake_repo, monkeypatch):
    fake_repo.add_raw("fault_free_training")
    fake_repo.convert("fault_free_training")

    fake_repo.add_raw("faulty_training")
    fake_repo.manifest["raw_files"]["faulty_training"]["md5"] = "f" * 32
    fake_repo.save_manifest()
    with pytest.raises(ConversionError):
        fake_repo.convert("faulty_training")

    fake_repo.add_raw("faulty_testing")

    def boom(*a, **k):
        raise KeyboardInterrupt  # stands in for a killed run
    monkeypatch.setattr(convert_mod, "read_frame", boom)
    with pytest.raises(KeyboardInterrupt):
        fake_repo.convert("faulty_testing")

    lines = [json.loads(line) for line in fake_repo.log_lines()]
    assert [line["raw_file"] for line in lines] == [
        "fault_free_training.RData", "faulty_training.RData", "faulty_testing.RData"]
    for line in lines:
        assert set(line) == {"time", "action", "raw_file", "commit", "dirty"}
        assert line["action"] == "convert"


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t",
                    "-c", "commit.gpgsign=false", *args], check=True, capture_output=True)


def test_dirty_flag_scope(fake_repo):
    root = fake_repo.root
    (root / "dataset" / "tool.py").write_text("x = 1\n")
    (root / "requirements.txt").write_text("numpy==1\n")
    (root / "eval").mkdir()
    (root / "eval" / "test_access.log").write_text("")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")

    commit, dirty = convert_mod.git_state(root)
    assert len(commit) == 40 and dirty is False

    (root / "eval" / "test_access.log").write_text("{}\n")
    fake_repo.manifest["dataset"] = {"download_date": "2026-09-24"}
    fake_repo.save_manifest()
    assert convert_mod.git_state(root)[1] is False

    (root / "dataset" / "tool.py").write_text("x = 2\n")
    assert convert_mod.git_state(root)[1] is True


def test_dirty_flag_untracked_script_counts(fake_repo):
    _git(fake_repo.root, "init", "-q")
    _git(fake_repo.root, "add", "-A")
    _git(fake_repo.root, "commit", "-q", "-m", "init")
    (fake_repo.root / "dataset" / "new.py").write_text("")
    assert convert_mod.git_state(fake_repo.root)[1] is True


# --- crosscheck ---

def test_crosscheck_identical(fake_repo, capsys):
    fake_repo.add_raw("fault_free_training")
    fake_repo.convert("fault_free_training", crosscheck=True)
    assert "identical: yes" in capsys.readouterr().out


def test_crosscheck_mismatch_writes_nothing(fake_repo, monkeypatch, capsys):
    import pyreadr
    fake_repo.add_raw("fault_free_training")
    real = pyreadr.read_r

    def altered(path):
        out = real(path)
        out["fault_free_training"].loc[0, "xmeas_5"] += 1.0
        return out
    monkeypatch.setattr(pyreadr, "read_r", altered)
    with pytest.raises(ConversionError, match="crosscheck failed"):
        fake_repo.convert("fault_free_training", crosscheck=True)
    assert "identical: no" in capsys.readouterr().out
    assert _files(fake_repo.root / "data") == []


# --- no values ever printed or stored ---

def test_sentinel_never_appears(fake_repo, monkeypatch, capsys):
    monkeypatch.setattr(convert_mod, "REPO_ROOT", fake_repo.root)
    monkeypatch.setattr(convert_mod, "DEFAULT_RAW_DIR", fake_repo.raw)
    monkeypatch.setattr(convert_mod, "DEFAULT_SEALED_DIR", fake_repo.sealed)

    # Failure paths first: a validation error, and a reader error.
    bad = make_columns("faulty_training", runs=3)
    bad["xmeas_1"][:] = SENTINEL
    fake_repo.add_raw("faulty_training", bad)
    assert convert_mod.main(["faulty_training"]) == 1
    fake_repo.add_raw("faulty_testing", make_columns("faulty_testing") | {"xmeas_2": np.full(24, SENTINEL)},
                      kinds={"xmeas_3": "cplx"})
    assert convert_mod.main(["faulty_testing"]) == 1

    for name in convert_mod.NAMES:
        cols = make_columns(name)
        cols["xmeas_1"][:] = SENTINEL
        cols["xmv_3"][::2] = SENTINEL
        fake_repo.add_raw(name, cols)
    assert convert_mod.main(["fault_free_training", "--crosscheck"]) == 0
    for name in convert_mod.NAMES[1:]:
        assert convert_mod.main([name]) == 0

    captured = capsys.readouterr()
    texts = [captured.out, captured.err, (fake_repo.root / "eval" / "test_access.log").read_text()]
    texts += [p.read_text() for p in fake_repo.root.rglob("*.json")]
    texts += [p.read_text() for p in fake_repo.sealed.rglob("*.json")]
    assert len(texts) == 3 + 2 + 3
    for text in texts:
        assert "98765" not in text and "9.8765" not in text
