"""Smoke test: the same SAM prompts work on two videos of the same task by different creators.
Flags (FAIL) any prompt with < 50% frame coverage in either video.

    uv run python scripts/smoke_cross_creator.py data/raw/<a>.mp4 data/raw/<b>.mp4 --task toner_replacement [--seconds 60]
"""

import argparse
import sys

from pr.client import MetaClient
from pr.license_check import LicenseError, require_allowed
from pr.steps import load_tasks
from pr.track import prepare, track

MIN_COVERAGE = 50.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("video_a")
    ap.add_argument("video_b")
    ap.add_argument("--task", required=True)
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--seconds", type=float, default=None, help="clip length; default is the full video")
    args = ap.parse_args()

    try:
        rows = [require_allowed(v) for v in (args.video_a, args.video_b)]
    except LicenseError as e:
        print(f"FAIL license: {e}")
        return 1
    if rows[0]["creator"] == rows[1]["creator"]:
        print(f"WARN: both videos are by {rows[0]['creator']!r}; this test needs different creators")

    prompts = load_tasks()[args.task]["object_prompts"]
    client = MetaClient()
    clip = (args.start, args.seconds) if args.seconds else None
    timelines = [track(v, prompts, client, prepared=prepare(v, client, clip=clip))
                 for v in (args.video_a, args.video_b)]

    ids = [t["video_id"] for t in timelines]
    print(f"\n{'prompt':<24}{ids[0][:22]:>24}{ids[1][:22]:>24}")
    low = []
    for prompt in prompts:
        cov = [t["prompts"][prompt]["coverage"] for t in timelines]
        mark = "  <50%" if min(cov) < MIN_COVERAGE else ""
        print(f"{prompt:<24}{cov[0]:>23.1f}%{cov[1]:>23.1f}%{mark}")
        low += [prompt] if mark else []
    if low:
        print(f"\nFAIL: coverage < {MIN_COVERAGE:.0f}% for: {', '.join(low)} — reword these prompts or drop them")
        return 1
    print("\nPASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
