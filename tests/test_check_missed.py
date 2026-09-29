"""eval/check_missed.py: hand-built tracks for the per-run detail, then the driver on
dev_table's synthetic runs (never data/), checked against direct scoring."""

import json

import numpy as np
import pytest

from eval import check_missed as cm
from eval import dev_table as dt
from eval import metrics
from tests.test_calibrate_driver import setup  # noqa: F401 (fixture)
from tests.test_dev_table import (calibrated, direct_alarm, direct_tracks,  # noqa: F401 (fixtures)
                                  faulty_dev, with_alarms)

WARMUP = 9
T = 120


def track(*spans):
    """A whole-run 0/1 track, on over each inclusive 1-based (first, last) span."""
    a = np.zeros(T, dtype=np.int8)
    for first, last in spans:
        a[first - 1:last] = 1
    return a


# ---------- one missed run ----------

def test_alert_bridging_onset_is_on_at_onset():
    # A false alert turns on at 15 and, held by grouping, stays on through the fault:
    # no switch-on in 21..100, so it's a miss. The twin shares samples 1-20.
    d = cm.missed_detail(track((15, T)), track((15, 30)), WARMUP)
    assert d == {"cause": cm.ON_AT_ONSET, "on_at_onset": True,
                 "last_notification_before_onset": 15, "on_through_window": True,
                 "first_notification_after_onset": None,
                 "twin_notifications_pre_onset": [15], "twin_track_equal_to_onset": True}
    assert not metrics.detection(track((15, T)), dt.ONSET, warmup=WARMUP).detected


def test_on_at_onset_then_off_for_the_window():
    d = cm.missed_detail(track((12, 25)), track((12, 25)), WARMUP)
    assert d["cause"] == cm.ON_AT_ONSET and not d["on_through_window"]
    assert d["last_notification_before_onset"] == 12 and d["first_notification_after_onset"] is None


def test_no_alert_in_window_and_a_late_one():
    d = cm.missed_detail(track((105, 110)), track(), WARMUP)
    assert d["cause"] == cm.NO_ALERT and not d["on_at_onset"]
    assert d["last_notification_before_onset"] is None
    assert d["first_notification_after_onset"] == 105                 # after the window
    assert d["twin_notifications_pre_onset"] == [] and d["twin_track_equal_to_onset"]


def test_alert_cleared_before_onset_is_not_on_at_onset():
    # On at 12-19, off at 20: the fault's switch-on at 22 is a detection, so this
    # run wouldn't be missed; the detail still reads the onset sample correctly.
    a = track((12, 19), (22, 40))
    assert metrics.detection(a, dt.ONSET, warmup=WARMUP).detected
    assert not cm.missed_detail(a, a, WARMUP)["on_at_onset"]


def test_warmup_alert_counts_at_the_first_scored_sample():
    d = cm.missed_detail(track((1, T)), track((1, T)), WARMUP)
    assert d["last_notification_before_onset"] == WARMUP + 1 and d["twin_notifications_pre_onset"] == [10]


def test_twin_differing_before_onset_is_flagged():
    assert not cm.missed_detail(track((15, T)), track(), WARMUP)["twin_track_equal_to_onset"]


# ---------- the summary ----------

def detail(on):
    return {"on_at_onset": on, "cause": cm.ON_AT_ONSET if on else cm.NO_ALERT}


def faults_with(only, on=True, excluded=None):
    """only maps a summary fault to its only-alarms run numbers."""
    rows = {f"fault_{f:02d}": {"missed": [], "only_alarms": [], "missed_runs": {}} for f in dt.FAULTS}
    for f, ks in only.items():
        rows[f"fault_{f:02d}"].update(missed=ks, only_alarms=ks,
                                      missed_runs={f"run_{k}": detail(on) for k in ks})
    for f, ks in (excluded or {}).items():
        rows[f"fault_{f:02d}"].update(missed=ks, only_alarms=ks)
    return rows


def test_summary_one_run_on_at_onset_holds():
    s = cm.summarise(faults_with({1: [107], 4: [107], 14: [107]}, excluded={3: [101, 102]}))
    assert s == {"only_alarms_runs": 3, "only_alarms_faults": [1, 4, 14],
                 "only_alarms_run_numbers": [107], "same_run_everywhere": True,
                 "all_on_at_onset": True, "hypothesis_holds": True}


def test_summary_fails_with_two_runs_or_off_at_onset():
    assert not cm.summarise(faults_with({1: [107], 4: [108]}))["hypothesis_holds"]
    s = cm.summarise(faults_with({1: [107], 4: [107]}, on=False))
    assert s["same_run_everywhere"] and not s["all_on_at_onset"] and not s["hypothesis_holds"]


def test_summary_with_no_only_alarms_runs():
    s = cm.summarise(faults_with({}))
    assert s["only_alarms_run_numbers"] == [] and not s["hypothesis_holds"]


# ---------- the driver ----------

def check(c, **kw):
    return cm.run(c["out"], c["model_path"], lead_vs=c["alarms"]["realistic"], repo_root=c["repo"], **kw)


def the_record(c):
    (path,) = (c["repo"] / "eval" / "runs").glob("*_check_missed_*.json")
    return json.loads(path.read_text())


def test_matches_direct_scoring(with_alarms):
    faults, summary = check(with_alarms)
    normal = with_alarms["normal"]
    twin_tracks, lim = direct_tracks(with_alarms, normal)
    for f in dt.FAULTS:
        runs = faulty_dev(normal, f)
        tracks, _ = direct_tracks(with_alarms, runs)
        base = direct_alarm(with_alarms["alarms"]["realistic"], "grouped", runs)
        missed = [k for k in sorted(tracks)
                  if not metrics.detection(tracks[k], dt.ONSET, warmup=lim["warmup"]).detected]
        only = [k for k in missed if metrics.detection(base[k][0], dt.ONSET, warmup=lim["warmup"]).detected]
        row = faults[f"fault_{f:02d}"]
        assert row["missed"] == missed and row["only_alarms"] == only and row["runs"] == len(tracks)
        if f in dt.SUMMARY_FAULTS:
            assert row["missed_runs"] == {f"run_{k}": cm.missed_detail(tracks[k], twin_tracks[k], lim["warmup"])
                                          for k in missed}
        else:
            assert "missed_runs" not in row
    assert summary == cm.summarise(faults)
    rec = the_record(with_alarms)
    assert rec["name"] == "check_missed_pca_static" and rec["metrics"]["summary"] == summary
    assert rec["config"]["alarms"]["detector"] == "alarms_realistic_grouped"


def test_loads_only_dev(with_alarms):
    check(with_alarms)
    pools = {c[-1] for c in with_alarms["calls"]}
    assert pools == {"dev"}
    assert sorted(c[1] for c in with_alarms["calls"] if c[0] == "faulty") == list(dt.FAULTS)


def test_refuses_an_alarm_row_as_app3(with_alarms):
    with pytest.raises(dt.DevTableError):
        cm.run(with_alarms["alarms"]["realistic"], None, lead_vs=with_alarms["alarms"]["realistic"],
               repo_root=with_alarms["repo"])
    assert not with_alarms["calls"]


def test_refuses_the_every_tag_list(with_alarms):
    with pytest.raises(dt.DevTableError, match="realistic"):
        cm.run(with_alarms["out"], with_alarms["model_path"], lead_vs=with_alarms["alarms"]["every"],
               repo_root=with_alarms["repo"])
    assert not with_alarms["calls"]


def test_refuses_dirty_tree_before_loading(with_alarms):
    (with_alarms["repo"] / "code.py").write_text("x = 2\n")
    with pytest.raises(cm.run_record.RunRecordError, match="dirty"):
        check(with_alarms)
    assert not with_alarms["calls"]
