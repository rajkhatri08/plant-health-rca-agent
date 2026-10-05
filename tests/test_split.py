"""eval/split.py: every difference between the dev and test splits, in one place (week 7 S1).

The loader is replaced by recording fakes; nothing here reads data or sets EVAL_MODE.
"""

import pytest

from dataset import loader as loader_mod
from eval import metrics
from eval import split as split_mod


@pytest.fixture
def calls(monkeypatch):
    seen = []
    monkeypatch.setattr(loader_mod, "load_normal", lambda pool: seen.append(("normal", pool)) or "N")
    monkeypatch.setattr(loader_mod, "load_faulty", lambda f, pool: seen.append(("faulty", f, pool)) or "F")
    monkeypatch.setattr(loader_mod, "load_testing", lambda f, *, purpose: seen.append(("testing", f, purpose)) or "T")
    return seen


def test_dev_is_the_dev_pool_at_onset_20(calls):
    sp = split_mod.get("dev", "dev_table")
    assert (sp.onset, sp.faults) == (metrics.TRAIN_ONSET, tuple(range(1, 16))) and sp.onset == 20
    assert sp.load_normal() == "N" and sp.load_faulty(4) == "F"
    assert calls == [("normal", "dev"), ("faulty", 4, "dev")]


def test_test_is_the_testing_files_at_onset_160_with_the_purpose_logged(calls):
    sp = split_mod.get("test", "dev_table pca_static")
    assert (sp.onset, sp.faults) == (metrics.TEST_ONSET, tuple(range(1, 21))) and sp.onset == 160
    assert sp.load_normal() == "T" and sp.load_faulty(17) == "T"
    assert calls == [("testing", 0, "dev_table pca_static"), ("testing", 17, "dev_table pca_static")]


@pytest.mark.parametrize("name, fault", [("dev", 16), ("dev", 0), ("test", 21), ("test", 0)])
def test_a_fault_outside_the_split_is_refused_before_any_load(calls, name, fault):
    with pytest.raises(loader_mod.LoaderError, match="isn't in the"):
        split_mod.get(name, "x").load_faulty(fault)
    assert calls == []


def test_test_outputs_and_the_llm_cache_go_to_the_sealed_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(loader_mod, "SEALED_ROOT", tmp_path / "sealed")
    dev, test = split_mod.get("dev", "x"), split_mod.get("test", "x")
    assert dev.out_dir(tmp_path / "data" / "agent_runs", "s_run") == tmp_path / "data" / "agent_runs"
    assert test.out_dir(tmp_path / "data" / "agent_runs", "s_run") == tmp_path / "sealed" / "test_outputs" / "s_run"
    assert dev.cache_dir(tmp_path / "data" / "llm_cache") == tmp_path / "data" / "llm_cache"
    assert test.cache_dir(tmp_path / "data" / "llm_cache") == tmp_path / "sealed" / "llm_cache"


def test_unknown_split_refused():
    with pytest.raises(ValueError, match="unknown split"):
        split_mod.get("train", "x")