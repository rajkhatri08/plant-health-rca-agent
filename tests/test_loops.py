"""library/loops.yaml: structure, consistency with the tag register, and (opt-in, on the
open data) that each fixed-setpoint PI loop holds its measurement at its setpoint.

Provenance: decision 61."""

import re
from pathlib import Path

import numpy as np
import pytest
import yaml

from tests.test_leak_scan import find_leaks

REPO = Path(__file__).resolve().parents[1]
LOOPS_FILE = REPO / "library" / "loops.yaml"
LOOPS = yaml.safe_load(LOOPS_FILE.read_text())["loops"]
REGISTER = {r["tag"]: r for r in yaml.safe_load((REPO / "library" / "tags.yaml").read_text())["tags"]}
BY_ID = {lp["id"]: lp for lp in LOOPS}
KEYS = {"id", "controlled", "output", "mode", "setpoint", "setpoint_value", "period_s", "override"}


def test_ids_are_unique_and_follow_the_controlled_tag():
    # FD-FI-101 -> FD-FIC-101: same area and number, measurement letter + "IC".
    assert len(BY_ID) == len(LOOPS) == 19
    for lp in LOOPS:
        area, kind, number = lp["controlled"].split("-")
        assert lp["id"] == f"{area}-{kind[0]}IC-{number}"
        assert set(lp) <= KEYS


def test_controlled_tags_are_measurements_or_analyzers_and_used_once():
    tags = [lp["controlled"] for lp in LOOPS]
    assert len(set(tags)) == len(tags)
    for t in tags:
        assert REGISTER[t]["kind"] in ("measurement", "analyzer")


def test_every_valve_is_moved_by_exactly_one_loop():
    moved = [lp["output"]["valve"] for lp in LOOPS if "valve" in lp["output"]]
    valves = sorted(t for t, r in REGISTER.items() if r["kind"] == "valve")
    assert sorted(moved) == valves                     # all 11, each once


def test_output_is_a_valve_or_another_loops_setpoint():
    for lp in LOOPS:
        (key, target), = lp["output"].items()
        assert key in ("valve", "setpoint_of")
        if key == "setpoint_of":
            assert target in BY_ID and target != lp["id"]


def test_setpoint_is_cascaded_exactly_when_a_master_moves_it():
    slaves = {lp["output"]["setpoint_of"] for lp in LOOPS if "setpoint_of" in lp["output"]}
    masters_per_slave = [lp["output"]["setpoint_of"] for lp in LOOPS if "setpoint_of" in lp["output"]]
    assert len(masters_per_slave) == len(slaves)       # one master per cascaded loop
    for lp in LOOPS:
        if lp["id"] in slaves:
            assert lp["setpoint"] == "cascaded" and "setpoint_value" not in lp
        else:
            assert lp["setpoint"] == "fixed" and isinstance(lp["setpoint_value"], float)


def test_cascades_are_acyclic_and_end_in_a_valve():
    for lp in LOOPS:
        seen, cur = set(), lp
        while "setpoint_of" in cur["output"]:
            assert cur["id"] not in seen
            seen.add(cur["id"])
            cur = BY_ID[cur["output"]["setpoint_of"]]
        assert cur["output"]["valve"] in REGISTER


def test_modes_and_periods():
    for lp in LOOPS:
        assert lp["mode"] in ("P", "PI")
        assert lp["period_s"] in (3, 360, 900)
        if REGISTER[lp["controlled"]]["kind"] == "analyzer":
            # An analyzer loop acts once per analyzer update.
            assert lp["period_s"] == REGISTER[lp["controlled"]]["update_interval_min"] * 60


def test_the_purge_override():
    (lp,) = [lp for lp in LOOPS if "override" in lp]
    o = lp["override"]
    assert lp["output"] == {"valve": "SP-FV-407"} and o["tag"] == "SP-PI-403"
    assert o["shut_at_or_below"] < o["release_at"] < o["open_at_or_above"]


def test_loop_map_passes_the_leak_scan():
    text = LOOPS_FILE.read_text()
    assert find_leaks(text) == []
    assert not re.search(r"xm(?:eas|v)|contrl", text, re.IGNORECASE)


# Opt-in on the real open data: `pytest -q -m opendata`. Skipped when data/ is absent.
@pytest.mark.opendata
def test_fixed_setpoint_pi_loops_hold_their_setpoint_on_the_fit_pool(monkeypatch):
    # Integral action returns the measurement to its setpoint, so over the fit pool its
    # mean sits at the setpoint (decision 61 found every one within 0.003 sd).
    import dataset.loader as loader
    from ingest import tags as tagmap
    if not (REPO / "data" / "fault_free_training.parquet").is_file():
        pytest.skip("open data not present")
    monkeypatch.setattr(loader, "REPO_ROOT", REPO)
    fit = loader.load_normal("fit")
    runs = list(fit.runs.values())
    for lp in LOOPS:
        if lp["mode"] == "PI" and lp["setpoint"] == "fixed":
            (c,) = tagmap.column_indices(fit.columns, [lp["controlled"]])
            x = np.concatenate([r[9:, c] for r in runs]).astype(np.float64)
            assert abs(x.mean() - lp["setpoint_value"]) <= 0.02 * x.std(), lp["id"]
