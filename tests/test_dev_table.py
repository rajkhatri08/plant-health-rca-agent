"""eval/dev_table.py on synthetic runs (never data/): calibrate with the drivers first, then
build the dev table. The run-level tests need Raj's metric functions (divergence, and
decision 60's period_counts, is_chattering, lead_time) and alarms.point_tracks; until
those exist they fail with NotImplementedError."""

import json

import numpy as np
import pytest

import dataset.loader as loader_mod
from dataset.convert import VARIABLES
from dataset.loader import Runs
from eval import calibrate_driver as drv
from eval import dev_table as dt
from eval import metrics, run_record
from ingest import tags as tagmap
from tests.test_calibrate_driver import GAPS, GRID, LAGS, dpca_setup, setup  # noqa: F401 (fixtures)
from tests.test_fit_pca import FAST, two_factor_runs

DEV = range(101, 111)
SAMPLES = 120
N_BOOT = 50


def faulty_dev(normal, fault, first_changed=21):
    """A copy of each normal dev run (its twin) with a step on every fast tag from
    sample first_changed on, larger per fault. Faults 3, 9 and 15 get no step, so those
    runs stay identical to their twins and any detection there is luck."""
    cols = tagmap.column_indices(VARIABLES, FAST)
    runs = {k: v.copy() for k, v in normal.runs.items()}
    if fault not in dt.EXCLUDED:
        for k in runs:
            runs[k][first_changed - 1:, cols] += np.float32(0.4 * fault)
    return Runs(name="faulty_training", fault=fault, pool="dev", columns=VARIABLES, runs=runs)


@pytest.fixture
def calibrated(setup, monkeypatch, tmp_path):
    return calibrate_and_patch(setup, monkeypatch, tmp_path)


@pytest.fixture
def calibrated_dpca(dpca_setup, monkeypatch, tmp_path):
    return calibrate_and_patch(dpca_setup, monkeypatch, tmp_path)


def calibrate_and_patch(setup, monkeypatch, tmp_path):
    """Calibrate the setup's model, then patch the loaders to serve only dev."""
    drv.run(setup["model_path"], setup["out"], repo_root=setup["repo"], q_grid=GRID, gap_range=GAPS)
    normal = two_factor_runs(numbers=DEV, samples=SAMPLES, seed=11)
    calls = []

    def load_normal(pool):
        calls.append(("normal", pool))
        if pool != "dev":
            pytest.fail(f"dev table loaded normal pool {pool}")
        return normal

    def load_faulty(fault, pool):
        calls.append(("faulty", fault, pool))
        if pool != "dev" or fault not in range(1, 16):
            pytest.fail(f"dev table loaded fault {fault} from {pool}")
        return faulty_dev(normal, fault)

    monkeypatch.setattr(loader_mod, "load_normal", load_normal)
    monkeypatch.setattr(loader_mod, "load_faulty", load_faulty)
    return {**setup, "normal": normal, "calls": calls, "tables": tmp_path / "tables"}


def build(c, **kw):
    return dt.run(c["out"], c["model_path"], repo_root=c["repo"], tables_dir=c["tables"],
                  n_boot=N_BOOT, **kw)


def direct_tracks(c, runs):
    lim = json.loads(c["out"].read_text())
    scored = drv.score_runs(c["model"], runs, lags=lim["lags"])
    return drv.tracks(scored, (lim["t2_lim"], lim["spe_lim"]), lim["n"], lim["gap"], lim["warmup"],
                      lim["lags"]), lim


def the_record(c):
    (path,) = (c["repo"] / "eval" / "runs").glob("*_dev_table_*.json")
    return path, json.loads(path.read_text())


# --- Pure pieces: these don't need Raj's stubs. ---

def test_faults_are_the_open_ones_and_the_summary_excludes_3_9_15():
    assert dt.FAULTS == tuple(range(1, 16))
    assert dt.SUMMARY_FAULTS == (1, 2, 4, 5, 6, 7, 8, 10, 11, 12, 13, 14)
    assert set(dt.FAMILIES) == set(dt.SUMMARY_FAULTS)


def test_mean_rate_weights_faults_equally():
    # Fault 1: 3 of 4 runs detected (0.75); fault 2: 1 of 4 (0.25). Mean 0.5.
    hit = {(1, 1): True, (1, 2): True, (1, 3): True, (1, 4): False,
           (2, 1): True, (2, 2): False, (2, 3): False, (2, 4): False}
    out = dt.mean_rate(hit, (1, 2), n_boot=N_BOOT)
    assert out["rate"] == pytest.approx(0.5)
    assert out["faults"] == [1, 2]
    low, high = out["rate_ci95"]
    assert 0 <= low <= high <= 1


def test_mean_rate_refuses_different_run_numbers_per_fault():
    # The joint bootstrap draws one set of numbers for every fault (rule 3).
    hit = {(1, 1): True, (1, 2): True, (2, 1): True, (2, 3): False}
    with pytest.raises(ValueError):
        dt.mean_rate(hit, (1, 2), n_boot=N_BOOT)


def test_mean_rate_refuses_a_missing_fault():
    with pytest.raises(ValueError):
        dt.mean_rate({(1, 1): True}, (1, 2), n_boot=N_BOOT)


def test_mean_rate_every_fault_detected_gives_a_point_interval():
    hit = {(f, k): True for f in (1, 2) for k in range(1, 6)}
    assert dt.mean_rate(hit, (1, 2), n_boot=N_BOOT)["rate_ci95"] == [1.0, 1.0]


def test_normal_row_matches_direct_metric_calls():
    # 120 samples, warm-up 9: 111 scored samples (5.55 h) per run.
    # Run 1: switches on at 12 (before the fake-onset window 21..100) and at 105 (after
    # it): 2 notifications, no chance "detection".
    # Run 2: on at 21..22, inside the window: 1 notification, a chance "detection".
    # So 3 notifications in 11.1 h, and a chance rate of 1 of 2.
    t1 = np.zeros(120, dtype=int); t1[11:13] = 1; t1[104] = 1
    t2 = np.zeros(120, dtype=int); t2[20:22] = 1
    row = dt.normal_row({1: t1, 2: t2}, warmup=9, n_boot=N_BOOT)
    runs = [metrics.ScoredRun(0, 1, t1), metrics.ScoredRun(0, 2, t2)]
    assert (row["notifications"], row["hours"], row["per_24h"]) == pytest.approx(
        metrics.false_alerts_per_24h(runs, 9))
    assert row["notifications"] == 3 and row["hours"] == pytest.approx(11.1)
    assert row["chance_rate"] == 0.5
    assert row["runs"] == 2


def test_render_marks_unbuilt_columns_and_infinite_delays():
    r = {"family": dt.PENDING, "runs": 2, "detected": 0, "rate": 0.0, "rate_ci95": [0.0, 0.0],
         "before_divergence": 0, "before_divergence_of": 0, "delay_median_min": "inf",
         "delay_q1_min": "inf", "delay_q3_min": "inf", "delay_median_ci95": ["inf", "inf"],
         "share_still_flagged": None, "share_still_flagged_runs": 0}
    stored = {"commit": "a" * 40, "dirty": False,
              "config": {"detector": "pca_static", "n": 3, "gap": 15, "q": 95.57, "warmup": 9,
                         "bootstrap": {"resamples": 2000}},
              "seeds": {"bootstrap": dt.BOOTSTRAP_SEED},
              "metrics": {"faults": {f"fault_{f:02d}": r for f in dt.FAULTS},
                          "summary": {"rate": 0.0, "rate_ci95": [0.0, 0.0]},
                          "excluded": {"rate": 0.0, "rate_ci95": [0.0, 0.0]},
                          "normal": {"runs": 2, "notifications": 1, "hours": 9.1, "per_24h": 2.637,
                                     "per_24h_ci95": [0.0, 5.0], "chance_rate": 0.5,
                                     "chance_rate_ci95": [0.0, 1.0]}}}
    text = dt.render(stored, "eval/runs/x_dev_table_pca_static.json")
    rows = [line for line in text.splitlines() if line.startswith("| 1 |")]
    assert len(rows) == 1
    assert "∞ (∞–∞)" in rows[0] and rows[0].count(dt.PENDING) >= 4
    assert "eval/runs/x_dev_table_pca_static.json" in text


# --- The whole run: needs Raj's first_divergence and before_divergence_share. ---

def test_loads_only_dev_each_fault_once(calibrated):
    build(calibrated)
    assert calibrated["calls"] == [("normal", "dev")] + [("faulty", f, "dev") for f in range(1, 16)]


def test_rows_match_direct_metric_calls(calibrated):
    results = build(calibrated)
    for f in (5, 9):
        tracks, lim = direct_tracks(calibrated, faulty_dev(calibrated["normal"], f))
        dets = [metrics.detection(tracks[k], dt.ONSET, warmup=lim["warmup"]) for k in sorted(tracks)]
        row = results["faults"][f"fault_{f:02d}"]
        assert row["runs"] == len(DEV)
        assert row["detected"] == sum(d.detected for d in dets)
        assert row["rate"] == pytest.approx(row["detected"] / len(DEV))
        median, q1, q3 = metrics.delay_summary([d.delay_min for d in dets])
        assert (row["delay_median_min"], row["delay_q1_min"], row["delay_q3_min"]) == (median, q1, q3)
        # Fault 5's runs diverge at sample 21; fault 9's never do.
        before_expected = sum(d.detected and (f == 9 or d.sample < 21) for d in dets)
        assert (row["before_divergence"], row["before_divergence_of"]) == (before_expected, row["detected"])
    tracks, lim = direct_tracks(calibrated, calibrated["normal"])
    runs = [metrics.ScoredRun(0, k, a) for k, a in tracks.items()]
    assert results["normal"]["per_24h"] == pytest.approx(metrics.false_alerts_per_24h(runs, lim["warmup"])[2])
    assert results["normal"]["chance_rate"] == metrics.chance_rate(runs, dt.ONSET, warmup=lim["warmup"])


def test_a_detection_before_divergence_is_counted(calibrated, monkeypatch):
    # Fault 5's runs diverge only from sample 60, so any detection in 21..59 is luck.
    normal = calibrated["normal"]
    monkeypatch.setattr(loader_mod, "load_faulty",
                        lambda fault, pool: faulty_dev(normal, fault, first_changed=60))
    results = build(calibrated)
    tracks, lim = direct_tracks(calibrated, faulty_dev(normal, 5, first_changed=60))
    dets = [metrics.detection(tracks[k], dt.ONSET, warmup=lim["warmup"]) for k in sorted(tracks)]
    row = results["faults"]["fault_05"]
    assert row["before_divergence"] == sum(d.detected and d.sample < 60 for d in dets)


def test_refuses_runs_that_differ_from_their_twins_before_onset(calibrated, monkeypatch):
    normal = calibrated["normal"]
    monkeypatch.setattr(loader_mod, "load_faulty",
                        lambda fault, pool: faulty_dev(normal, fault, first_changed=15))
    with pytest.raises(dt.DevTableError):
        build(calibrated)


def test_record_holds_every_fault_and_no_sealed_ones(calibrated):
    build(calibrated)
    _, rec = the_record(calibrated)
    assert sorted(rec["metrics"]["faults"]) == [f"fault_{f:02d}" for f in range(1, 16)]
    assert rec["config"]["pool"] == "dev" and rec["seeds"] == {"bootstrap": dt.BOOTSTRAP_SEED}
    assert rec["config"]["calibration_record"].endswith("_calibrate_pca.json")
    assert rec["metrics"]["summary"]["faults"] == list(dt.SUMMARY_FAULTS)
    text = json.dumps(rec)
    assert not any(f"fault_{f}" in text for f in range(16, 21))


def test_table_is_rendered_from_the_saved_record(calibrated):
    build(calibrated)
    path, rec = the_record(calibrated)
    (table,) = calibrated["tables"].glob("*_dev_table_*.md")
    assert rec["outputs"]["table"]["sha256"] == run_record.sha256(table)
    rel = path.relative_to(calibrated["repo"]).as_posix()
    assert table.read_text() == dt.render(rec, rel)


def test_same_seed_same_numbers(calibrated):
    first = build(calibrated)
    # Records and tables are never overwritten, and two runs in one second share a name.
    for p in [*(calibrated["repo"] / "eval" / "runs").glob("*_dev_table_*.json"),
              *calibrated["tables"].glob("*.md")]:
        p.unlink()
    assert build(calibrated) == first


def test_refuses_dirty_tree_before_loading(calibrated):
    (calibrated["repo"] / "code.py").write_text("x = 2\n")
    with pytest.raises(run_record.RunRecordError):
        build(calibrated)
    assert calibrated["calls"] == []


def test_refuses_limits_without_a_calibration_record(calibrated):
    lim = json.loads(calibrated["out"].read_text())
    lim["q"] = 50.0
    calibrated["out"].write_text(json.dumps(lim))
    with pytest.raises(drv.CalibrationError):
        build(calibrated)
    assert calibrated["calls"] == []


# ---------------------------------------------------------------------------
# Decision 60: operator load, alarm rows and App 3's lead time.

from eval import calibrate_alarms as ca                     # noqa: E402
from eval.baselines import alarms as al                     # noqa: E402
from tests import test_calibrate_alarms as tca              # noqa: E402


def det(sample):
    if sample is None:
        return metrics.Detection(False, None, metrics.INF)
    return metrics.Detection(True, sample, float((sample - 20) * 3))


def test_operator_load_by_hand():
    # Run 1: point 0 turns on at 21, 23, 25 (25 - 21 = 4 <= 9: chattering); point 1 at 50.
    #        In the window 21..60: 4 notifications. Minutes after onset 20: 3, 9, 15, 90,
    #        so periods [2, 1, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0].
    # Run 2: point 1 at 5 and 61, both outside the window: 0 notifications.
    # Per episode: mean (4 + 0) / 2 = 2.0, max 4. Per 10 min: 4 / 24 periods. Peak 2.
    # Chattering points per run: (1 + 0) / 2. Share from chattering: 3 of 4.
    load = dt.operator_load({1: [[21, 23, 25], [50]], 2: [[], [5, 61]]})
    assert load == pytest.approx({"per_episode_mean": 2.0, "per_episode_max": 4,
                                  "per_10min_mean": 4 / 24, "peak_10min": 2, "flood_share": 0.0,
                                  "chattering_points_per_run": 0.5, "chattering_share": 0.75})


def test_operator_load_flood_and_no_notifications():
    # 11 points each turning on at sample 21 (3 min): 11 > 10 in period 0, a flood.
    load = dt.operator_load({1: [[21]] * 11})
    assert load["flood_share"] == pytest.approx(1 / 12) and load["peak_10min"] == 11
    assert dt.operator_load({1: [[]], 2: [[5]]})["chattering_share"] is None


def test_lead_row_by_hand():
    # Runs 1-2 both detected: 15 - 9 = 6 and 12 - 12 = 0, median 3; run 3 only alarms;
    # run 4 only App 3; run 5 neither.
    app = {1: det(23), 2: det(24), 3: det(None), 4: det(30), 5: det(None)}
    base = {1: det(25), 2: det(24), 3: det(27), 4: det(None), 5: det(None)}
    row = dt.lead_row(5, app, base, n_boot=N_BOOT)
    assert (row["median_min"], row["both"], row["only_app"], row["only_base"], row["neither"]) == (3.0, 2, 1, 1, 1)
    assert 0.0 <= row["median_ci95"][0] <= row["median_ci95"][1] <= 6.0


def test_lead_row_without_both_detected():
    row = dt.lead_row(5, {1: det(23)}, {1: det(None)}, n_boot=N_BOOT)
    assert row["median_min"] is None and row["median_ci95"] is None and row["only_app"] == 1


@pytest.fixture
def with_alarms(calibrated, monkeypatch, tmp_path):
    """Both alarm lists calibrated on synthetic plant-like runs, then dev loaders serving
    plant-like dev runs (valves near 50% open)."""
    calib = tca.plant_runs(range(1, 21))
    monkeypatch.setattr(loader_mod, "load_normal", lambda pool: calib if pool == "calibration" else pytest.fail(pool))
    monkeypatch.setattr(loader_mod, "load_faulty", lambda f, pool: tca.plant_runs(
        range(1, 13), seed=100 + f, step=1.0 + 0.3 * f, fault=f, pool="forest_ceiling"))
    paths = {}
    for name in ("realistic", "every"):
        paths[name] = tmp_path / "alarms" / f"alarms_{name}_limits.json"
        ca.run(name, paths[name], repo_root=calibrated["repo"], warmup=tca.WARMUP,
               q_grid=tca.GRID, gap_range=tca.GAPS)

    normal = tca.plant_runs(DEV, seed=11, pool="dev")
    calls = []

    def load_normal(pool):
        calls.append(("normal", pool))
        if pool != "dev":
            pytest.fail(f"dev table loaded normal pool {pool}")
        return normal

    def load_faulty(fault, pool):
        calls.append(("faulty", fault, pool))
        if pool != "dev" or fault not in range(1, 16):
            pytest.fail(f"dev table loaded fault {fault} from {pool}")
        return faulty_dev(normal, fault)

    monkeypatch.setattr(loader_mod, "load_normal", load_normal)
    monkeypatch.setattr(loader_mod, "load_faulty", load_faulty)
    return {**calibrated, "normal": normal, "calls": calls, "alarms": paths}


def direct_alarm(limits_path, row, runs):
    """{run: (alert track, per-point notifications)} built straight from alarms.py."""
    lim = json.loads(limits_path.read_text())
    r = lim[row]
    hl = [al.ANALYZER_ON_DELAY if a else r["n"] for a in lim["hl_analyzer"]]
    ns = hl + hl + [r["n"]] * len(lim["valve_tags"])
    hl_cols = tagmap.column_indices(VARIABLES, lim["hl_tags"])
    v_cols = tagmap.column_indices(VARIABLES, lim["valve_tags"]) if lim["valve_tags"] else []
    out = {}
    for k, x in runs.runs.items():
        high, low = al.hysteresis(x[:, hl_cols], r["lo"], r["hi"], lim["band"])
        pts = np.hstack([high, low] + ([al.at_limit(x[:, v_cols])] if v_cols else []))
        per_point = al.point_tracks(pts, ns, r["gap"], lim["warmup"])
        out[k] = (al.plant_track(pts, ns, r["gap"], lim["warmup"]),
                  [metrics.notifications(per_point[:, j], lim["warmup"]) for j in range(per_point.shape[1])])
    return out


def build_alarm(c, name="realistic", row="grouped", **kw):
    return dt.run(c["alarms"][name], None, row=row, repo_root=c["repo"], tables_dir=c["tables"],
                  n_boot=N_BOOT, **kw)


@pytest.mark.parametrize("name, row", [("realistic", "grouped"), ("every", "ungrouped")])
def test_alarm_row_matches_direct_scoring(with_alarms, name, row):
    results = build_alarm(with_alarms, name, row)
    lim = json.loads(with_alarms["alarms"][name].read_text())
    for f in (5, 9):
        scored = direct_alarm(with_alarms["alarms"][name], row, faulty_dev(with_alarms["normal"], f))
        dets = [metrics.detection(scored[k][0], dt.ONSET, warmup=lim["warmup"]) for k in sorted(scored)]
        r = results["faults"][f"fault_{f:02d}"]
        assert r["detected"] == sum(d.detected for d in dets)
        assert r["delay_median_min"] == metrics.delay_summary([d.delay_min for d in dets])[0]
        assert r["load"] == pytest.approx(dt.operator_load({k: p for k, (_, p) in scored.items()}))
    _, rec = the_record(with_alarms)
    assert rec["name"] == f"dev_table_alarms_{name}_{row}"
    assert rec["config"]["row"] == row and rec["config"]["calibration_record"].endswith(
        f"_calibrate_alarms_{name}.json")
    assert "lead_vs" not in rec["config"]


def test_app3_lead_time_matches_direct(with_alarms):
    results = build(with_alarms, lead_vs=with_alarms["alarms"]["realistic"])
    for f in (5, 13):
        runs = faulty_dev(with_alarms["normal"], f)
        app_tracks, lim = direct_tracks(with_alarms, runs)
        base = direct_alarm(with_alarms["alarms"]["realistic"], "grouped", runs)
        ks = sorted(app_tracks)
        lt = metrics.lead_time([metrics.detection(app_tracks[k], dt.ONSET, warmup=lim["warmup"]) for k in ks],
                               [metrics.detection(base[k][0], dt.ONSET, warmup=lim["warmup"]) for k in ks])
        lead = results["faults"][f"fault_{f:02d}"]["lead"]
        assert (lead["median_min"], lead["both"], lead["only_app"], lead["only_base"], lead["neither"]) == tuple(lt)
        # App 3's operator load counts its one plant stream.
        assert results["faults"][f"fault_{f:02d}"]["load"] == pytest.approx(dt.operator_load(
            {k: [metrics.notifications(app_tracks[k], lim["warmup"])] for k in ks}))
    _, rec = the_record(with_alarms)
    assert rec["config"]["lead_vs"]["detector"] == "alarms_realistic_grouped"
    table = next(with_alarms["tables"].glob("*.md")).read_text()
    assert "only App 3" in table and "Operator load" in table


@pytest.mark.parametrize("kw", [
    {"row": None},                               # an alarm file needs a row
    {"row": "both"},                             # not a row
])
def test_alarm_detector_needs_a_valid_row_before_loading(with_alarms, kw):
    with pytest.raises(dt.DevTableError):
        dt.run(with_alarms["alarms"]["realistic"], None, repo_root=with_alarms["repo"],
               tables_dir=with_alarms["tables"], n_boot=N_BOOT, **kw)
    assert with_alarms["calls"] == []


def test_refusals_before_loading(with_alarms):
    c = with_alarms
    with pytest.raises(dt.DevTableError):                       # PCA takes no row
        build(c, row="grouped")
    with pytest.raises(dt.DevTableError):                       # lead is against realistic only
        build(c, lead_vs=c["alarms"]["every"])
    with pytest.raises(dt.DevTableError):                       # an alarm row has no lead column
        build_alarm(c, lead_vs=c["alarms"]["realistic"])
    doc = json.loads(c["alarms"]["realistic"].read_text())
    doc["grouped"]["q"] = 1.0
    c["alarms"]["realistic"].write_text(json.dumps(doc))        # no longer the recorded file
    with pytest.raises(dt.DevTableError):
        build_alarm(c)
    assert c["calls"] == []


def test_main_routes_lead_time(monkeypatch):
    seen = []
    monkeypatch.setattr(dt, "run", lambda limits, model, **kw: seen.append((limits, kw["row"], kw["lead_vs"])))
    assert dt.main([]) == 0
    assert dt.main(["--no-lead"]) == 0
    assert dt.main(["--limits", "a.json", "--row", "grouped"]) == 0
    assert dt.main(["--lead-vs", "b.json"]) == 0
    assert seen == [(drv.DEFAULT_OUT, None, dt.DEFAULT_LEAD), (drv.DEFAULT_OUT, None, None),
                    (dt.Path("a.json"), "grouped", None), (drv.DEFAULT_OUT, None, dt.Path("b.json"))]


# ---------------------------------------------------------------------------
# Decision 62: the Masked column comes from a masked_faults record.

from app.detector import loops as loop_map_mod              # noqa: E402


def write_masked(c, masked=(5,), sha=None, rule="plant", name="20260928T000000Z_masked_faults.json"):
    faults = {f"fault_{f:02d}": {"masked": f in masked, "masked_share": 1.0 if f in masked else 0.0,
                                 "absorbing_valves": "CD-FV-302" if f in masked else None,
                                 "absorbing_loops": "ST-FIC-603", "valve_shares": {}, "loop_shares": {}}
              for f in range(1, 16)}
    config = {"loop_map_sha256": sha or run_record.sha256(loop_map_mod.LOOPS_FILE)}
    if rule:
        config["rule"] = rule
    rec = {"config": config,
           "metrics": {"masked_faults": list(masked), "faults": faults}}
    path = c["repo"] / "eval" / "runs" / name
    path.write_text(json.dumps(rec))
    return path


def test_masked_column_from_a_record(calibrated):
    path = write_masked(calibrated)
    results = build(calibrated, masked=path)
    assert results["faults"]["fault_05"]["masked"] == {"masked": True, "valves": "CD-FV-302"}
    assert results["faults"]["fault_04"]["masked"] == {"masked": False, "valves": None}
    rec_path, rec = the_record(calibrated)
    assert rec["config"]["masked_record"] == "eval/runs/20260928T000000Z_masked_faults.json"
    table = next(calibrated["tables"].glob("*.md")).read_text()
    assert "| 5 | condenser cooling | yes (CD-FV-302) |" in table
    assert "| 4 | reactor cooling | no |" in table


@pytest.mark.parametrize("kw", [{"sha": "0" * 64}, {"name": "20260928T000000Z_other.json"},
                                {"rule": None}])            # the superseded any-loop record
def test_masked_record_refusals_before_loading(calibrated, kw):
    path = write_masked(calibrated, **kw)
    with pytest.raises(dt.DevTableError):
        build(calibrated, masked=path)
    assert calibrated["calls"] == []


# --- DPCA row (decision 63) ----------------------------------------------------------

def test_dpca_rows_match_direct_scoring(calibrated_dpca):
    c = calibrated_dpca
    results = build(c)
    for f in (5, 9):
        tracks, lim = direct_tracks(c, faulty_dev(c["normal"], f))
        assert lim["lags"] == LAGS
        dets = [metrics.detection(tracks[k], dt.ONSET, warmup=lim["warmup"]) for k in sorted(tracks)]
        row = results["faults"][f"fault_{f:02d}"]
        assert row["detected"] == sum(d.detected for d in dets)
        median, q1, q3 = metrics.delay_summary([d.delay_min for d in dets])
        assert (row["delay_median_min"], row["delay_q1_min"], row["delay_q3_min"]) == (median, q1, q3)
        # Divergence is on the plant tags the model reads (the lag-0 block): fault 5's runs
        # diverge at sample 21, fault 9's never do.
        before_expected = sum(d.detected and (f == 9 or d.sample < 21) for d in dets)
        assert (row["before_divergence"], row["before_divergence_of"]) == (before_expected, row["detected"])
    tracks, lim = direct_tracks(c, c["normal"])
    runs = [metrics.ScoredRun(0, k, a) for k, a in tracks.items()]
    assert results["normal"]["per_24h"] == pytest.approx(metrics.false_alerts_per_24h(runs, lim["warmup"])[2])


def test_dpca_record_and_table_name_the_lags(calibrated_dpca):
    build(calibrated_dpca)
    _, rec = the_record(calibrated_dpca)
    assert rec["config"]["detector"] == "pca_dynamic" and rec["config"]["lags"] == LAGS
    (table,) = calibrated_dpca["tables"].glob("*_dev_table_pca_dynamic.md")
    assert f"L = {LAGS} lags" in table.read_text()
    assert "equals static PCA" not in table.read_text()


@pytest.mark.parametrize("detector, lags, note", [
    ("pca_static", 0, ""),
    ("alarms_realistic_grouped", 0, ""),
    ("pca_dynamic", 3, ", L = 3 lags"),
    ("pca_dynamic", 0, ", L = 0 lags (L = 0: DPCA equals static PCA)"),
])
def test_lags_note(detector, lags, note):
    assert dt._lags_note({"detector": detector, "lags": lags}) == note
