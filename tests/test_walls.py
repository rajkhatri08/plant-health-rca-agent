"""Import and read walls (eval/LEAKAGE.md, CI checks): app/ imports neither eval/, ingest/
nor dataset/, and only dataset/ reads raw data files."""

import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FORBIDDEN_IN_APP = {"eval", "ingest", "dataset"}
READ_DATA = re.compile(r"\.parquet|\.rdata\b|read_parquet|pyarrow|pyreadr", re.IGNORECASE)
NOT_DATASET = ["app", "eval", "ingest", "library"]


def imported_top_modules(source):
    mods = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            mods |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative imports stay inside their own package
                continue
            mods.add(node.module.split(".")[0])
    return mods


def py_files(*dirs):
    for d in dirs:
        yield from sorted(p for p in (REPO / d).rglob("*.py") if "__pycache__" not in p.parts)


def test_app_imports_no_eval_ingest_or_dataset():
    hits = [f"{p.relative_to(REPO)}: {m}" for p in py_files("app")
            for m in imported_top_modules(p.read_text()) & FORBIDDEN_IN_APP]
    assert hits == []


def test_only_dataset_reads_raw_files():
    hits = [f"{p.relative_to(REPO)}: {m.group(0)}" for p in py_files(*NOT_DATASET)
            for m in READ_DATA.finditer(p.read_text())]
    assert hits == []


@pytest.mark.parametrize("src, expected", [
    ("import eval.metrics", {"eval"}), ("from ingest.tags import x", {"ingest"}),
    ("from dataset import loader", {"dataset"}), ("import numpy as np", {"numpy"}),
    ("from . import sibling", set()),
])
def test_import_scanner(src, expected):
    assert imported_top_modules(src) == expected


@pytest.mark.parametrize("src", ["pq.read_table('x.parquet')", "import pyarrow", "pd.read_parquet(p)",
                                 "load('TEP.RData')", "import pyreadr"])
def test_read_scanner_catches(src):
    assert READ_DATA.search(src)


@pytest.mark.parametrize("src", ["np.load(bundle)", "yaml.safe_load(text)", "read_text()"])
def test_read_scanner_passes(src):
    assert not READ_DATA.search(src)