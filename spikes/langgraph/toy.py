"""Toy data for the spike: two entries and a toy historian. Not plant data, no labels.

reading(episode, notified_at, as_of) is what the evidence step would see as of as_of,
by minutes since the notification:
- before +30 min: nothing yet (raises ToyError: a diagnosis never runs that early)
- from +30 min (provisional): RX-FV-206, "high" for most episodes, "low" for episodes
  whose name starts with "unknown" (no toy entry matches that, so the graph declines)
- from +60 min (revised): RX-TI-204 "normal" is added
"""

from datetime import datetime

OFFSETS_MIN = {"provisional": 30, "revised": 60}
ENTRIES = {
    "toy-warm-supply": {"RX-FV-206": "high", "RX-TI-204": "normal"},
    "toy-valve-sticking": {"RX-FV-206": "both", "RX-TI-204": "both"},
}
ACTIONS = {"toy-warm-supply": "check-toy-supply", "toy-valve-sticking": "check-toy-valve"}


class ToyError(ValueError):
    pass


def reading(episode, notified_at, as_of) -> dict:
    minutes = (datetime.fromisoformat(as_of) - datetime.fromisoformat(notified_at)).total_seconds() / 60
    if minutes < OFFSETS_MIN["provisional"]:
        raise ToyError(f"no reading {minutes:.0f} min after the notification")
    out = {"RX-FV-206": "low" if episode.startswith("unknown") else "high"}
    if minutes >= OFFSETS_MIN["revised"]:
        out["RX-TI-204"] = "normal"
    return out
