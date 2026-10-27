"""Full pipeline over the manifest, scored against data/ground_truth.jsonl.

    uv run python scripts/run_eval.py                 # run missing stages (API calls), then score
    uv run python scripts/run_eval.py --dry-run       # cached checklists/reports only, no API calls
    uv run python scripts/run_eval.py --flags F.json  # score precomputed flags {video_id: [flag, ...]}
    uv run python scripts/run_eval.py --set dev       # dev set (data/ground_truth_dev.jsonl)
    uv run python scripts/run_eval.py --set dev --runs 1,2,3   # three independent reviews per video, + vote

Two sets: prompts are tuned on `dev` (flaws injected into other takes); the held-out `test` set is scored to
report results. Prints detected X/N, false flags Y/M, and a per-video table; writes results/summary[_dev].md.

Every run is also scored as its "first pass" (before the re-check overturned any "not performed"), and with
several runs, as a per-step majority vote. The headline is the vote when there are several runs, else the run.
A video whose report leaves a step unanswered counts as a failure (INCOMPLETE); in --dry-run, a video without
a cached report is skipped, not scored.
"""

import argparse
import json
import sys
from datetime import datetime

from pr.align import align, first_pass, keystep_of, unanswered, vote
from pr.client import RESULTS, MetaClient
from pr.judge import judge
from pr.license_check import ROOT, LicenseError, load_manifest, local_path, require_allowed
from pr.order import keystep_pairs
from pr.score import incomplete, score_video, summarize
from pr.steps import CHECKLISTS, extract_steps, load_tasks

TARGET_DETECTED, TARGET_FLAWED, TARGET_CLEAN = 5, 6, 2


GROUND_TRUTH = {"test": ROOT / "data" / "ground_truth.jsonl", "dev": ROOT / "data" / "ground_truth_dev.jsonl"}


def load_ground_truth(which: str) -> list[dict]:
    path = GROUND_TRUTH[which]
    lines = path.read_text().splitlines() if path.exists() else []
    return [json.loads(l) for l in lines if l.strip()]


class Pipeline:
    """Runs (or loads from cache) checklist -> Muse Spark trainee report -> judge for one trainee video."""

    def __init__(self, manifest: dict, dry_run: bool, eval_ids: set[str]):
        self.manifest, self.dry_run = manifest, dry_run
        # Order rules are learned from correct takes; never from a video under test or its source take.
        self.exclude = eval_ids | {v.split("__")[0] for v in eval_ids}
        self.tasks = load_tasks()
        self._client = None

    @property
    def client(self) -> MetaClient:
        self._client = self._client or MetaClient()
        return self._client

    def checklist(self, task: str) -> dict | None:
        path = CHECKLISTS / f"{task}.json"
        if path.exists():
            return json.loads(path.read_text())
        if self.dry_run:
            return None
        ref = next((r for r in self.manifest.values() if r["task"] == task and r["role"] == "reference"), None)
        if ref is None:
            raise RuntimeError(f"no reference video for task {task} in the manifest")
        return extract_steps(ref["video_id"], task, self.client)

    def matches(self, video_id: str, task: str, run: int) -> tuple[list[dict] | None, str]:
        checklist = self.checklist(task)
        if checklist is None:
            return None, "no cached checklist"
        client = None if self.dry_run else self.client
        found = align(video_id, checklist, client, self.tasks[task]["name"], run)
        if found is None:
            return None, f"no cached report for run {run}"
        if gaps := unanswered(found, checklist):
            return found, f"run {run} has no answer for steps {gaps}"
        return found, ""

    def judge(self, matches: list[dict], task: str) -> list[dict]:
        before = keystep_pairs(task, list(self.manifest.values()), self.exclude)
        return judge(matches, keystep_of(self.checklist(task)), self.tasks[task]["keysteps"], before)


def variants(runs: dict[int, list[dict]]) -> dict[str, list[dict]]:
    out = {}
    for r, ms in runs.items():
        out[f"run {r}"] = ms
        out[f"run {r} first pass"] = first_pass(ms)
    if len(runs) > 1:
        out["vote"] = vote(list(runs.values()))
        out["vote first pass"] = vote([first_pass(ms) for ms in runs.values()])
    return out


def fmt_flaw(flaw: dict) -> str:
    if flaw["type"] == "none":
        return "none"
    steps = ",".join(str(s) for s in flaw["steps"])
    span = f"{flaw['start_ts']:g}s" if flaw["start_ts"] == flaw["end_ts"] else f"{flaw['start_ts']:g}–{flaw['end_ts']:g}s"
    return f"{flaw['type']} step {steps} @ {span}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tol", type=float, default=5.0, help="timestamp tolerance in seconds")
    ap.add_argument("--dry-run", action="store_true", help="use cached results only; no API calls")
    ap.add_argument("--set", choices=list(GROUND_TRUTH), default="test")
    ap.add_argument("--runs", default="1", help="comma-separated run numbers; each is an independent review")
    ap.add_argument("--flags", help="JSON file {video_id: [flags]} to score instead of running the pipeline")
    args = ap.parse_args()
    runs = [int(r) for r in args.runs.split(",")]

    manifest = {r["video_id"]: r for r in load_manifest()}
    given = json.loads(open(args.flags).read()) if args.flags else None
    ground_truth = load_ground_truth(args.set)
    # Exclude both sets' videos from order-rule learning, so the rules are the same for dev and test.
    pipe = Pipeline(manifest, args.dry_run, {gt["video_id"] for w in GROUND_TRUTH for gt in load_ground_truth(w)})
    names = ["precomputed"] if given else list(variants({r: [] for r in runs}))
    headline = names[0] if given or len(runs) == 1 else "vote"
    scores: dict[str, list[dict]] = {n: [] for n in names}
    rows, skipped = [], []

    for gt in ground_truth:
        vid, flaw = gt["video_id"], gt["injected_flaw"]
        status = {}
        if given is None:
            try:
                row = require_allowed(vid)
            except LicenseError as e:
                skipped.append((vid, str(e)))
                continue
            if not local_path(row).exists():
                skipped.append((vid, f"file missing: {row['local_path']}"))
                continue
            found = {r: pipe.matches(vid, gt["task"], r) for r in runs}
            if missing := [note for ms, note in found.values() if ms is None]:
                skipped.append((vid, missing[0]))
                continue
            if bad := [note for _, note in found.values() if note]:
                flags, note = [], "; ".join(bad)
                for n in names:
                    scores[n].append(incomplete(flaw))
                    status[n] = "INCOMPLETE"
            else:
                note = ""
                for n, ms in variants({r: ms for r, (ms, _) in found.items()}).items():
                    s = score_video(flaw, pipe.judge(ms, gt["task"]), args.tol)
                    scores[n].append(s)
                    status[n] = s["status"]
                flags = pipe.judge(variants({r: ms for r, (ms, _) in found.items()})[headline], gt["task"])
        else:
            flags, note = given.get(vid, []), "precomputed"
            scores[headline].append(score_video(flaw, flags, args.tol))
            status[headline] = scores[headline][-1]["status"]
        s = scores[headline][-1]
        (RESULTS / "flags").mkdir(parents=True, exist_ok=True)
        (RESULTS / "flags" / f"{vid}.json").write_text(json.dumps(flags, indent=1))
        hit = s["hit"]
        rows.append({"video": vid, "task": gt["task"], "injected": fmt_flaw(flaw),
                     "status": s["status"], "flags": s["n_flags"], "extra": s["extra"],
                     "hit": f"{hit['type']} step {hit['step']} @ {hit['ts']:.1f}s" if hit else "",
                     "note": note, "by_variant": status})

    def line(n: str) -> tuple[str, str, str]:
        x = summarize(scores[n])
        return (f"Detected {x['detected']}/{x['n_flawed']}  (target ≥{TARGET_DETECTED}/{TARGET_FLAWED})",
                f"False flags {x['false_flags']}/{x['n_clean']}  (target 0/{TARGET_CLEAN})",
                f"Extra flags on flawed videos {x['extra_on_flawed']}")

    headers = ["video", "task", "injected", "status", "flags", "extra", "hit", "note"]
    widths = {h: max([len(h)] + [len(str(r[h])) for r in rows]) for h in headers}
    print("  ".join(h.ljust(widths[h]) for h in headers))
    for r in rows:
        print("  ".join(str(r[h]).ljust(widths[h]) for h in headers))
    for vid, why in skipped:
        print(f"skipped {vid}: {why}")
    print()
    for n in names:
        print(f"{n:>18}:  " + "   ".join(line(n)))

    det, ff, extra = line(headline)
    md = [f"# ProcedureReplay evaluation ({args.set} set)", "",
          f"Run {datetime.now().isoformat(timespec='minutes')}, timestamp tolerance ±{args.tol:g}s, "
          f"review runs {args.runs}, headline: {headline}.", "",
          f"- **{det}**", f"- **{ff}**", f"- {extra}", ""]
    if len(names) > 1:
        md += ["| variant | detected | false flags | extra flags on flawed |", "|---|---|---|---|"]
        for n in names:
            x = summarize(scores[n])
            md.append(f"| {n} | {x['detected']}/{x['n_flawed']} | {x['false_flags']}/{x['n_clean']} "
                      f"| {x['extra_on_flawed']} |")
        md += ["", "Per video:", "", "| video | " + " | ".join(names) + " |", "|" + "---|" * (len(names) + 1)]
        md += [f"| {r['video']} | " + " | ".join(r["by_variant"].get(n, "") for n in names) + " |" for r in rows]
        md += ["", f"Headline ({headline}) details:", ""]
    md += ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    md += ["| " + " | ".join(str(r[h]) for h in headers) + " |" for r in rows]
    if skipped:
        md += ["", "Skipped (not scored):", *[f"- `{v}`: {w}" for v, w in skipped]]
    out = RESULTS / ("summary.md" if args.set == "test" else f"summary_{args.set}.md")
    out.write_text("\n".join(md) + "\n")
    print(f"wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
