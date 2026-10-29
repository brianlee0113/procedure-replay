"""Blind human check of the Muse Spark judge (docs/B0_guide_eval_plan.md §4.2, early dev check §7).

    uv run python scripts/judge_check.py draw                  # 30 dev items -> results/judge_check/dev/
    uv run python scripts/judge_check.py score answers.json    # agreement, from the scoring page's answers

draw: run 1 of the B2 baseline, 10 items per labelled domain, fixed seed: 4 judge-accepted pairs, 2 judge-rejected
pairs, 2 unmatched predicted steps from the main configuration and 2 accepted pairs from "uniform + captions";
a short category is filled from the domain's other categories (accepted first). Each item's step clip is cut from
the source video (360p, with sound). page.json holds only what the scorer sees; key.json holds the judge's answers
and where each item came from, and is never shown on the page.
"""

import argparse
import json
import random
import subprocess
import sys
from collections import Counter

from pr.client import RESULTS
from pr.guide_eval import coarse_units, fine_units, load_labels, load_merges, overlap, preds_of, score_video
from pr.guide_judge import RUBRIC
from pr.guides import Guide
from pr.license_check import find_row, local_path
from pr.transcribe import TRANSCRIPTS

sys.path.insert(0, str(RESULTS.parent / "scripts"))
from run_guides import DOMAIN, RUNS, videos_of  # noqa: E402

OUT = RESULTS / "judge_check" / "dev"
SEED = 20261028
QUOTA = {"accepted": 4, "rejected": 2, "unmatched": 2, "baseline": 2}
MAIN_CFG = "tr-ost-mute"


def load_run(cfg: str, video: str, task: str):
    folder = RUNS / cfg / "run1" / video
    guide = Guide.model_validate_json((folder / "guide.json").read_text())
    path = folder / "judge.json"  # absent when no step had a candidate label, so the judge was never called
    judge = {int(i): v for i, v in json.loads(path.read_text())["steps"].items()} if path.exists() else {}
    labels, merges = load_labels(video), load_merges(task)
    score = score_video(preds_of(guide), labels, merges, judge)
    units = {u.key: u for u in fine_units(labels) + coarse_units(labels, merges)}
    return guide, judge, labels, score, units


def pools(task: str, videos: list[str]) -> dict[str, list[dict]]:
    out = {k: [] for k in QUOTA}
    for v in videos:
        for cfg in (MAIN_CFG, "uniform+captions"):
            guide, judge, labels, score, units = load_run(cfg, v, task)
            matches = {int(i): k for i, k in score["matches"].items()}
            for s in guide.steps:
                base = {"video": v, "task": task, "cfg": cfg, "step": s.index}
                if cfg != MAIN_CFG:
                    if s.index in matches:
                        out["baseline"].append({**base, "kind": "pair", "unit": matches[s.index]})
                    continue
                if s.index in matches:
                    out["accepted"].append({**base, "kind": "pair", "unit": matches[s.index]})
                else:
                    out["unmatched"].append({**base, "kind": "unmatched"})
                for key, same in judge.get(s.index, {}).get("same_action", {}).items():
                    if not same:
                        out["rejected"].append({**base, "kind": "pair", "unit": key})
    return out


def draw_domain(task: str, rng: random.Random) -> list[dict]:
    videos = [v for v, t in videos_of("dev") if t == task]
    pool = pools(task, videos)
    for items in pool.values():
        rng.shuffle(items)
    taken, used = [], set()

    def take(category: str, n: int) -> int:
        got = 0
        for item in pool[category]:
            if got == n:
                break
            step_id = (item["video"], item["cfg"], item["step"])
            if step_id not in used:
                used.add(step_id)
                taken.append({**item, "category": category})
                got += 1
        return got

    short = sum(n - take(c, n) for c, n in QUOTA.items())
    for c in ["accepted", "rejected", "unmatched", "baseline"]:
        short -= take(c, short) if short else 0
    return taken


def cut(video: str, start: float, end: float, out) -> None:
    if out.exists():
        return
    src = local_path(find_row(video))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.2f}", "-i", str(src), "-t", f"{end - start:.2f}",
                    "-vf", "scale=-2:360", "-c:v", "libx264", "-preset", "veryfast", "-crf", "30",
                    "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", str(out)], check=True)


def said(video: str, start: float, end: float) -> list[dict]:
    path = TRANSCRIPTS / f"{video}.json"
    turns = json.loads(path.read_text())["turns"] if path.exists() else []
    return [{"start_s": t["start_s"], "end_s": t["end_s"], "text": t["text"]}
            for t in turns if t["end_s"] > start and t["start_s"] < end]


def draw() -> None:
    rng = random.Random(SEED)
    items = [i for task in DOMAIN for i in draw_domain(task, rng)]
    rng.shuffle(items)
    (OUT / "clips").mkdir(parents=True, exist_ok=True)
    page, key = [], {}
    for n, item in enumerate(items, 1):
        qid = f"q{n:02d}"
        guide, judge, labels, _, units = load_run(item["cfg"], item["video"], item["task"])
        step = next(s for s in guide.steps if s.index == item["step"])
        clip = f"clips/{qid}.mp4"
        cut(item["video"], step.clip.start_s, step.clip.end_s, OUT / clip)
        shown = {
            "id": qid, "kind": item["kind"], "domain": DOMAIN[item["task"]], "clip": clip,
            "clip_start_s": step.clip.start_s, "clip_end_s": step.clip.end_s,
            "step": {"title": step.title, "instruction": step.instruction, "done_when": step.done_when,
                     "key_objects": step.key_objects, "start_s": step.start_s, "end_s": step.end_s},
            "said": said(item["video"], step.clip.start_s, step.clip.end_s),  # both configs saw the transcript
            "all_labels": [{"name": l["step"], "start_s": l["start"], "end_s": l["end"]}
                           for l in sorted(labels, key=lambda l: l["start"])],
        }
        verdict = judge.get(item["step"], {})
        if item["kind"] == "pair":
            u = units[item["unit"]]
            shown["label"] = {"name": " + ".join(u.labels), "start_s": u.start, "end_s": u.end}
            judged = {"same_action": verdict.get("same_action", {}).get(item["unit"]), "rubric": verdict.get("rubric")}
        else:
            near = [u for u in fine_units(labels) if overlap(step.start_s, step.end_s, u.start, u.end) > 0]
            shown["overlapping"] = [{"name": " + ".join(u.labels), "start_s": u.start, "end_s": u.end} for u in near]
            judged = {"same_action": {k: v for k, v in verdict.get("same_action", {}).items()}}
        page.append(shown)
        key[qid] = {**item, "judge": judged}
    (OUT / "page.json").write_text(json.dumps(page, indent=1, ensure_ascii=False))
    (OUT / "key.json").write_text(json.dumps(key, indent=1, ensure_ascii=False))
    counts = Counter((DOMAIN[i["task"]], i["category"]) for i in items)
    print(json.dumps({f"{d} / {c}": n for (d, c), n in sorted(counts.items())}, indent=1))
    print(f"wrote {len(items)} items to {OUT}")


def score(answers_path: str) -> None:
    """Agreement per domain as counts (§4.2). answers: [{id, data: {same_action | label_choice, rubric}}]."""
    key = json.loads((OUT / "key.json").read_text())
    rows = json.loads(open(answers_path).read())
    answers = {r["id"]: r.get("data", r) for r in rows}
    tally = {}
    for qid, k in key.items():
        a = answers.get(qid)
        if not a:
            continue
        t = tally.setdefault(DOMAIN[k["task"]], Counter())
        if k["kind"] == "pair":
            t["same_action n"] += 1
            t["same_action agree"] += bool(a.get("same_action")) == bool(k["judge"]["same_action"])
            if k["category"] in ("accepted", "baseline") and a.get("rubric") and k["judge"]["rubric"]:
                for r in RUBRIC:
                    t[f"{r} n"] += 1
                    t[f"{r} agree"] += bool(a["rubric"].get(r)) == bool(k["judge"]["rubric"][r])
        else:
            t["unmatched n"] += 1
            t["unmatched human found a match (judge/overlap miss)"] += a.get("label_choice") not in (None, "", "none")
    for domain, t in tally.items():
        print(f"\n{domain}")
        for name in ["same_action", *RUBRIC]:
            if t[f"{name} n"]:
                n, agree = t[f"{name} n"], t[f"{name} agree"]
                flag = "  <- disagreement >= 15%: draw more (§4.2)" if (n - agree) >= 0.15 * n else ""
                print(f"  {name}: {agree}/{n}{flag}")
        if t["unmatched n"]:
            print(f"  unmatched steps where the human found a match: "
                  f"{t['unmatched human found a match (judge/overlap miss)']}/{t['unmatched n']}")
    print(f"\nanswered {len(answers)}/{len(key)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("draw")
    sp = sub.add_parser("score")
    sp.add_argument("answers")
    args = ap.parse_args()
    draw() if args.cmd == "draw" else score(args.answers)
