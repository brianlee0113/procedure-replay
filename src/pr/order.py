"""Which steps must come before which, as pairs of keystep names (a, b) = "a before b".

- If the dataset ships a task graph (CaptainCook4D recipes, data/task_graphs/<task>.json), use it.
- Otherwise learn it from the correct takes: a must precede b when every correct take that does both
  does a first. IndEgo's PC repair shows why: experts install the five parts in many different orders,
  but all of them open the case first, clean before closing, and test last.

Videos being evaluated (and the takes they were edited from) are excluded, so the rules never come
from the video under test.
"""

import json

from pr.license_check import ROOT

KEYSTEPS = ROOT / "data" / "keysteps"
GRAPHS = ROOT / "data" / "task_graphs"
MIN_TAKES = 3  # a pair needs this many correct takes doing both steps before it becomes a rule


def mistake_takes() -> set[str]:
    ids = set()
    for f in ("indego_mistakes.jsonl", "captaincook_mistakes.jsonl"):
        path = ROOT / "data" / f
        if path.exists():
            ids |= {json.loads(l)["video_id"] for l in path.read_text().splitlines() if l.strip()}
    return ids


def first_order(video_id: str) -> list[str]:
    """Keystep names in the order the take first does them."""
    seen: list[str] = []
    for s in json.loads((KEYSTEPS / f"{video_id}.json").read_text()):
        if s["step"] not in seen:
            seen.append(s["step"])
    return seen


def keystep_pairs(task: str, manifest: list[dict], exclude: set[str] = frozenset()) -> set[tuple[str, str]]:
    graph = GRAPHS / f"{task}.json"
    if graph.exists():
        return {tuple(p) for p in json.loads(graph.read_text())["before"]}
    bad = mistake_takes() | set(exclude)
    takes = [first_order(r["video_id"]) for r in manifest
             if r["task"] == task and "__" not in r["video_id"] and r["video_id"] not in bad
             and (KEYSTEPS / f"{r['video_id']}.json").exists()]
    names = {s for t in takes for s in t}
    pairs = set()
    for a in names:
        for b in names - {a}:
            both = [t for t in takes if a in t and b in t]
            if len(both) >= MIN_TAKES and all(t.index(a) < t.index(b) for t in both):
                pairs.add((a, b))
    return pairs
