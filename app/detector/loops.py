"""The control loop map and valve headroom (decisions 10, 61, 62).

Runtime code: no imports from dataset/, eval/ or ingest/. Reads library/loops.yaml and
library/tags.yaml, both agent-visible.

- load(): the loops, checked against the register (every tag known, each valve moved by
  one loop, cascades acyclic and ending in a valve).
- end_valve(): the valve a loop finally moves, following its cascade down. For a cascade
  master (reactor temperature) that's the inner loop's valve (the cooling water valve).
- headroom(): how far a valve is from its physical limits, min(position, 100 - position)
  in % open. A valve at 0% or 100% can't absorb any more of a disturbance, so its loop
  has lost control of its measurement.
- valve_headroom(): headroom as of one sample (the latest), per valve, with its loop.
  No thresholds: it's evidence for diagnosis, not an alarm.
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
LOOPS_FILE = REPO_ROOT / "library" / "loops.yaml"
REGISTER = REPO_ROOT / "library" / "tags.yaml"
VALVE_MIN, VALVE_MAX = 0.0, 100.0            # physical limits, % open


class LoopMapError(ValueError):
    pass


@dataclass(frozen=True)
class Loop:
    id: str
    controlled: str
    valve: str | None            # set when the loop moves a valve directly
    setpoint_of: str | None      # set when the loop moves another loop's setpoint
    mode: str                    # "P" or "PI"
    setpoint: str                # "fixed" or "cascaded"
    setpoint_value: float | None
    period_s: int


def load(path=LOOPS_FILE, register=REGISTER) -> dict:
    """{loop id: Loop}, in file order. Raises LoopMapError on an inconsistent map."""
    rows = yaml.safe_load(Path(path).read_text())["loops"]
    kinds = {r["tag"]: r["kind"] for r in yaml.safe_load(Path(register).read_text())["tags"]}
    loops = {}
    for r in rows:
        out = r["output"]
        lp = Loop(r["id"], r["controlled"], out.get("valve"), out.get("setpoint_of"), r["mode"],
                  r["setpoint"], r.get("setpoint_value"), r["period_s"])
        if lp.id in loops:
            raise LoopMapError(f"loop {lp.id} appears twice")
        if (lp.valve is None) == (lp.setpoint_of is None):
            raise LoopMapError(f"loop {lp.id} must move exactly one valve or one setpoint")
        if kinds.get(lp.controlled) not in ("measurement", "analyzer"):
            raise LoopMapError(f"loop {lp.id}: {lp.controlled} isn't a measurement in the register")
        if lp.valve is not None and kinds.get(lp.valve) != "valve":
            raise LoopMapError(f"loop {lp.id}: {lp.valve} isn't a valve in the register")
        loops[lp.id] = lp
    valves = [lp.valve for lp in loops.values() if lp.valve]
    if len(set(valves)) != len(valves):
        raise LoopMapError("a valve is moved by more than one loop")
    for lp in loops.values():
        end_valve(loops, lp.id)                  # every cascade resolves to a valve
    return loops


def end_valve(loops, loop_id) -> str:
    """The valve at the bottom of loop_id's cascade. Raises LoopMapError on an unknown
    loop or a cycle."""
    seen = set()
    while True:
        if loop_id not in loops:
            raise LoopMapError(f"unknown loop {loop_id}")
        if loop_id in seen:
            raise LoopMapError(f"cascade cycle through {loop_id}")
        seen.add(loop_id)
        lp = loops[loop_id]
        if lp.valve is not None:
            return lp.valve
        loop_id = lp.setpoint_of


def headroom(position):
    """min(position - 0, 100 - position) in % open, for a number or an array.
    Raises ValueError on NaN or inf, or a position outside 0..100."""
    v = np.asarray(position, dtype=np.float64)
    if not np.isfinite(v).all():
        raise ValueError("a valve position is NaN or inf")
    if ((v < VALVE_MIN) | (v > VALVE_MAX)).any():
        raise ValueError(f"a valve position is outside {VALVE_MIN}..{VALVE_MAX} % open")
    h = np.minimum(v - VALVE_MIN, VALVE_MAX - v)
    return float(h) if h.ndim == 0 else h


def valve_headroom(positions, loops) -> dict:
    """{valve: {"loop", "position_pct", "headroom_pct"}} for every valve a loop moves,
    from positions ({tag: value} as of one sample). Raises ValueError if a valve is
    missing from positions."""
    out = {}
    for lp in loops.values():
        if lp.valve is None:
            continue
        if lp.valve not in positions:
            raise ValueError(f"no position for {lp.valve}")
        v = float(positions[lp.valve])
        out[lp.valve] = {"loop": lp.id, "position_pct": v, "headroom_pct": headroom(v)}
    return out