"""Guide scoring on hand-made cases (B0 plan §3.4, §4.1). No API calls. Run: uv run python tests/test_guide_eval.py"""

from pr.guide_eval import (Pred, coarse_units, fine_units, is_candidate, load_labels, load_merges, max_matching,
                           order_tau, score_video, temporal_iou_f1, uniform_steps)


def L(step, start, end):
    return {"step": step, "start": start, "end": end}


def P(index, start, end, pad=1.0):
    return Pred(index, start, end, max(0.0, start - pad), end + pad)


def yes(*pairs):
    """judgments: step index -> the unit keys the judge called the same action."""
    out = {}
    for i, key in pairs:
        out.setdefault(i, {"same_action": {}})["same_action"][key] = True
    return out


# Fine units: identical intervals merge, partial overlaps do not.
labels = [L("scoop", 10, 20), L("plate", 10, 20), L("crack egg", 30, 40), L("cook", 25, 60)]
fine = fine_units(labels)
assert [u.labels for u in fine] == [("scoop", "plate"), ("cook",), ("crack egg",)], fine

# Coarse units: a merge applies only to a consecutive run that is exactly the group, left to right.
drill = [L("unplug", 0, 3), L("remove bit", 4, 8), L("insert bit", 9, 14), L("remove bit", 15, 18),
         L("insert bit", 19, 24), L("plug in", 25, 27), L("test", 27, 30)]
merges = [["remove bit", "insert bit"], ["plug in", "test"]]
assert [u.labels for u in coarse_units(drill, merges)] == [
    ("unplug",), ("remove bit", "insert bit"), ("remove bit", "insert bit"), ("plug in", "test")]
assert coarse_units(drill, merges)[1].start == 4 and coarse_units(drill, merges)[1].end == 14
missing = [L("unplug", 0, 3), L("remove bit", 4, 8), L("plug in", 25, 27), L("test", 27, 30)]  # bit never inserted
assert [u.labels for u in coarse_units(missing, merges)] == [("unplug",), ("remove bit",), ("plug in", "test")]
apart = [L("plug in", 0, 2), L("unplug", 3, 5), L("test", 6, 9)]  # another label between them
assert [u.labels for u in coarse_units(apart, merges)] == [("plug in",), ("unplug",), ("test",)]

# Candidates: >= 50% cover and the length cap max(2 x unit, unit + 6 s).
u = fine_units([L("a", 10, 14)])[0]
assert is_candidate(P(1, 11, 14), u)                    # covers 75%, clip 5 s
assert not is_candidate(P(1, 13, 20), u)                # covers 25%
assert is_candidate(P(1, 9, 17, pad=0), u)              # clip 8 s <= 4 + 6
assert not is_candidate(P(1, 9, 20, pad=0), u)          # clip 11 s > 10
long_unit = fine_units([L("cook", 0, 100)])[0]
assert is_candidate(P(1, 0, 190, pad=0), long_unit) and not is_candidate(P(1, 0, 210, pad=0), long_unit)

# Matching is one-to-one: one long step accepted for three labels earns one true positive.
assert max_matching({1: ["a", "b"], 2: ["a"]}) == {1: "b", 2: "a"}
three = [L("a", 0, 10), L("b", 10, 20), L("c", 20, 30)]
keys = [x.key for x in fine_units(three)]
s = score_video([P(1, 0, 30, pad=0)], three, [], yes((1, keys[0]), (1, keys[1]), (1, keys[2])))
assert s["step_hit"]["tp"] == 0  # 30 s clip is over the cap for 10 s units: no candidate at all
s = score_video([P(1, 0, 16, pad=0)], three, [], yes((1, keys[0]), (1, keys[1])))
assert s["step_hit"]["tp"] == 1 and s["step_hit"]["recall"] == 1 / 3 and s["step_hit"]["precision"] == 1.0

# The judge's "no" removes a candidate; a multi-label unit is one unit.
s = score_video([P(1, 10, 20), P(2, 30, 40)], labels, [], yes((1, fine[0].key)))
assert s["step_hit"]["tp"] == 1 and s["step_hit"]["n_units"] == 3

# Merge-tolerant: a step covering an allowed merge counts once against the coarse set.
co = coarse_units(drill, merges)
preds = [P(1, 0, 3), P(2, 4, 14), P(3, 15, 24), P(4, 25, 30)]
s = score_video(preds, drill, merges, yes(*[(p.index, c.key) for p, c in zip(preds, co)]))
assert s["merge_tolerant"]["tp"] == 4 and s["merge_tolerant"]["n_units"] == 4
assert s["step_hit"]["tp"] == 1 and s["step_hit"]["n_units"] == 7  # only "unplug" is the same unit in both sets

# Clip focus: >= 10 s of a non-concurrent label in the clip; concurrent work does not count.
from pr.guide_eval import focused  # noqa: E402
cook = fine_units([L("cook", 0, 60), L("crack", 10, 25), L("serve", 61, 80)])
assert focused(P(1, 0, 60), cook[0], cook)              # crack overlaps cook in time: concurrent
assert not focused(P(1, 0, 75), cook[0], cook)          # 14 s of serving in the clip
s = score_video([P(1, 0, 60), P(2, 61, 80)], [L("cook", 0, 60), L("crack", 10, 25), L("serve", 61, 80)], [],
                yes((1, cook[0].key), (2, cook[2].key)))
assert s["clip_focus"] == 1.0

# Order: a swap gives tau < 1; overlapping (concurrent) units are not compared.
f = fine_units([L("a", 0, 10), L("b", 20, 30), L("c", 40, 50)])
assert order_tau({1: f[0], 2: f[1], 3: f[2]}) == 1.0
assert order_tau({1: f[1], 2: f[0], 3: f[2]}) == 1 / 3
conc = fine_units([L("cook", 0, 60), L("crack", 10, 20)])
assert order_tau({1: conc[1], 2: conc[0]}) is None

# Temporal IoU F1 and the uniform baseline.
assert temporal_iou_f1([P(1, 0, 10), P(2, 10, 20)], f)["tp"] == 1
assert uniform_steps(60.0, 20.0) == [(0.0, 20.0), (20.0, 40.0), (40.0, 60.0)]

# Real label files load and every allowed merge names real steps.
assert len(fine_units(load_labels("cc4d_22_21"))) == 14  # scoop + plate share one interval there
assert load_merges("pc_repair") == [] and len(load_merges("home_cooking")) == 3

print("ok")
