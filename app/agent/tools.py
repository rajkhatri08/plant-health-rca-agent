"""The agent's tools: the evidence and the library entries, as of the diagnosis time
(decisions 11, 16, 74, 75; CLAUDE.md, Time and Leakage).

Runtime code: no imports from dataset/, eval/ or ingest/. Tool outputs are agent-visible,
so each one goes through the leak scan (shared/leak_scan.py) before it's returned, and a
leak withholds the whole output (LeakError).

Every argument comes from the graph's saved state, never from the LLM: history_id, the
notification time and as_of (decision 74: as_of = notified_at + 30 or 60 min).

evidence(history_id, notified_at, as_of)
    The categorical evidence at as_of for an alert notified at notified_at: the location
    at the notification, and each reading (+30 min provisional, +60 min revised) whose
    time is at or before as_of. The stream is cut at as_of first, so nothing after as_of
    is read, not even to compute something that is then dropped:
    - fast tags: only samples with ts <= as_of
    - analyzers: only values published at or before as_of, held, never interpolated
      (features.held_series)
    - RBC (decision 65): only the n triggering samples t - n + 1 .. t, row by row
    Then app/detector/features.extract, the code evaluation uses (decision 19), on the cut
    stream. At +30 min it can't return the revised reading: that reading's samples aren't
    in the cut stream.
    It needs notified_at as well as as_of: the location and each reading's window start at
    the notification (decisions 65, 68). Output: {"notified_at", "as_of", "features"},
    with features in features.extract's form (states only, no raw values; decision 75).

retrieve(entry_ids, as_of)
    store.agent_view for each listed entry in force at as_of (store.Library.get): no
    drafts, no withdrawn entries, no approvals after as_of, and never the sources. Output:
    {"as_of", "entries": [...], "not_in_force": [...]}, entries in the order asked.

history_id names the episode's history. Here it selects the historian stream (one stream
per episode; the engine resets per stream, decision 37). When work orders are built it
also keys them. It's opaque: it never carries a run or fault number.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np

from app.detector import features, rbc, replay
from app.library import store
from shared import leak_scan


class ToolError(RuntimeError):
    pass


@dataclass(frozen=True)
class History:
    """One episode's historian stream: the fast tags on the sample grid (replay.Stream, in
    the model's tag order) and each analyzer's publications {tag: ((ts, value), ...)}."""
    stream: replay.Stream
    analyzers: dict


def load_history(csv_path, bundle) -> History:
    """A History from a historian CSV (ts, tag, value, quality), as written by
    ingest/export_replay.py."""
    plant = features.plant_from_files(bundle.model.tags)
    return History(stream=replay.read_csv(csv_path, bundle.model.tags),
                   analyzers=replay.read_publications(csv_path, plant.analyzers))


def _aware(t, what):
    if not isinstance(t, datetime) or t.tzinfo is None:
        raise ToolError(f"{what} must be a timezone-aware datetime, got {t!r}")
    return t


def _utc(t):
    return t.astimezone(timezone.utc).strftime(replay.TS_FORMAT)


def _leak_checked(out, where):
    leak_scan.check(json.dumps(out, sort_keys=True), where)
    return out


class Tools:
    """The tools for one bundle (pca_v3 on: Watch boundaries and evidence normals), one
    library, and the episodes' histories {history_id: History}."""

    def __init__(self, bundle, library, histories):
        if bundle.watch is None or bundle.normals is None:
            raise ToolError(f"bundle {bundle.name} lacks Watch boundaries or evidence normals; "
                            "the evidence tool needs pca_v3 or later")
        self.bundle = bundle
        self.library = library
        self.histories = histories
        self.plant = features.plant_from_files(bundle.model.tags)
        self.bands = bundle.bands()
        w = bundle.watch
        self.group_names = list(w["groups"])
        self.group_cols = [tuple(bundle.model.tags.index(t) for t in w["groups"][g]["tags"])
                           for g in self.group_names]
        self.w_group = np.array([w["groups"][g]["w"] for g in self.group_names])
        self.w_tag = np.array([w["tags"][t] for t in bundle.model.tags])
        self.M = rbc.index_matrix(bundle.model, bundle.limits["t2_lim"], bundle.limits["spe_lim"])

    # ---------- evidence ----------

    def _history(self, history_id):
        try:
            return self.histories[history_id]
        except KeyError:
            raise ToolError(f"no history {history_id!r}") from None

    def evidence(self, history_id, notified_at, as_of) -> dict:
        _aware(notified_at, "notified_at")
        _aware(as_of, "as_of")
        if as_of < notified_at:
            raise ToolError("as_of is before the notification")
        h = self._history(history_id)
        ts = h.stream.ts
        if notified_at not in ts:
            raise ToolError(f"the notification {notified_at.isoformat()} isn't a sample of the stream")
        t = ts.index(notified_at) + 1                          # 1-based notification sample
        m = sum(1 for x in ts if x <= as_of)                   # the cut: samples 1..m only
        X = h.stream.values[:m]                                # nothing after as_of from here on
        n = self.bundle.limits["n"]
        if t - n < 0:
            raise ToolError(f"the notification at sample {t} has fewer than n = {n} samples before it")

        # RBC over the triggering samples only (decision 65), row by row, so a gap elsewhere
        # in the stream is never scored. rank_at reads only these rows.
        window = X[t - n:t]
        try:
            g = rbc.group_rbc(self.bundle.model, self.M, window, self.group_cols) / self.w_group
            k = rbc.tag_rbc(self.bundle.model, self.M, window) / self.w_tag
        except ValueError as e:
            raise ToolError(f"the triggering samples can't be scored: {e}") from None
        group_ratios = np.full((m, len(self.group_names)), np.nan)
        tag_ratios = np.full((m, len(self.bundle.model.tags)), np.nan)
        group_ratios[t - n:t], tag_ratios[t - n:t] = g, k

        sample = {x: i + 1 for i, x in enumerate(ts[:m])}
        pubs = {}
        for tag in self.plant.analyzers:
            items = []
            for when, value in h.analyzers.get(tag, ()):
                if when > as_of:
                    break                                      # published after as_of: unseen
                if when not in sample:
                    raise ToolError(f"{tag} published at {when.isoformat()}, off the sample grid")
                items.append((sample[when], value))
            pubs[tag] = items
        try:
            feats = features.extract(self.plant, X, pubs, self.bands, t, n, group_ratios, tag_ratios,
                                     self.group_names)
        except (features.FeatureError, ValueError) as e:
            raise ToolError(f"the evidence can't be read as of {as_of.isoformat()}: {e}") from None
        out = {"notified_at": _utc(notified_at), "as_of": _utc(as_of), "features": feats}
        return _leak_checked(out, "the evidence tool's output")

    # ---------- retrieval ----------

    def retrieve(self, entry_ids, as_of) -> dict:
        _aware(as_of, "as_of")
        entries, not_in_force = [], []
        for entry_id in dict.fromkeys(entry_ids):              # each once, in the order asked
            got = self.library.get(entry_id, as_of)
            if got is None:
                not_in_force.append(entry_id)
            else:
                entries.append(store.agent_view(got))
        out = {"as_of": _utc(as_of), "entries": entries, "not_in_force": not_in_force}
        return _leak_checked(out, "the retrieval tool's output")