"""Smoke test: Muse Spark returns an ordered step list with start/end timestamps for a full reference video.

    uv run python scripts/smoke_steps.py data/raw/<reference>.mp4 --task toner_replacement
"""

import argparse
import sys

from pr.client import MetaClient
from pr.frames import fmt_ts
from pr.license_check import LicenseError, require_allowed
from pr.steps import CHECKLISTS, extract_steps, load_tasks, validate


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("video", help="local path or manifest video_id")
    ap.add_argument("--task", required=True)
    args = ap.parse_args()

    try:
        require_allowed(args.video)
    except LicenseError as e:
        print(f"FAIL license: {e}")
        return 1
    checklist = extract_steps(args.video, args.task, MetaClient())

    print(f"\n{checklist['reference_video']} ({checklist['duration']:.1f}s): {checklist['task_summary']}")
    for s in checklist["steps"]:
        print(f"  {s['index']:>2}. {fmt_ts(s['start_s'])}–{fmt_ts(s['end_s'])}  {s['title']}  [{', '.join(s['key_objects'])}]")
    problems = validate(checklist, checklist["duration"], load_tasks()[args.task]["expected_steps"])
    print(f"\nsaved {CHECKLISTS / (args.task + '.json')}")
    if problems:
        print("FAIL:\n  " + "\n  ".join(problems))
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
