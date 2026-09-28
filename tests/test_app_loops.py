"""app/detector/loops.py: the loop map at runtime, and valve headroom (decisions 61, 62)."""

import numpy as np
import pytest
import yaml

from app.detector import loops as lp_mod


@pytest.fixture(scope="module")
def loops():
    return lp_mod.load()


def test_loads_every_loop(loops):
    assert len(loops) == 19
    assert sum(lp.valve is not None for lp in loops.values()) == 11


@pytest.mark.parametrize("loop_id, valve", [
    ("RX-TIC-204", "RX-FV-206"),          # reactor temperature -> cooling water loop -> valve
    ("ST-AIC-612", "ST-FV-607"),          # two levels of cascade: -> ST-TIC-604 -> ST-FIC-605
    ("RX-AIC-214", "FD-FV-106"),
    ("SP-AIC-412", "SP-FV-407"),
    ("ST-FIC-603", "CD-FV-302"),          # a valve loop is its own end
])
def test_end_valve_follows_the_cascade(loops, loop_id, valve):
    assert lp_mod.end_valve(loops, loop_id) == valve


def test_end_valve_refuses_unknown_loop(loops):
    with pytest.raises(lp_mod.LoopMapError):
        lp_mod.end_valve(loops, "XX-FIC-999")


@pytest.mark.parametrize("position, expected", [
    (0.0, 0.0), (100.0, 0.0), (50.0, 50.0), (2.0, 2.0), (98.0, 2.0), (63.05, 36.95),
])
def test_headroom_is_the_distance_to_0_and_100(position, expected):
    assert lp_mod.headroom(position) == pytest.approx(expected)


def test_headroom_on_an_array():
    assert lp_mod.headroom(np.array([0.0, 25.0, 99.5])) == pytest.approx([0.0, 25.0, 0.5])


@pytest.mark.parametrize("bad", [np.nan, np.inf, -0.1, 100.1])
def test_headroom_refusals(bad):
    with pytest.raises(ValueError):
        lp_mod.headroom(bad)


def test_valve_headroom_covers_every_valve_with_its_loop(loops):
    positions = {lp.valve: 10.0 * i for i, lp in enumerate(v for v in loops.values() if v.valve)}
    out = lp_mod.valve_headroom(positions, loops)
    assert set(out) == set(positions)
    assert out["CD-FV-302"]["loop"] == "ST-FIC-603"
    for valve, row in out.items():
        assert row["position_pct"] == positions[valve]
        assert row["headroom_pct"] == pytest.approx(min(positions[valve], 100 - positions[valve]))


def test_valve_headroom_refuses_a_missing_valve(loops):
    with pytest.raises(ValueError):
        lp_mod.valve_headroom({"FD-FV-105": 50.0}, loops)


def _write(tmp_path, rows):
    p = tmp_path / "loops.yaml"
    p.write_text(yaml.safe_dump({"loops": rows}))
    return p


@pytest.mark.parametrize("rows", [
    # two loops on one valve
    [{"id": "A", "controlled": "FD-FI-101", "output": {"valve": "FD-FV-105"}, "mode": "P", "setpoint": "fixed", "period_s": 3},
     {"id": "B", "controlled": "FD-FI-102", "output": {"valve": "FD-FV-105"}, "mode": "P", "setpoint": "fixed", "period_s": 3}],
    # a cascade cycle
    [{"id": "A", "controlled": "FD-FI-101", "output": {"setpoint_of": "B"}, "mode": "P", "setpoint": "cascaded", "period_s": 3},
     {"id": "B", "controlled": "FD-FI-102", "output": {"setpoint_of": "A"}, "mode": "P", "setpoint": "cascaded", "period_s": 3}],
    # a "valve" that isn't a valve
    [{"id": "A", "controlled": "FD-FI-101", "output": {"valve": "FD-FI-102"}, "mode": "P", "setpoint": "fixed", "period_s": 3}],
    # an unknown controlled tag
    [{"id": "A", "controlled": "ZZ-FI-999", "output": {"valve": "FD-FV-105"}, "mode": "P", "setpoint": "fixed", "period_s": 3}],
    # a duplicate id
    [{"id": "A", "controlled": "FD-FI-101", "output": {"valve": "FD-FV-105"}, "mode": "P", "setpoint": "fixed", "period_s": 3},
     {"id": "A", "controlled": "FD-FI-102", "output": {"valve": "FD-FV-106"}, "mode": "P", "setpoint": "fixed", "period_s": 3}],
])
def test_load_refuses_an_inconsistent_map(tmp_path, rows):
    with pytest.raises(lp_mod.LoopMapError):
        lp_mod.load(_write(tmp_path, rows))