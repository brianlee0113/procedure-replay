"""B2–B4 guide evaluation (docs/B0_guide_eval_plan.md §4–7): build guides, judge them, score them, write a summary.

    uv run python scripts/run_guides.py --set iterate                  # B3 rounds (config/splits.yaml)
    uv run python scripts/run_guides.py --set dev --runs 1,2,3         # B2 baseline / before the freeze
    uv run python scripts/run_guides.py --set iterate --no-transcript  # an ablation (one change per round)
    uv run python scripts/run_guides.py --set iterate --dry-run        # score cached results only, no API calls
    uv run python scripts/run_guides.py --videos 07_u15_r04_c_01       # a few videos
    uv run python scripts/run_guides.py --set test --i-am-at-b4        # test, once, frozen configuration

Results: results/guide_runs/<config>/run<k>/<video>/{guide,raw,judge}.json and the same under
uniform+captions/ for the baseline. guide.json and raw.json are written once and never overwritten; delete
the folder to rebuild. Summary: results/summary_guides_<set>.md.
"""

import argparse
import csv
import functools
import json
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import yaml

from pr.build import Config, build_guide
from pr.client import RESULTS, MetaClient
from pr.guide_eval import (Pred, fine_units, load_labels, load_merges, median_label_length, preds_of, score_video,
                           temporal_iou_f1, uniform_steps)
from pr.guide_judge import RUBRIC, judge_guide
from pr.guides import Guide
from pr.license_check import ROOT, load_manifest
from pr.transcribe import TRANSCRIPTS

RUNS = RESULTS / "guide_runs"
SPLITS = yaml.safe_load((ROOT / "config" / "splits.yaml").read_text())
CATEGORY = {"pc_repair": "repair_maintenance", "drill_bit": "workshop_tools", "home_cooking": "cooking"}  # set before B2
DOMAIN = {"pc_repair": "PC repair", "drill_bit": "Drill bit", "home_cooking": "Omelet"}


def participant(row: dict) -> str:
    return row["creator"].rsplit(",", 1)[-1].strip().removeprefix("participant ")


def videos_of(which: str) -> list[tuple[str, str]]:
    """[(video_id, task)] for a set: iterate, dev or test (labelled originals only)."""
    manifest = {r["video_id"]: r for r in load_manifest()}
    labelled = {p.stem for p in (ROOT / "data" / "keysteps").glob("*.json")}
    out = []
    for task, split in SPLITS.items():
        if task == "narrated":
            continue
        people = set(split["test" if which == "test" else "dev"])
        for vid in sorted(labelled):
            row = manifest.get(vid)
            if not row or row["task"] != task or participant(row) not in people:
                continue
            correct = "_c_" in vid or (task == "home_cooking" and not is_mistake_take(vid))
            if which != "iterate" or correct or vid in split["iterate_mistakes"]:
                out.append((vid, task))
    narrated = SPLITS["narrated"]["test" if which == "test" else "dev"] or []
    return out + [(v, task_of(v, manifest)) for v in narrated]


@functools.cache
def omelet_mistake_takes() -> set[str]:
    lines = (ROOT / "data" / "captaincook_mistakes.jsonl").read_text().splitlines()
    return {json.loads(l)["video_id"] for l in lines if l.strip()}


def is_mistake_take(vid: str) -> bool:
    return vid in omelet_mistake_takes()


def task_of(vid: str, manifest: dict) -> str:
    return manifest[vid]["task"]


@functools.cache
def domain_length(task: str) -> float:
    """Uniform baseline part length: median label length over the task's dev takes (never test labels)."""
    dev = [v for v, t in videos_of("dev") if t == task]
    return median_label_length(dev)


def write_once(path, data) -> None:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2))


def transcript_of(video_id: str) -> dict | None:
    path = TRANSCRIPTS / f"{video_id}.json"
    return json.loads(path.read_text()) if path.exists() else None


def run_one(video_id: str, task: str, cfg: Config, run: int, baseline: bool, dry: bool, client) -> dict | None:
    folder = RUNS / ("uniform+captions" if baseline else cfg.label()) / f"run{run}" / video_id
    if not (folder / "guide.json").exists():
        if dry:
            return None
        length = domain_length(task)
        guide, raw = build_guide(video_id, f"eval_{video_id}", cfg, client,
                                 segments=(lambda d: uniform_steps(d, length)) if baseline else None)
        write_once(folder / "raw.json", raw)
        write_once(folder / "guide.json", guide.model_dump())
    guide = Guide.model_validate_json((folder / "guide.json").read_text())
    labels, merges = load_labels(video_id), load_merges(task)
    if dry and not (folder / "judge.json").exists():
        return None
    judgments = judge_guide(guide, labels, merges, folder / "judge.json", client,
                            transcript_of(video_id) if cfg.transcript else None, cfg.model)
    score = score_video(preds_of(guide), labels, merges, judgments)
    matched = [judgments[int(i)]["rubric"] for i in score["matches"]]
    raw = json.loads((folder / "raw.json").read_text())
    quotes_given = sum(1 for s in raw["steps"] if s["quote_text"].strip() or s["quote_turn_ids"])
    return {
        "video": video_id, "task": task, "run": run, "score": score,
        "rubric_all": [all(r[k] for k in RUBRIC) for r in matched],
        "category": guide.category == CATEGORY.get(task),
        "category_top2": CATEGORY.get(task) in [guide.category, *guide.category_alternatives[:1]],
        "quotes_given": quotes_given, "quotes_dropped": len(guide.provenance.get("dropped_quotes", [])),
        "steps": len(guide.steps),
    }


def uniform_score(video_id: str, task: str) -> dict:
    """Uniform baseline (no text): temporal IoU F1 only."""
    labels = load_labels(video_id)
    duration = max(l["end"] for l in labels)  # labels end before the video does; close enough for a weak baseline
    steps = uniform_steps(duration, domain_length(task))
    preds = [Pred(i, a, b, a, b) for i, (a, b) in enumerate(steps, 1)]
    return temporal_iou_f1(preds, fine_units(labels))


def pooled(rows: list[dict], key: str) -> float | None:
    tp = sum(r["score"][key]["tp"] for r in rows)
    n_pred = sum(r["score"][key]["n_pred"] for r in rows)
    n_units = sum(r["score"][key]["n_units"] for r in rows)
    if not n_pred or not n_units:
        return None
    p, rc = tp / n_pred, tp / n_units
    return 2 * p * rc / (p + rc) if p + rc else 0.0


def fmt(x, digits=2) -> str:
    return "–" if x is None else f"{x:.{digits}f}"


def spread(values: list[float | None]) -> str:
    v = [x for x in values if x is not None]
    if not v:
        return "–"
    return f"{statistics.mean(v):.2f} ({min(v):.2f}–{max(v):.2f})" if len(v) > 1 else f"{v[0]:.2f}"


def summarize(which: str, cfg: Config, runs: list[int], main: list[dict], base: list[dict], cost: float) -> str:
    lines = [f"# Guide evaluation ({which} set)", "",
             f"Run {datetime.now().isoformat(timespec='minutes')}, config `{cfg.label()}`, runs {runs}, "
             f"judge = builder model (§4.2; human check pending). Means over runs, (min–max) across runs. "
             f"Step hit F1 is pooled over the domain's videos. Approx. API cost of this invocation: ${cost:.2f}.", ""]
    head = ("| domain | videos | step hit F1 | uniform+captions | paired diff (wins) | merge-tolerant F1 | IoU F1 | "
            "uniform IoU F1 | granularity | boundary start/end s | length ratio | clip focus | rubric all 4 | "
            "category top-1 / top-2 | quotes given / dropped |")
    lines += [head, "|" + "---|" * (head.count("|") - 1)]
    for task in DOMAIN:
        m = [r for r in main if r["task"] == task]
        if not m:
            continue
        b = [r for r in base if r["task"] == task]
        vids = sorted({r["video"] for r in m})
        per_run = lambda rows, key: [pooled([r for r in rows if r["run"] == k], key) for k in runs]
        diffs, wins = [], 0
        for v in vids:
            d = [mr["score"]["step_hit"]["f1"] - br["score"]["step_hit"]["f1"] for k in runs
                 for mr in m if mr["video"] == v and mr["run"] == k for br in b if br["video"] == v and br["run"] == k]
            if d:
                diffs.append(statistics.mean(d))
                wins += statistics.mean(d) > 0
        avg = lambda key, sub: [r["score"][key][sub] for r in m if r["score"][key][sub] is not None]
        ratios = [r["score"]["granularity"] for r in m if r["score"]["granularity"]]
        focus = [r["score"]["clip_focus"] for r in m if r["score"]["clip_focus"] is not None]
        rubric = [x for r in m for x in r["rubric_all"]]
        uni = [uniform_score(v, task)["f1"] for v in vids]
        lines.append("| " + " | ".join([
            DOMAIN[task], str(len(vids)), spread(per_run(m, "step_hit")), spread(per_run(b, "step_hit")) if b else "–",
            f"{statistics.mean(diffs):+.2f} ({wins}/{len(diffs)})" if diffs else "–",
            spread(per_run(m, "merge_tolerant")), spread(per_run(m, "temporal_iou")), fmt(statistics.mean(uni)),
            fmt(statistics.median(ratios)),
            f"{fmt(statistics.median(avg('boundary', 'start_s')) if avg('boundary', 'start_s') else None, 1)} / "
            f"{fmt(statistics.median(avg('boundary', 'end_s')) if avg('boundary', 'end_s') else None, 1)}",
            fmt(statistics.median(avg('length_ratio', 'median')) if avg('length_ratio', 'median') else None),
            fmt(statistics.mean(focus) if focus else None),
            f"{sum(rubric)}/{len(rubric)}",
            f"{sum(r['category'] for r in m)}/{len(m)} / {sum(r['category_top2'] for r in m)}/{len(m)}",
            f"{sum(r['quotes_given'] for r in m)} / {sum(r['quotes_dropped'] for r in m)}",
        ]) + " |")
    lines += ["", "Per video, step hit F1 per run (main | uniform+captions):", "",
              "| video | " + " | ".join(f"run {k}" for k in runs) + " |", "|---|" + "---|" * len(runs)]
    for v in sorted({r["video"] for r in main}):
        cells = []
        for k in runs:
            mr = next((r for r in main if r["video"] == v and r["run"] == k), None)
            br = next((r for r in base if r["video"] == v and r["run"] == k), None)
            cells.append(f"{fmt(mr['score']['step_hit']['f1']) if mr else '–'} | {fmt(br['score']['step_hit']['f1']) if br else '–'}"
                         .replace(" | ", " / "))
        lines.append(f"| {v} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def cost_since(t0: str) -> float:
    with open(RESULTS / "costs.csv") as f:
        return sum(float(r["est_usd"]) for r in csv.DictReader(f) if r["ts"] >= t0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", choices=["iterate", "dev", "test"], default="iterate")
    ap.add_argument("--videos", help="comma-separated video ids instead of a set")
    ap.add_argument("--runs", default="1")
    ap.add_argument("--no-transcript", action="store_true")
    ap.add_argument("--no-on-screen-text", action="store_true")
    ap.add_argument("--audio", action="store_true")
    ap.add_argument("--seeded", action="store_true", help="give the expert step names (ablation 2)")
    ap.add_argument("--model")
    ap.add_argument("--no-baseline", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--i-am-at-b4", action="store_true", help="required for --set test")
    args = ap.parse_args()
    if args.set == "test" and not args.i_am_at_b4:
        sys.exit("The test set is run once, at B4, with the frozen configuration (B0 plan §5). Pass --i-am-at-b4.")
    if args.seeded:
        sys.exit("--seeded needs per-task step names; not wired yet")

    cfg = Config(transcript=not args.no_transcript, on_screen_text=not args.no_on_screen_text, audio=args.audio,
                 model=args.model)
    runs = [int(r) for r in args.runs.split(",")]
    manifest = {r["video_id"]: r for r in load_manifest()}
    todo = ([(v, task_of(v, manifest)) for v in args.videos.split(",")] if args.videos else videos_of(args.set))
    client = None if args.dry_run else MetaClient()
    t0 = datetime.now(timezone.utc).isoformat(timespec="seconds")
    kinds = [False] if args.no_baseline else [False, True]
    print(f"{len(todo)} videos × runs {runs} × {'main' if args.no_baseline else 'main + baseline'} "
          f"= {len(todo) * len(runs) * len(kinds)} jobs")

    def work(video):
        """All runs of one video in one thread, so its proxy and transcript are made once, not raced."""
        v, t = video
        out = []
        for k in runs:
            for base in kinds:
                try:
                    r = run_one(v, t, cfg, k, base, args.dry_run, client)
                    print(f"  {'base' if base else 'main'} run{k} {v}: " +
                          (f"step hit F1 {r['score']['step_hit']['f1']:.2f}" if r else "not cached"), flush=True)
                    out.append((base, r))
                except Exception as e:  # one failed video must not stop a long run; it is listed at the end
                    print(f"  FAILED {'base' if base else 'main'} run{k} {v}: {type(e).__name__}: {e}", flush=True)
                    out.append((base, {"failed": v}))
        return out

    with ThreadPoolExecutor(args.workers) as pool:
        results = [r for per_video in pool.map(work, todo) for r in per_video]
    failed = [r["failed"] for _, r in results if r and "failed" in r]
    main_rows = [r for base, r in results if r and not base and "failed" not in r]
    base_rows = [r for base, r in results if r and base and "failed" not in r]
    text = summarize(args.videos and "selected" or args.set, cfg, runs, main_rows, base_rows, cost_since(t0))
    if failed:
        text += f"\nFailed (not scored): {', '.join(sorted(set(failed)))}\n"
    out = RESULTS / f"summary_guides_{'selected' if args.videos else args.set}.md"
    out.write_text(text)
    print(text)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
