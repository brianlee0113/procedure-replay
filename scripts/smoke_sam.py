"""Smoke test: SAM 3.1 tracks each task prompt on a 30-second clip. PASS if every prompt is found at least once.

    uv run python scripts/smoke_sam.py data/raw/<video>.mp4 --task toner_replacement [--start 20]
"""

import argparse
import statistics
import sys

from pr.client import MetaClient
from pr.license_check import LicenseError, require_allowed
from pr.steps import load_tasks
from pr.track import prepare, track


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("video", help="local path or manifest video_id")
    ap.add_argument("--task", required=True)
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--seconds", type=float, default=30.0)
    args = ap.parse_args()

    prompts = load_tasks()[args.task]["object_prompts"]
    try:
        require_allowed(args.video)
    except LicenseError as e:
        print(f"FAIL license: {e}")
        return 1
    client = MetaClient()
    p = prepare(args.video, client, clip=(args.start, args.seconds))
    timeline = track(args.video, prompts, client, prepared=p)

    print(f"\n{p['video_id']}: {p['n_frames']} frames @ {timeline['fps']} fps, {p['info']['width']}x{p['info']['height']}")
    print(f"{'prompt':<24}{'coverage':>9}{'max inst':>9}{'mean conf':>10}")
    ok = True
    for prompt in prompts:
        t = timeline["prompts"][prompt]
        recs = [r for f in t["frames"].values() for r in f]
        confs = [r["conf"] for r in recs if r["conf"] is not None]
        max_inst = max((len(f) for f in t["frames"].values()), default=0)
        mean_c = f"{statistics.mean(confs):.2f}" if confs else "-"
        print(f"{prompt:<24}{t['coverage']:>8.1f}%{max_inst:>9}{mean_c:>10}")
        ok &= t["coverage"] > 0
    print("\nPASS" if ok else "\nFAIL: at least one prompt was never detected (see 0.0% rows)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
