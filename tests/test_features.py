"""app/detector/features.py: decision 68's vocabulary on hand-built cases."""

import numpy as np
import pytest

from app.detector import bundle, features

FAST = bundle.fast_tags()
LO, HI = 0.0, 1.0


# ---------- tags (F1-A) ----------

@pytest.mark.parametrize("x, expected", [
    ([0.5] * 8, "normal"),
    ([0.0, 1.0, 1.0, 0.0, 1.0, 1.0], "normal"),                 # the edges count as inside
    ([0.5, 2, 2, 0.5, 2, 2, 0.5], "normal"),                    # 2 in a row isn't out
    ([0.5, 2, 2, 2, 0.5], "high"),
    ([0.5, -1, -1, -1, 0.5], "low"),
    ([2, 2, 2, 0.5, -1, -1, -1], "both"),                       # a run on each side
    ([0.5, 2, 2, -1, 0.5], "both"),                             # one run crossing sides (decision 62: out)
    ([2, 2, 2, 0.5, 2, 2, 2], "high"),
])
def test_tag_state(x, expected):
    assert features.tag_state(x, LO, HI) == expected


def test_tag_state_refuses_a_gap():
    with pytest.raises(features.FeatureError):
        features.tag_state([0.5, np.nan, 0.5], LO, HI)


# ---------- analyzers (F5-A) ----------

@pytest.mark.parametrize("values, expected", [
    ([], "not_yet_available"),
    ([5.0], "not_yet_available"),                               # fewer than 2 published
    ([0.5, 0.5], "normal"),
    ([2, 2], "high"),
    ([0.5, -1, -1], "low"),
    ([2, 0.5, 2, 0.5], "normal"),                               # never 2 in a row
    ([2, 2, 0.5, -1, -1], "low"),                               # both qualify: the most recent decides
    ([-1, -1, 2, 2, 0.5], "high"),
])
def test_analyzer_state(values, expected):
    assert features.analyzer_state(values, LO, HI) == expected


# ---------- loops (F4-A) ----------

M_BAND, V_BAND = (0.0, 1.0), (40.0, 60.0)
IN_M, IN_V = [0.5] * 5, [50.0] * 5


@pytest.mark.parametrize("meas, valve, expected", [
    (IN_M, IN_V, "held"),
    (IN_M, [70.0] * 5, "compensating"),                         # measurement held, valve out
    ([2.0] * 5, [70.0] * 5, "lost"),                            # measurement out
    ([2.0] * 5, [99.0] * 5, "saturated"),                       # at the limit beats lost
    (IN_M, [1.0] * 5, "saturated"),
    (IN_M, [50, 98.0, 98.0, 98.0, 50], "saturated"),            # 98 counts as at the limit
    (IN_M, [50, 99.0, 99.0, 50, 50], "held"),                   # 2 samples at the limit (and out): neither
])
def test_loop_state(meas, valve, expected):
    assert features.loop_state(meas, valve, M_BAND, V_BAND) == expected


# ---------- held series ----------

def test_held_series_holds_and_never_interpolates():
    got = features.held_series([(2, 1.0), (4, 3.0)], 6)
    assert np.isnan(got[0]) and got[1:].tolist() == [1.0, 1.0, 3.0, 3.0, 3.0]


def test_held_series_refuses_out_of_order():
    with pytest.raises(features.FeatureError):
        features.held_series([(4, 1.0), (2, 3.0)], 6)


# ---------- a whole reading on the real register and loop map ----------

@pytest.fixture
def plant():
    return features.plant_from_files(FAST)


def bands_for(plant):
    b = {t: (0.0, 1.0) for t in plant.measurements + plant.analyzers}
    b.update({t: (40.0, 60.0) for t in plant.valves})
    return b


def normal_run(plant, samples=60):
    x = np.array([[50.0 if t in plant.valves else 0.5 for t in plant.fast_tags]] * samples)
    pubs = {t: [(s, 0.5) for s in range(2, samples + 1, 2)] for t in plant.analyzers}
    return x, pubs


def test_plant_from_files(plant):
    assert len(plant.fast_tags) == 33 and len(plant.analyzers) == 19 and len(plant.valves) == 11
    assert plant.loops["RX-TIC-204"] == ("RX-TI-204", "RX-FV-206")      # cascade to its end valve
    assert plant.loops["RX-AIC-211"][0] == "RX-AI-211"
    with pytest.raises(features.FeatureError):
        features.plant_from_files(FAST[:-1])


def test_normal_reading(plant):
    x, pubs = normal_run(plant)
    r = features.reading(plant, x, pubs, bands_for(plant), t=30, n=3, as_of=40)
    assert set(r["tags"].values()) == {"normal"} and set(r["loops"].values()) == {"held"}
    assert set(r["analyzers"].values()) == {"normal"} and r["masked"] is False
    assert len(r["tags"]) == 33 and len(r["analyzers"]) == 19 and len(r["loops"]) == 19


def test_a_valve_absorbing_the_disturbance_is_masked_and_compensating(plant):
    x, pubs = normal_run(plant)
    j = plant.fast_tags.index("RX-FV-206")
    x[30:, j] = 75.0                                            # samples 31 on: out, not saturated
    r = features.reading(plant, x, pubs, bands_for(plant), t=30, n=3, as_of=40)
    assert r["tags"]["RX-FV-206"] == "high"
    assert r["loops"]["RX-TIC-205"] == "compensating" and r["loops"]["RX-TIC-204"] == "compensating"
    assert r["masked"] is True


def test_a_measurement_out_makes_the_loop_lost_and_unmasks(plant):
    x, pubs = normal_run(plant)
    x[30:, plant.fast_tags.index("RX-FV-206")] = 75.0
    x[30:, plant.fast_tags.index("RX-TI-204")] = 3.0
    r = features.reading(plant, x, pubs, bands_for(plant), t=30, n=3, as_of=40)
    assert r["loops"]["RX-TIC-204"] == "lost" and r["loops"]["RX-TIC-205"] == "compensating"
    assert r["masked"] is False


def test_an_analyzer_out_unmasks_through_its_held_series(plant):
    x, pubs = normal_run(plant)
    x[30:, plant.fast_tags.index("RX-FV-206")] = 75.0
    pubs["RX-AI-211"] = [(s, 0.5 if s < 32 else 4.0) for s in range(2, 61, 2)]
    r = features.reading(plant, x, pubs, bands_for(plant), t=30, n=3, as_of=40)
    assert r["analyzers"]["RX-AI-211"] == "high" and r["masked"] is False
    assert r["loops"]["RX-AIC-211"] == "lost"


def test_analyzers_count_only_values_published_after_the_notification(plant):
    x, pubs = normal_run(plant)
    pubs["SP-AI-412"] = [(s, 4.0 if s <= 30 else 0.5) for s in range(2, 61, 2)]
    r = features.reading(plant, x, pubs, bands_for(plant), t=30, n=3, as_of=40)
    assert r["analyzers"]["SP-AI-412"] == "normal"
    pubs["ST-AI-612"] = [(s, 0.5) for s in range(5, 61, 5)]    # every 5 samples: 35 and 40 after t = 30
    r = features.reading(plant, x, pubs, bands_for(plant), t=30, n=3, as_of=34)
    assert r["analyzers"]["ST-AI-612"] == "not_yet_available"


def test_reading_is_as_of(plant):
    x, pubs = normal_run(plant)
    x[30:, plant.fast_tags.index("RX-FV-206")] = 75.0
    base = features.reading(plant, x, pubs, bands_for(plant), t=30, n=3, as_of=40)
    later = x.copy()
    later[40:] = np.nan                                         # nothing after sample 40 is read
    later_pubs = {t: [(s, v if s <= 40 else float("nan")) for s, v in p] for t, p in pubs.items()}
    assert features.reading(plant, later, later_pubs, bands_for(plant), t=30, n=3, as_of=40) == base


def test_window_starts_at_the_triggering_samples(plant):
    # Out only on samples 28..30 (t = 30, n = 3): inside the window t - n + 1 .. as_of.
    x, pubs = normal_run(plant)
    x[27:30, plant.fast_tags.index("RX-PI-202")] = 5.0
    r = features.reading(plant, x, pubs, bands_for(plant), t=30, n=3, as_of=40)
    assert r["tags"]["RX-PI-202"] == "high"
    r = features.reading(plant, x, pubs, bands_for(plant), t=31, n=1, as_of=40)
    assert r["tags"]["RX-PI-202"] == "normal"


@pytest.mark.parametrize("t, n, as_of", [(2, 3, 10), (30, 3, 29), (30, 3, 61), (30, 0, 40)])
def test_window_refusals(plant, t, n, as_of):
    x, pubs = normal_run(plant)
    with pytest.raises(features.FeatureError):
        features.reading(plant, x, pubs, bands_for(plant), t=t, n=n, as_of=as_of)


def test_a_gap_in_the_window_is_refused(plant):
    x, pubs = normal_run(plant)
    x[35, 0] = np.nan
    with pytest.raises(features.FeatureError):
        features.reading(plant, x, pubs, bands_for(plant), t=30, n=3, as_of=40)


# ---------- extract ----------

def test_extract_location_and_readings(plant):
    x, pubs = normal_run(plant)
    names = ["feed", "reactor"]
    g = np.zeros((60, 2))
    g[27:30, 1] = 5.0                                            # reactor leads at t = 30
    k = np.zeros((60, 33))
    k[27:30, [3, 7, 1]] = [[9.0, 8.0, 7.0]] * 3
    got = features.extract(plant, x, pubs, bands_for(plant), 30, 3, g, k, names)
    assert got["location"] == {"top_group": "reactor",
                               "top_tags": [plant.fast_tags[3], plant.fast_tags[7], plant.fast_tags[1]]}
    assert set(got) == {"location", "provisional", "revised"}
    short = features.extract(plant, x[:45], pubs, bands_for(plant), 30, 3, g[:45], k[:45], names)
    assert set(short) == {"location", "provisional"}           # no revised reading before +60 min


def test_extract_needs_normals_for_every_tag(plant):
    x, pubs = normal_run(plant)
    b = bands_for(plant)
    del b["RX-AI-211"]
    with pytest.raises(features.FeatureError, match="RX-AI-211"):
        features.extract(plant, x, pubs, b, 30, 3, np.zeros((60, 1)), np.zeros((60, 33)), ["feed"])


def test_vocabulary_matches_the_schema():
    from app.library import schema
    assert set(schema.TAG_STATES) == {"high", "low", "both", "normal"}
    assert set(schema.LOOP_STATES) == {"held", "compensating", "lost", "saturated"}
    assert set(schema.ANALYZER_STATES) == {"high", "low", "normal", "not_yet_available"}
    assert features.READINGS == {"provisional": 10, "revised": 20}
