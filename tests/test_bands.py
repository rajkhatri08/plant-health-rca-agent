"""app/detector/bands.py: precedence, group bands and the attributed group (decisions 12,
65, 66). Hand-built cases."""

import numpy as np
import pytest

from app.detector import bands
from eval import metrics


# ---------- group bands ----------

def test_group_bands_are_strictly_above_one():
    assert bands.group_bands([0.5, 1.0, 1.0000001, 3.0]) == ["Normal", "Normal", "Watch", "Watch"]


@pytest.mark.parametrize("bad", [np.nan, np.inf])
def test_group_bands_refuse_non_finite(bad):
    with pytest.raises(ValueError):
        bands.group_bands([0.5, bad])


# ---------- plant band precedence ----------

@pytest.mark.parametrize("unknown, alert_on, ratios, expected", [
    (True, True, [2.0, 2.0], "Unknown"),          # Unknown beats everything
    (True, False, [0.1, 0.1], "Unknown"),
    (False, True, [2.0, 2.0], "Alert"),           # Alert beats Watch
    (False, True, [0.1, 0.1], "Alert"),           # an alert held after the ratios drop
    (False, False, [0.1, 1.5], "Watch"),          # any group above 1
    (False, False, [1.0, 1.0], "Normal"),         # exactly 1 isn't Watch
    (False, False, [0.1, 0.2], "Normal"),
    (False, False, None, "Normal"),               # a bundle without Watch boundaries
    (False, True, None, "Alert"),
])
def test_plant_band_precedence(unknown, alert_on, ratios, expected):
    assert bands.plant_band(unknown, alert_on, ratios) == expected


def test_band_names():
    assert bands.BANDS == ("Normal", "Watch", "Alert", "Unknown")


# ---------- notifications (the protocol's definition, without importing eval/) ----------

@pytest.mark.parametrize("seed", range(5))
def test_notifications_equal_the_metric(seed):
    alert = (np.random.default_rng(seed).random(80) > 0.6).astype(int)
    for warmup in (0, 3, 9):
        assert bands.notifications(alert, warmup) == metrics.notifications(alert, warmup)


# ---------- attributed group ----------

NAMES = ["feed", "reactor", "condenser"]
#                     feed reactor condenser        sample
RATIOS = np.array([[0.1, 0.1, 0.1],               # 1
                   [0.2, 0.9, 0.1],               # 2
                   [0.3, 1.5, 0.1],               # 3
                   [0.4, 2.5, 0.2],               # 4  <- first alert (n = 2: samples 3, 4)
                   [5.0, 0.1, 0.1],               # 5  still the same episode
                   [5.0, 0.1, 0.1],               # 6  off
                   [0.1, 0.1, 4.0],               # 7
                   [0.1, 0.1, 4.0]])              # 8  <- second alert (samples 7, 8)
ALERT = np.array([0, 0, 0, 1, 1, 0, 0, 1])


def test_attributed_is_fixed_at_the_episodes_notification():
    # Episode 1 starts at sample 4: means over samples 3..4 are feed 0.35, reactor 2.0,
    # condenser 0.15, so reactor. At sample 5 feed is far higher, but the episode keeps
    # reactor. Episode 2 starts at 8: condenser.
    got = bands.attributed(ALERT, RATIOS, warmup=1, n=2, names=NAMES)
    assert got == [None, None, None, "reactor", "reactor", None, None, "condenser"]


def test_attributed_reads_nothing_after_the_notification():
    later = RATIOS.copy()
    later[4:6, 0] = 100.0                         # samples 5, 6 change
    assert bands.attributed(ALERT, later, 1, 2, NAMES)[3] == "reactor"


def test_alert_on_at_the_first_scored_sample_is_attributed_there():
    alert = np.array([0, 1, 1, 0, 0, 0, 0, 0])    # warm-up 1: sample 2 is the first scored
    got = bands.attributed(alert, RATIOS, warmup=1, n=2, names=NAMES)
    assert got[:3] == [None, "reactor", "reactor"]     # samples 1..2: reactor 0.5 vs feed 0.15