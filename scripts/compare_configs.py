"""Compare guide configurations on one set against a reference configuration, from stored results (no API calls).

    uv run python scripts/compare_configs.py --set iterate --ref tr-ost-mute tr-noost-mute tr-ost-audio tr-noost-audio

Per config and domain: pooled step hit precision / recall / F1 (judged), temporal IoU F1 (judge-free), steps per
guide, the run-to-run spread, and per video the 3-run mean difference against the reference (wins / losses, sign
test, bootstrap 95% interval over videos), also by participant. Missing guide or judge files are counted as
missing, never scored. The reference's own run-to-run noise is shown so a difference can be read against it.
"""

import argparse
import json
import math
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

from pr.client import RESULTS
from pr.guide_eval import load_labels, load_merges, preds_of, score_video
from pr.guides import Guide

sys.path.insert(0, str(RESULTS.parent / "scripts"))
from run_guides import DOMAIN, RUNS, load_manifest, participant, videos_of  # noqa: E402

RUN_IDS = [1, 2, 3]


def score_one(cfg: str, run: int, video: str, task: str) -> dict | None:
    folder = RUNS / cfg / f"run{run}" / video
    if not (folder / "guide.json").exists():
        return None
    guide = Guide.model_validate_json((folder / "guide.json").read_text())
    path = folder / "judge.json"
    # no judge file: no step had a candidate label, so the judge was never called
    judge = {int(i): v for i, v in json.loads(path.read_text())["steps"].items()} if path.exists() else {}
    s = score_video(preds_of(guide), load_labels(video), load_merges(task), judge)
    return {"hit": s["step_hit"], "iou": s["temporal_iou"], "steps": len(guide.steps)}


def prf(rows: list[dict], key: str) -> tuple[float, float, float] | None:
    tp = sum(r[key]["tp"] for r in rows)
    n_pred = sum(r[key]["n_pred"] for r in rows)
    n_units = sum(r[key]["n_units"] for r in rows)
    if not n_pred or not n_units:
        return None
    p, r = tp / n_pred, tp / n_units
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)


def sign_test(wins: int, losses: int) -> float:
    n = wins + losses
    if not n:
        return 1.0
    k = min(wins, losses)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def bootstrap(diffs: list[float], n: int = 5000, seed: int = 0) -> tuple[float, float]:
    rng = random.Random(seed)
    means = sorted(statistics.mean(rng.choices(diffs, k=len(diffs))) for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n)]


def f(x, d=2) -> str:
    return "–" if x is None else f"{x:.{d}f}"


def span(xs: list[float]) -> str:
    return f"{min(xs):.2f}–{max(xs):.2f}" if xs else "–"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="iterate")
    ap.add_argument("--ref", default="tr-ost-mute")
    ap.add_argument("configs", nargs="+")
    args = ap.parse_args()
    manifest = {r["video_id"]: r for r in load_manifest()}
    videos = videos_of(args.set)
    cfgs = [args.ref] + [c for c in args.configs if c != args.ref]
    scores = {c: {(v, k): score_one(c, k, v, t) for v, t in videos for k in RUN_IDS} for c in cfgs}
    out = [f"# Config comparison ({args.set} set, {len(videos)} videos × runs {RUN_IDS}, reference `{args.ref}`)", ""]

    out += ["## Completeness", "", "| config | scored runs | missing |", "|---|---|---|"]
    for c in cfgs:
        missing = [f"{v} run{k}" for (v, k), s in scores[c].items() if s is None]
        out.append(f"| `{c}` | {len(scores[c]) - len(missing)}/{len(scores[c])} | {', '.join(missing[:12]) + (f' … (+{len(missing) - 12})' if len(missing) > 12 else '') or '–'} |")

    out += ["", "## Pooled per domain (all scored runs)", "",
            "Step hit = judged (Muse Spark); temporal IoU F1 = judge-free. Spread = min–max of the pooled F1 across runs.", "",
            "| domain | config | step hit P | R | F1 | F1 spread | IoU F1 | steps / guide |", "|---|---|---|---|---|---|---|---|"]
    for task in DOMAIN:
        vids = [v for v, t in videos if t == task]
        for c in cfgs:
            rows = [s for (v, k), s in scores[c].items() if s and v in vids]
            hit, iou = prf(rows, "hit"), prf(rows, "iou")
            per_run = [prf([s for (v, k), s in scores[c].items() if s and v in vids and k == run], "hit") for run in RUN_IDS]
            spread = [x[2] for x in per_run if x]
            out.append(f"| {DOMAIN[task]} ({len(vids)}) | `{c}` | {f(hit and hit[0])} | {f(hit and hit[1])} | **{f(hit and hit[2])}** | "
                       f"{span(spread)} | {f(iou and iou[2])} | {f(statistics.mean(r['steps'] for r in rows) if rows else None, 1)} |")

    def video_mean(c: str, v: str, key: str) -> float | None:
        xs = [scores[c][(v, k)][key]["f1"] for k in RUN_IDS if scores[c][(v, k)]]
        return statistics.mean(xs) if xs else None

    out += ["", "## Reference noise", "",
            f"Per video, the standard deviation of step hit F1 across the 3 runs of `{args.ref}` (median over videos), and the "
            "pooled F1 difference between two halves of the reference's own runs (run 1 vs run 2) — a config difference "
            "smaller than this is not distinguishable from rerunning the same config.", "",
            "| domain | median per-video SD | run 1 vs run 2 pooled F1 |", "|---|---|---|"]
    for task in DOMAIN:
        vids = [v for v, t in videos if t == task]
        sds = [statistics.stdev(xs) for v in vids if len(xs := [scores[args.ref][(v, k)]["hit"]["f1"] for k in RUN_IDS if scores[args.ref][(v, k)]]) > 1]
        r1 = prf([scores[args.ref][(v, 1)] for v in vids if scores[args.ref][(v, 1)]], "hit")
        r2 = prf([scores[args.ref][(v, 2)] for v in vids if scores[args.ref][(v, 2)]], "hit")
        out.append(f"| {DOMAIN[task]} | {statistics.median(sds):.2f} | {r1[2]:.2f} vs {r2[2]:.2f} ({r1[2] - r2[2]:+.2f}) |")

    for key, name in [("hit", "step hit F1 (judged)"), ("iou", "temporal IoU F1 (judge-free)")]:
        out += ["", f"## Paired per-video difference vs `{args.ref}`: {name}", "",
                "3-run mean per video, config minus reference. Wins/losses ignore |diff| < 0.01. Sign test two-sided; "
                "interval = bootstrap 95% over videos.", "",
                "| domain | config | mean diff | 95% interval | wins / losses / ties | sign test p |", "|---|---|---|---|---|---|"]
        for task in DOMAIN:
            vids = [v for v, t in videos if t == task]
            for c in cfgs[1:]:
                d = [a - b for v in vids if (a := video_mean(c, v, key)) is not None and (b := video_mean(args.ref, v, key)) is not None]
                if not d:
                    continue
                w, l = sum(x >= 0.01 for x in d), sum(x <= -0.01 for x in d)
                lo, hi = bootstrap(d)
                out.append(f"| {DOMAIN[task]} | `{c}` | {statistics.mean(d):+.3f} | {lo:+.3f} … {hi:+.3f} | {w} / {l} / {len(d) - w - l} | {sign_test(w, l):.2f} |")

    out += ["", "## By participant: step hit F1 3-run mean difference vs reference (mean over the participant's videos)", "",
            "| domain | participant | videos | " + " | ".join(f"`{c}`" for c in cfgs[1:]) + " |", "|---|---|---|" + "---|" * (len(cfgs) - 1)]
    groups = defaultdict(list)
    for v, t in videos:
        groups[(t, participant(manifest[v]))].append(v)
    for (t, person), vids in sorted(groups.items()):
        cells = []
        for c in cfgs[1:]:
            d = [a - b for v in vids if (a := video_mean(c, v, "hit")) is not None and (b := video_mean(args.ref, v, "hit")) is not None]
            cells.append(f"{statistics.mean(d):+.2f}" if d else "–")
        out.append(f"| {DOMAIN[t]} | {person} | {len(vids)} | " + " | ".join(cells) + " |")

    out += ["", "## Per video: step hit F1, 3-run mean", "", "| video | " + " | ".join(f"`{c}`" for c in cfgs) + " |",
            "|---|" + "---|" * len(cfgs)]
    for v, t in videos:
        out.append(f"| {v} | " + " | ".join(f(video_mean(c, v, "hit")) for c in cfgs) + " |")
    print("\n".join(out))


if __name__ == "__main__":
    main()
