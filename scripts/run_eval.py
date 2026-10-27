"""Full pipeline over the manifest, scored against data/ground_truth.jsonl.

    uv run python scripts/run_eval.py                 # run missing stages (API calls), then score
    uv run python scripts/run_eval.py --dry-run       # cached checklists/reports only, no API calls
    uv run python scripts/run_eval.py --flags F.json  # score precomputed flags {video_id: [flag, ...]}
    uv run python scripts/run_eval.py --set dev       # dev set (data/ground_truth_dev.jsonl)

Two sets: prompts are tuned on `dev` (flaws injected into other takes); the held-out `test` set is scored to
report results. Prints detected X/N, false flags Y/M, and a per-video table; writes results/summary[_dev].md.
"""

import argparse
import json
import sys
from datetime import datetime

from pr.align import align, keystep_of
from pr.client import RESULTS, MetaClient
from pr.judge import judge
from pr.license_check import ROOT, LicenseError, load_manifest, local_path, require_allowed
from pr.order import keystep_pairs
from pr.score import score_video, summarize
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

    def flags(self, video_id: str, task: str) -> tuple[list[dict], str]:
        checklist = self.checklist(task)
        if checklist is None:
            return [], "no cached checklist"
        cfg = self.tasks[task]
        matches = align(video_id, checklist, None if self.dry_run else self.client, cfg["name"])
        if matches is None:
            return [], "no cached report"
        before = keystep_pairs(task, list(self.manifest.values()), self.exclude)
        return judge(matches, keystep_of(checklist), cfg["keysteps"], before), ""


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
    ap.add_argument("--flags", help="JSON file {video_id: [flags]} to score instead of running the pipeline")
    args = ap.parse_args()

    manifest = {r["video_id"]: r for r in load_manifest()}
    given = json.loads(open(args.flags).read()) if args.flags else None
    ground_truth = load_ground_truth(args.set)
    # Exclude both sets' videos from order-rule learning, so the rules are the same for dev and test.
    pipe = Pipeline(manifest, args.dry_run, {gt["video_id"] for w in GROUND_TRUTH for gt in load_ground_truth(w)})
    rows, skipped = [], []

    for gt in ground_truth:
        vid = gt["video_id"]
        if given is None:
            try:
                row = require_allowed(vid)
            except LicenseError as e:
                skipped.append((vid, str(e)))
                continue
            if not local_path(row).exists():
                skipped.append((vid, f"file missing: {row['local_path']}"))
                continue
            flags, note = pipe.flags(vid, gt["task"])
        else:
            flags, note = given.get(vid, []), "precomputed"
        s = score_video(gt["injected_flaw"], flags, args.tol)
        (RESULTS / "flags").mkdir(parents=True, exist_ok=True)
        (RESULTS / "flags" / f"{vid}.json").write_text(json.dumps(flags, indent=1))
        hit = s["hit"]
        rows.append({"video": vid, "task": gt["task"], "injected": fmt_flaw(gt["injected_flaw"]),
                     "status": s["status"], "flags": s["n_flags"],
                     "hit": f"{hit['type']} step {hit['step']} @ {hit['ts']:.1f}s" if hit else "",
                     "note": note, "score": s})

    summary = summarize([r["score"] for r in rows])
    headers = ["video", "task", "injected", "status", "flags", "hit", "note"]
    widths = {h: max([len(h)] + [len(str(r[h])) for r in rows]) for h in headers}
    print("  ".join(h.ljust(widths[h]) for h in headers))
    for r in rows:
        print("  ".join(str(r[h]).ljust(widths[h]) for h in headers))
    for vid, why in skipped:
        print(f"skipped {vid}: {why}")

    det = f"Detected {summary['detected']}/{summary['n_flawed']}  (target ≥{TARGET_DETECTED}/{TARGET_FLAWED})"
    ff = f"False flags {summary['false_flags']}/{summary['n_clean']}  (target 0/{TARGET_CLEAN})"
    print(f"\n{det}\n{ff}")

    md = [f"# ProcedureReplay evaluation ({args.set} set)", "",
          f"Run {datetime.now().isoformat(timespec='minutes')}, timestamp tolerance ±{args.tol:g}s.", "",
          f"- **{det}**", f"- **{ff}**", "",
          "| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    md += ["| " + " | ".join(str(r[h]) for h in headers) + " |" for r in rows]
    if skipped:
        md += ["", "Skipped:", *[f"- `{v}`: {w}" for v, w in skipped]]
    out = RESULTS / ("summary.md" if args.set == "test" else f"summary_{args.set}.md")
    out.write_text("\n".join(md) + "\n")
    print(f"wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
