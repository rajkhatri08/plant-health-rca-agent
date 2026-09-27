"""Raw column -> plant tag mapping (builder side; decisions 34 and 44).

Reads ingest/tag_map.yaml (raw names) and library/tags.yaml (tag metadata). Raw names
stay on this side: callers get plant tags back.
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


def tag_map(repo_root=None) -> dict:
    """{raw column: plant tag}."""
    root = Path(repo_root or REPO_ROOT)
    rows = yaml.safe_load((root / "ingest" / "tag_map.yaml").read_text())["tags"]
    return {r["raw"]: r["tag"] for r in rows}


def register(repo_root=None) -> list:
    """The tag register rows, in file order."""
    root = Path(repo_root or REPO_ROOT)
    return yaml.safe_load((root / "library" / "tags.yaml").read_text())["tags"]


def fast_tags(repo_root=None) -> list:
    """The detector's tags: every register tag that isn't an analyzer, in register order."""
    return [r["tag"] for r in register(repo_root) if r["kind"] != "analyzer"]


def column_indices(columns, tags, repo_root=None) -> list:
    """Indices into raw `columns` for each plant tag in `tags`, in that order."""
    to_raw = {tag: raw for raw, tag in tag_map(repo_root).items()}
    missing = [t for t in tags if t not in to_raw or to_raw[t] not in columns]
    if missing:
        raise KeyError(f"no raw column for tags {missing}")
    position = {c: i for i, c in enumerate(columns)}
    return [position[to_raw[t]] for t in tags]