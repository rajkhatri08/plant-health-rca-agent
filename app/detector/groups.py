"""Equipment groups for attribution (decisions 48, 64).

Runtime code: no imports from dataset/, eval/ or ingest/. Reads library/tags.yaml, which is
agent-visible.

load(tags) maps each group to the column indices of its tags in the given order (the
model's tag order). Groups come in the order they first appear in the register, and a
group with none of the given tags is left out. Every given tag belongs to exactly one
group, so the groups partition the model's columns.
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTER = REPO_ROOT / "library" / "tags.yaml"


class GroupError(ValueError):
    pass


def load(tags, register=REGISTER) -> dict:
    """{group name: tuple of column indices into tags}. Raises GroupError on a tag that
    isn't in the register (including lagged names such as TAG@t-1), on a repeated tag, or
    on a register row with no group."""
    tags = tuple(tags)
    if len(set(tags)) != len(tags):
        raise GroupError("a tag appears twice in the model's tags")
    rows = yaml.safe_load(Path(register).read_text())["tags"]
    group_of, order = {}, []
    for r in rows:
        g = r.get("group")
        if not g:
            raise GroupError(f"register row {r.get('tag')} has no group")
        group_of[r["tag"]] = g
        if g not in order:
            order.append(g)
    unknown = [t for t in tags if t not in group_of]
    if unknown:
        raise GroupError(f"tags not in the register: {unknown[:5]}")
    groups = {g: tuple(i for i, t in enumerate(tags) if group_of[t] == g) for g in order}
    return {g: cols for g, cols in groups.items() if cols}
