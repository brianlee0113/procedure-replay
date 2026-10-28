"""Scoring a guide against human step labels (docs/B0_guide_eval_plan.md §4.1). Pure functions, no API calls.

Labels are data/keysteps/<video>.json: [{step, start, end}]. They are turned into units:
- fine units: labels with identical start and end in that video become one unit (primary metric);
- coarse units: the task's allowed merges (data/label_groups/<task>.json) applied where every label of a group
  is present and the labels are consecutive in time order, left to right (merge-tolerant metric).

A predicted step and a unit form a candidate pair when the step covers >= 50% of the unit and its clip is not
too long (max(2 x unit, unit + 6 s)). The judge answers "same action" per candidate pair; a hit is a candidate
the judge accepted, and hits are matched one-to-one (maximum bipartite matching), so one long step earns at most
one true positive.

`judgments` maps a step index to {"same_action": {unit_key: bool}, "rubric": {...}}; unit keys come from
`Unit.key`, so fine and coarse units can be judged in one call. Clip focus needs no judge: it is computed from
the label intervals (a matched clip is unfocused if it holds >= FOCUS_S of a label that does not overlap the
matched unit in time; concurrent labels and waiting inside the unit never count).
"""

import json
import statistics
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KEYSTEPS = ROOT / "data" / "keysteps"
LABEL_GROUPS = ROOT / "data" / "label_groups"

EPS = 0.01
MIN_COVER = 0.5      # a step must cover at least this share of the unit
LENGTH_FACTOR = 2.0  # clip <= max(LENGTH_FACTOR x unit, unit + LENGTH_SLACK_S)
LENGTH_SLACK_S = 6.0
IOU_MIN = 0.3
FOCUS_S = 10.0


@dataclass(frozen=True)
class Unit:
    labels: tuple[str, ...]
    start: float
    end: float

    @property
    def key(self) -> str:
        return f"{' + '.join(self.labels)} @{self.start:.2f}"

    @property
    def length(self) -> float:
        return self.end - self.start


@dataclass(frozen=True)
class Pred:
    """A predicted guide step: its bounds and the clip the app loops."""
    index: int
    start: float
    end: float
    clip_start: float
    clip_end: float

    @property
    def clip_length(self) -> float:
        return self.clip_end - self.clip_start


def preds_of(guide) -> list[Pred]:
    """Pred list from a pr.guides.Guide or its dict form."""
    steps = guide["steps"] if isinstance(guide, dict) else [s.model_dump() for s in guide.steps]
    return [Pred(s["index"], s["start_s"], s["end_s"], s["clip"]["start_s"], s["clip"]["end_s"]) for s in steps]


def load_labels(video_id: str) -> list[dict]:
    return json.loads((KEYSTEPS / f"{video_id}.json").read_text())


def load_merges(task: str) -> list[list[str]]:
    path = LABEL_GROUPS / f"{task}.json"
    return [m["labels"] for m in json.loads(path.read_text())["allowed_merges"]] if path.exists() else []


def _sorted(labels: list[dict]) -> list[dict]:
    return sorted(labels, key=lambda l: (l["start"], l["end"]))  # stable: ties keep label-file order


def _same_interval(units: list[Unit]) -> list[Unit]:
    out: list[Unit] = []
    for u in units:
        twin = next((o for o in out if abs(o.start - u.start) <= EPS and abs(o.end - u.end) <= EPS), None)
        if twin:
            out[out.index(twin)] = Unit(twin.labels + u.labels, twin.start, twin.end)
        else:
            out.append(u)
    return out


def fine_units(labels: list[dict]) -> list[Unit]:
    return _same_interval([Unit((l["step"],), l["start"], l["end"]) for l in _sorted(labels)])


def coarse_units(labels: list[dict], merges: list[list[str]]) -> list[Unit]:
    labels = _sorted(labels)
    units, i = [], 0
    while i < len(labels):
        for group in merges:
            run = labels[i:i + len(group)]
            if len(run) == len(group) and sorted(l["step"] for l in run) == sorted(group):
                units.append(Unit(tuple(l["step"] for l in run), min(l["start"] for l in run), max(l["end"] for l in run)))
                i += len(group)
                break
        else:
            units.append(Unit((labels[i]["step"],), labels[i]["start"], labels[i]["end"]))
            i += 1
    return _same_interval(units)


def overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def is_candidate(p: Pred, u: Unit) -> bool:
    covers = overlap(p.start, p.end, u.start, u.end) >= MIN_COVER * u.length - EPS
    short_enough = p.clip_length <= max(LENGTH_FACTOR * u.length, u.length + LENGTH_SLACK_S) + EPS
    return covers and short_enough


def candidates(preds: list[Pred], units: list[Unit]) -> dict[int, list[Unit]]:
    """Units each predicted step is a candidate for (what the judge is asked about)."""
    return {p.index: [u for u in units if is_candidate(p, u)] for p in preds}


def max_matching(edges: dict[int, list[str]]) -> dict[int, str]:
    """Maximum bipartite matching, left = step index, right = unit key (augmenting paths; graphs are small)."""
    owner: dict[str, int] = {}

    def augment(left: int, seen: set[str]) -> bool:
        for right in edges[left]:
            if right in seen:
                continue
            seen.add(right)
            if right not in owner or augment(owner[right], seen):
                owner[right] = left
                return True
        return False

    for left in sorted(edges):
        augment(left, set())
    return {left: right for right, left in owner.items()}


def f1(tp: int, n_pred: int, n_true: int) -> dict:
    p = tp / n_pred if n_pred else 0.0
    r = tp / n_true if n_true else 0.0
    return {"tp": tp, "n_pred": n_pred, "n_units": n_true, "precision": p, "recall": r,
            "f1": 2 * p * r / (p + r) if p + r else 0.0}


def step_hits(preds: list[Pred], units: list[Unit], judgments: dict[int, dict]) -> dict:
    """Step hit F1: candidate pairs the judge accepted, matched one-to-one."""
    by_key = {u.key: u for u in units}
    edges = {p.index: [u.key for u in units if is_candidate(p, u)
                       and judgments.get(p.index, {}).get("same_action", {}).get(u.key) is True] for p in preds}
    matches = max_matching(edges)
    out = f1(len(matches), len(preds), len(units))
    out["matches"] = {i: by_key[k] for i, k in matches.items()}
    return out


def temporal_iou_f1(preds: list[Pred], units: list[Unit], threshold: float = IOU_MIN) -> dict:
    """One-to-one matching on temporal IoU >= threshold, no semantic check (comparable with the uniform baseline)."""
    def iou(p: Pred, u: Unit) -> float:
        inter = overlap(p.start, p.end, u.start, u.end)
        return inter / (max(p.end, u.end) - min(p.start, u.start))
    edges = {p.index: [u.key for u in units if iou(p, u) >= threshold] for p in preds}
    return f1(len(max_matching(edges)), len(preds), len(units))


def focused(p: Pred, u: Unit, units: list[Unit]) -> bool:
    """False if p's clip holds >= FOCUS_S of a different unit that does not overlap u in time."""
    return not any(overlap(p.clip_start, p.clip_end, o.start, o.end) >= FOCUS_S for o in units
                   if o != u and overlap(o.start, o.end, u.start, u.end) <= EPS)


def order_tau(matches: dict[int, Unit]) -> float | None:
    """Kendall tau between step order and label order over matched pairs; pairs of units that overlap in time
    (concurrent work) are skipped. None when fewer than two comparable pairs."""
    items = sorted(matches.items())
    concordant = discordant = 0
    for a in range(len(items)):
        for b in range(a + 1, len(items)):
            ua, ub = items[a][1], items[b][1]
            if overlap(ua.start, ua.end, ub.start, ub.end) > EPS:
                continue
            if ua.start < ub.start:
                concordant += 1
            else:
                discordant += 1
    n = concordant + discordant
    return (concordant - discordant) / n if n else None


def boundary_errors(preds: list[Pred], matches: dict[int, Unit]) -> dict:
    by_index = {p.index: p for p in preds}
    ds = [abs(by_index[i].start - u.start) for i, u in matches.items()]
    de = [abs(by_index[i].end - u.end) for i, u in matches.items()]
    rel = [(abs(by_index[i].start - u.start) + abs(by_index[i].end - u.end)) / 2 / u.length
           for i, u in matches.items() if u.length > 0]
    med = lambda xs: statistics.median(xs) if xs else None
    return {"start_s": med(ds), "end_s": med(de), "relative": med(rel)}


def length_ratios(preds: list[Pred], matches: dict[int, Unit]) -> dict:
    by_index = {p.index: p for p in preds}
    rs = [by_index[i].clip_length / u.length for i, u in matches.items() if u.length > 0]
    return {"median": statistics.median(rs) if rs else None, "max": max(rs) if rs else None}


def score_video(preds: list[Pred], labels: list[dict], merges: list[list[str]], judgments: dict[int, dict]) -> dict:
    """All §4.1 segmentation metrics for one guide on one labelled video."""
    fine, coarse = fine_units(labels), coarse_units(labels, merges)
    hits = step_hits(preds, fine, judgments)
    matches = hits.pop("matches")
    coarse_hits = step_hits(preds, coarse, judgments)
    coarse_hits.pop("matches")
    by_index = {p.index: p for p in preds}
    focus = [focused(by_index[i], u, fine) for i, u in matches.items()]
    return {
        "step_hit": hits,
        "merge_tolerant": coarse_hits,
        "temporal_iou": temporal_iou_f1(preds, fine),
        "order_tau": order_tau(matches),
        "granularity": len(preds) / len(fine) if fine else None,
        "boundary": boundary_errors(preds, matches),
        "length_ratio": length_ratios(preds, matches),
        "clip_focus": sum(focus) / len(focus) if focus else None,
        "matches": {i: u.key for i, u in matches.items()},
    }


def uniform_steps(duration: float, length: float) -> list[tuple[float, float]]:
    """Uniform baseline: equal parts of about `length` seconds (the domain's median dev label length)."""
    n = max(1, round(duration / length))
    return [(duration * k / n, duration * (k + 1) / n) for k in range(n)]


def median_label_length(video_ids: list[str]) -> float:
    return statistics.median(l["end"] - l["start"] for v in video_ids for l in load_labels(v))
