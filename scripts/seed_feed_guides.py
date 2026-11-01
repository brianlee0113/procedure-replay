"""Fill the app's Feed with guides built from the downloaded CC BY first-person videos (B5).

Each video in data/feed_candidates.csv that is downloaded under data/raw/narrated/ goes through the same builder
and configuration as an app recording (server.APP_BUILD_CONFIG), then is published as Public. The author is the
video's real creator (channel name), credited "YouTube · CC BY" — never a sample persona, since they filmed it.
Clips are cut ahead so the step player doesn't wait.

    uv run python scripts/seed_feed_guides.py --dry-run        # list what would be built
    uv run python scripts/seed_feed_guides.py --budget 3       # build, stop starting new ones past $3

Skips videos that already have a guide (guide id feed_<hash of video id>) and anything in a test split, which must
not reach the model before B4. Calls the Meta API.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import yaml

from pr import build, guides
from pr.client import RESULTS
from pr.license_check import ROOT, find_row
from pr.server import APP_BUILD_CONFIG

CANDIDATES = ROOT / "data/feed_candidates.csv"
NARRATED = ROOT / "data/raw/narrated"
COSTS = RESULTS / "costs.csv"


def guide_id(video_id: str) -> str:
    return "feed_" + hashlib.sha1(video_id.encode()).hexdigest()[:10]


def author_id(creator: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", creator.lower()).strip("-") or "creator"


def test_videos() -> set[str]:
    """Video ids named in a test split (the narrated split lists videos; dataset splits are participants)."""
    splits = yaml.safe_load((ROOT / "config/splits.yaml").read_text())
    named = set((splits.get("narrated") or {}).get("test") or [])
    # Creators held out for the narrated test set (splits.yaml comments): never sent before B4.
    return named | {"yt_P-pHllvP0wo"}


def spent() -> float:
    if not COSTS.exists():
        return 0.0
    with COSTS.open() as f:
        return sum(float(r["est_usd"] or 0) for r in csv.DictReader(f))


def todo() -> list[dict]:
    held_out = test_videos()
    out = []
    with CANDIDATES.open() as f:
        for row in csv.DictReader(f):
            vid = row["video_id"]
            if not (NARRATED / f"{vid}.mp4").exists() or vid in held_out:
                continue
            if (guides.GUIDES / guide_id(vid) / "guide.json").exists():
                continue
            out.append(row)
    return out


def build_one(row: dict) -> tuple[str, str]:
    vid = row["video_id"]
    gid = guide_id(vid)
    creator = find_row(vid)["creator"].split(" (")[0]
    guide, raw = build.build_guide(vid, gid, cfg=APP_BUILD_CONFIG)
    guides.write_json(guides.guide_dir(gid) / "raw.json", raw)
    meta = guides.Meta(author=author_id(creator), author_name=creator, author_role="YouTube · CC BY",
                       visibility="public", published_at=guides.now())
    guides.save(guide, meta)
    guides.precut(guide)
    return gid, f"{guide.title} ({len(guide.steps)} steps, {guide.category})"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=float, default=3.0, help="stop starting new builds once this run spent this much (USD)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rows = todo()
    print(f"{len(rows)} videos to build")
    for r in rows:
        print(f"  {r['video_id']}  {r['category']:<20} {int(r['duration_s']):>5}s  {r['creator']}")
    if args.dry_run or not rows:
        return

    start = spent()
    lock = threading.Lock()
    stop = threading.Event()

    def guarded(row: dict):
        if stop.is_set():
            return row["video_id"], None
        result = build_one(row)
        with lock:
            used = spent() - start
            if used >= args.budget:
                stop.set()
        return row["video_id"], result

    with ThreadPoolExecutor(args.workers) as pool:
        futures = {pool.submit(guarded, r): r for r in rows}
        for fut in as_completed(futures):
            vid = futures[fut]["video_id"]
            try:
                _, result = fut.result()
                print(f"{vid}: " + (f"{result[0]}  {result[1]}" if result else "skipped (budget reached)"), flush=True)
            except Exception as e:  # one bad video shouldn't stop the rest
                print(f"{vid}: FAILED {type(e).__name__}: {e}", flush=True)
    print(f"spent this run: ${spent() - start:.3f}")


if __name__ == "__main__":
    main()
