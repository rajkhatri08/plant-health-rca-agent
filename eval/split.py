"""The two splits an evaluation driver can run on, and every way they differ (week 7 S1).

- dev: the 50 dev run numbers of the training files (decision 49), onset after sample 20,
  faults 1-15. Outputs go where each driver already puts them, under <repo>/data.
- test: all 500 runs of the testing files, onset after sample 160, faults 1-20 (16-20 from
  the testing file only, S0 answer 5). Loaded through loader.load_testing, so only under
  EVAL_MODE and with an access-log line per file. Per-case outputs go to the sealed folder
  (S0 answers 21, 22), never under the repo.

A driver takes --split dev|test and asks its Split for runs, the onset and the output
folder, so no driver hardcodes a split again.
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from dataset import loader
from eval import metrics

NAMES = ("dev", "test")
TEST_SEED = 20261006               # S0 answer 14: one draw for every fault and the normal runs
TEST_DRAW = 10
TEST_RUN_NUMBERS = range(1, 501)


def test_draw(seed=TEST_SEED, n=TEST_DRAW, numbers=TEST_RUN_NUMBERS):
    """The test subsample's run numbers, sorted: n drawn without replacement from the sorted
    numbers with numpy's default generator at seed (as agent_table draws its dev subsets).
    Used for every fault and for the normal runs' false-alert cases (S0 answers 14, 15)."""
    pool = sorted(int(k) for k in numbers)
    return sorted(int(x) for x in np.random.default_rng(seed).choice(pool, n, replace=False))


@dataclass(frozen=True)
class Split:
    name: str
    onset: int                 # the last pre-fault sample
    faults: tuple
    purpose: str               # written to the access log on a test load

    def load_normal(self):
        if self.name == "dev":
            return loader.load_normal("dev")
        return loader.load_testing(0, purpose=self.purpose)

    def load_faulty(self, fault):
        if fault not in self.faults:
            raise loader.LoaderError(f"fault {fault} isn't in the {self.name} split's faults")
        if self.name == "dev":
            return loader.load_faulty(fault, "dev")
        return loader.load_testing(fault, purpose=self.purpose)

    def out_dir(self, default, label):
        """Where a run's per-case outputs go: default (a folder under <repo>/data) on dev;
        <sealed folder>/test_outputs/<label> on test."""
        if self.name == "dev":
            return Path(default)
        return loader.SEALED_ROOT / "test_outputs" / label

    def cache_dir(self, default):
        """The LLM cache: default on dev; <sealed folder>/llm_cache on test (S0 answer 22)."""
        return Path(default) if self.name == "dev" else loader.SEALED_ROOT / "llm_cache"


def get(name, purpose):
    """The Split called name. purpose names the command, for the access log."""
    if name == "dev":
        return Split("dev", metrics.TRAIN_ONSET, tuple(loader.OPEN_FAULTS), purpose)
    if name == "test":
        return Split("test", metrics.TEST_ONSET, tuple(range(1, 21)), purpose)
    raise ValueError(f"unknown split {name!r}; one of {NAMES}")