"""app/detector/replay.py: one engine, as-of, and Unknown never reads as Normal."""

from datetime import timedelta

import numpy as np
import pytest

from app.detector import alerting, pca, replay
from app.detector import bundle as bm
from dataset.convert import VARIABLES
from eval import calibrate_driver as drv
from ingest import export_replay
from ingest import tags as tagmap
from tests.replay_helpers import make_bundle, stream_run, write_csv
from tests.test_fit_pca import FAST

COLS = tagmap.column_indices(VARIABLES, FAST)


@pytest.fixture
def b(tmp_path):
    return bm.load(make_bundle(tmp_path / "pca_v1"))


@pytest.fixture
def run_values():
    return stream_run()[0]


def stream(tmp_path, values, rows_filter=None):
    return replay.read_csv(write_csv(tmp_path / "run.csv", values, VARIABLES, rows_filter), FAST)


def ts_of(sample):
    return export_replay.START + (sample - 1) * export_replay.STEP


END = ts_of(10_000)
RATIO_REL = 1e-12       # ratios agree to about 12 significant digits


def assert_same_rows(got, want):
    """Same samples, bands and reasons exactly; ratios to RATIO_REL.

    Matrix products can round the last digit differently for different batch sizes
    (for example OpenBLAS on Linux against Accelerate on macOS), so an exact float
    comparison between two scorings isn't portable. The bands must still match exactly.
    """
    key = lambda r: (r["ts"], r["band"], r["reason"])
    assert [key(r) for r in got] == [key(r) for r in want]
    for g, w in zip(got, want):
        if w["ratio"] is None:
            assert g["ratio"] is None
        else:
            assert g["ratio"] == pytest.approx(w["ratio"], rel=RATIO_REL)


def test_csv_round_trips_float32_exactly(tmp_path, run_values):
    s = stream(tmp_path, run_values)
    assert s.tags == tuple(FAST) and len(s.ts) == len(run_values)
    assert np.array_equal(s.values, run_values[:, COLS].astype(np.float64))
    assert s.ts[1] - s.ts[0] == timedelta(minutes=3)


def test_one_engine_bands_equal_the_evaluation_tracks(tmp_path, b, run_values):
    # The calibration driver's alert track for this run, from the raw float32 array.
    from dataset.loader import Runs
    runs = Runs("faulty_training", 13, "dev", VARIABLES, {1: run_values})
    lim = b.limits
    scored = drv.score_runs(b.model, runs)
    track = drv.tracks(scored, (lim["t2_lim"], lim["spe_lim"]), lim["n"], lim["gap"], lim["warmup"])[1]
    t2, spe = scored[1]
    ratio = alerting.plant_ratio(t2, spe, lim["t2_lim"], lim["spe_lim"])

    rows = replay.status(b, stream(tmp_path, run_values), END)
    w = lim["warmup"]
    assert [r["band"] for r in rows[w:]] == ["Alert" if a else "Normal" for a in track[w:]]
    assert [r["ratio"] for r in rows[w:]] == pytest.approx(ratio[w:].tolist(), rel=RATIO_REL)
    # Not a vacuous match: the run is Normal before the step and alerts after it.
    assert {r["band"] for r in rows[w:29]} == {"Normal"}
    assert "Alert" in {r["band"] for r in rows[29:]}
    assert track[:w].tolist() == [0] * w


def test_warmup_is_unknown_with_no_ratio(tmp_path, b, run_values):
    rows = replay.status(b, stream(tmp_path, run_values), END)
    for r in rows[:3]:
        assert r == {"ts": r["ts"], "band": "Unknown", "ratio": None, "reason": "warm-up"}
    assert all(r["band"] in ("Normal", "Alert") for r in rows[3:])


def test_as_of_is_a_prefix_of_the_full_replay(tmp_path, b, run_values):
    s = stream(tmp_path, run_values)
    full = replay.status(b, s, END)
    for k in range(0, len(run_values) + 1, 7):
        upto = ts_of(k) if k else ts_of(1) - timedelta(minutes=1)
        assert_same_rows(replay.status(b, s, upto), full[:k])


def test_as_of_between_samples(tmp_path, b, run_values):
    s = stream(tmp_path, run_values)
    assert len(replay.status(b, s, ts_of(10) + timedelta(minutes=2))) == 10


def drop(sample, tag=None):
    def f(rows):
        ts = ts_of(sample).strftime(export_replay.TS_FORMAT)
        return [r for r in rows if not (r[0] == ts and (tag is None or r[1] == tag))]
    return f


def bad_quality(sample, tag):
    def f(rows):
        ts = ts_of(sample).strftime(export_replay.TS_FORMAT)
        return [(r[0], r[1], r[2], "bad") if (r[0] == ts and r[1] == tag) else r for r in rows]
    return f


@pytest.mark.parametrize("edit, first_unknown", [
    (drop(40, FAST[5]), 40),                   # one tag missing at sample 40
    (bad_quality(40, FAST[0]), 40),            # one tag with bad quality at 40
    (drop(40), 40),                            # sample 40 missing: 41 follows 39 by 6 min
])
def test_bad_data_is_unknown_from_there_on_and_earlier_is_unchanged(tmp_path, b, run_values,
                                                                    edit, first_unknown):
    full = replay.status(b, stream(tmp_path, run_values), END)
    (tmp_path / "run.csv").unlink()
    rows = replay.status(b, stream(tmp_path, run_values, edit), END)
    before = [r for r in rows if r["ts"] < ts_of(first_unknown).strftime(export_replay.TS_FORMAT)]
    after = [r for r in rows if r["ts"] >= ts_of(first_unknown).strftime(export_replay.TS_FORMAT)]
    assert_same_rows(before, full[:first_unknown - 1])
    assert after and all(r == {"ts": r["ts"], "band": "Unknown", "ratio": None, "reason": "data"}
                         for r in after)


def test_non_finite_value_is_unknown(tmp_path, b, run_values):
    def f(rows):
        return [(r[0], r[1], "nan", r[3]) if i == 20 * 33 else r for i, r in enumerate(rows)]
    rows = replay.status(b, stream(tmp_path, run_values, f), END)
    assert rows[20]["band"] == "Unknown" and rows[20]["reason"] == "data"


def test_other_tags_are_ignored(tmp_path, b, run_values):
    # An analyzer row isn't a fast tag: the stream and the bands are unchanged.
    plain = replay.status(b, stream(tmp_path, run_values), END)
    (tmp_path / "run.csv").unlink()
    extra = stream(tmp_path, run_values, lambda rows: rows + [(rows[0][0], "RX-AI-211", "1.5", "good")])
    assert_same_rows(replay.status(b, extra, END), plain)


@pytest.mark.parametrize("text", [
    "time,tag,value,quality\n",                                         # wrong header
    "ts,tag,value,quality\n2026-01-05 06:00:00,FD-FI-101,1.0,good\n",   # bad timestamp
    "ts,tag,value,quality\n2026-01-05T06:00:00Z,FD-FI-101,abc,good\n",  # bad value
    "ts,tag,value,quality\n2026-01-05T06:00:00Z,FD-FI-101,1.0\n",       # 3 fields
    "ts,tag,value,quality\n2026-01-05T06:00:00Z,FD-FI-101,1.0,good\n"
    "2026-01-05T06:00:00Z,FD-FI-101,2.0,bad\n",                         # repeated (ts, tag)
])
def test_malformed_csv_is_refused(tmp_path, text):
    path = tmp_path / "run.csv"
    path.write_text(text)
    with pytest.raises(replay.ReplayError):
        replay.read_csv(path, FAST)


def test_stream_and_model_tags_must_match(tmp_path, b, run_values):
    write_csv(tmp_path / "run.csv", run_values, VARIABLES)
    s = replay.read_csv(tmp_path / "run.csv", tuple(reversed(FAST)))
    with pytest.raises(replay.ReplayError):
        replay.status(b, s, END)


def test_scoring_matches_pca_scores(tmp_path, b, run_values):
    rows = replay.status(b, stream(tmp_path, run_values), END)
    t2, spe = pca.scores(b.model, run_values[:, COLS])
    lim = b.limits
    expected = np.maximum(t2 / lim["t2_lim"], spe / lim["spe_lim"])
    assert [r["ratio"] for r in rows[3:]] == pytest.approx(expected[3:].tolist(), rel=RATIO_REL)


# ---------- a bundle with Watch boundaries (pca_v2, decisions 64-66) ----------

from app.detector import rbc  # noqa: E402
from eval import calibrate_watch as cw  # noqa: E402
from eval import metrics  # noqa: E402
from tests.replay_helpers import add_watch  # noqa: E402


@pytest.fixture
def b2(tmp_path):
    # p = 90 on 10 runs, so the Watch band shows up in a 60-sample stream (the real one
    # comes from the calibration, decision 66).
    return bm.load(add_watch(make_bundle(tmp_path / "pca_v2"), p=90.0))


def evaluation_path(b, run_values):
    """What evaluation computes for this run: the alert track (calibration driver), the
    group ratios (calibrate_watch.rbc_runs, the Watch calibration's path, over W_g) and
    the attributed group at each notification (rank_at, as the dev table does)."""
    from dataset.loader import Runs
    runs = Runs("faulty_training", 13, "dev", VARIABLES, {1: run_values})
    lim = b.limits
    scored = drv.score_runs(b.model, runs)
    track = drv.tracks(scored, (lim["t2_lim"], lim["spe_lim"]), lim["n"], lim["gap"], lim["warmup"])[1]
    names = list(b.watch["groups"])
    by_group, _ = cw.rbc_runs(b.model, lim, runs, names)
    ratios = by_group[1] / np.array([b.watch["groups"][g]["w"] for g in names])
    top = {t: names[rbc.rank_at(ratios, t, lim["n"])[1][0]]
           for t in metrics.notifications(track, lim["warmup"])}
    return track, ratios, names, top


def test_parity_with_the_evaluation_path(tmp_path, b2, run_values):
    track, ratios, names, top = evaluation_path(b2, run_values)
    rows = replay.status(b2, stream(tmp_path, run_values), END)
    w = b2.limits["warmup"]
    for i, r in enumerate(rows[w:], start=w):
        assert list(r["groups"]) == names
        assert [r["groups"][g]["ratio"] for g in names] == pytest.approx(ratios[i].tolist(), rel=RATIO_REL)
        assert [r["groups"][g]["band"] for g in names] == ["Watch" if x > 1 else "Normal" for x in ratios[i]]
        expected = "Alert" if track[i] else ("Watch" if (ratios[i] > 1).any() else "Normal")
        assert r["band"] == expected
    for t, g in top.items():
        assert rows[t - 1]["attributed"] == g
    # Not vacuous: Watch appears before the step, and an alert is attributed after it.
    assert "Watch" in {r["band"] for r in rows[w:29]}
    assert top and all(rows[t - 1]["band"] == "Alert" for t in top)


def test_attributed_only_during_an_alert_and_held_for_the_episode(tmp_path, b2, run_values):
    rows = replay.status(b2, stream(tmp_path, run_values), END)
    for prev, r in zip(rows, rows[1:]):
        if r["band"] != "Alert":
            assert r["attributed"] is None
        elif prev["band"] == "Alert":
            assert r["attributed"] == prev["attributed"]
        else:
            assert r["attributed"] is not None


def test_v2_unknown_rows_have_no_groups(tmp_path, b2, run_values):
    rows = replay.status(b2, stream(tmp_path, run_values, drop(40)), END)
    for r in rows[:3] + rows[39:]:
        assert r["band"] == "Unknown" and r["groups"] is None and r["attributed"] is None


def test_v2_as_of_is_a_prefix(tmp_path, b2, run_values):
    s = stream(tmp_path, run_values)
    full = replay.status(b2, s, END)
    for k in range(0, len(run_values) + 1, 7):
        upto = ts_of(k) if k else ts_of(1) - timedelta(minutes=1)
        part = replay.status(b2, s, upto)
        assert_same_rows(part, full[:k])
        assert [r["attributed"] for r in part] == [r["attributed"] for r in full[:k]]
        for p_, f_ in zip(part, full[:k]):
            if f_["groups"] is None:
                assert p_["groups"] is None
            else:
                assert {g: v["band"] for g, v in p_["groups"].items()} == \
                       {g: v["band"] for g, v in f_["groups"].items()}


def test_v1_rows_are_unchanged(tmp_path, b, run_values):
    rows = replay.status(b, stream(tmp_path, run_values), END)
    assert all(set(r) == {"ts", "band", "ratio", "reason"} for r in rows)
    assert "Watch" not in {r["band"] for r in rows}
