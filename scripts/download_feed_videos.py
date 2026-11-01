"""Download more feed candidates (data/feed_candidates.csv) and register them: manifest row + ATTRIBUTION entry.

Takes candidates labelled usable (English narration, fully first person) that aren't downloaded yet, skips the
creators held out for the narrated test set, re-checks the license in YouTube's own metadata (must say Creative
Commons), and saves a ≤720p MP4 under data/raw/narrated/. A video whose license doesn't check out is skipped.

    uv run python scripts/download_feed_videos.py --dry-run
    uv run python scripts/download_feed_videos.py --max-minutes 20

Then scripts/seed_feed_guides.py builds guides from whatever is downloaded.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor

from pr.license_check import ROOT

CANDIDATES = ROOT / "data/feed_candidates.csv"
NARRATED = ROOT / "data/raw/narrated"
MANIFEST = ROOT / "data/manifest.csv"
ATTRIBUTION = ROOT / "ATTRIBUTION.md"
# Narrated test creators (config/splits.yaml, docs/B0_guide_eval_plan.md §3.2): never sent before B4.
HELD_OUT_CREATORS = ("Abraham Moreno", "Ultra Plumbing")
CATEGORY_LABEL = {"cooking": "Cooking", "crafts": "Crafts", "repair_maintenance": "Repair & maintenance",
                  "cleaning_household": "Cleaning & household", "electronics": "Electronics", "assembly": "Assembly",
                  "workshop_tools": "Workshop tools", "other": "Other"}


def slug(title: str) -> str:
    words = re.sub(r"[^a-z0-9 ]+", " ", title.lower()).split()
    return "_".join(words[:5]) or "feed_video"


def pending(max_minutes: float) -> list[dict]:
    out = []
    with CANDIDATES.open() as f:
        for row in csv.DictReader(f):
            if not row["label"].startswith("학습"):
                continue
            if any(c in row["creator"] for c in HELD_OUT_CREATORS):
                continue
            if (NARRATED / f"{row['video_id']}.mp4").exists() or int(row["duration_s"]) > max_minutes * 60:
                continue
            out.append(row)
    return out


def fetch(row: dict) -> tuple[dict, str | None]:
    """Download one video after re-checking its license. Returns (row, problem or None)."""
    vid, url = row["video_id"], row["source_url"]
    try:
        info = json.loads(subprocess.run(["yt-dlp", "-J", "--no-warnings", url], check=True, capture_output=True,
                                         text=True, timeout=120).stdout)
    except Exception as e:
        return row, f"metadata: {type(e).__name__}"
    lic = (info.get("license") or "").lower()
    if "creative commons" not in lic:
        return row, f"license in metadata is {info.get('license')!r}"
    out = NARRATED / f"{vid}.mp4"
    try:
        subprocess.run(["yt-dlp", "--no-warnings", "-q", "-f",
                        "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720][ext=mp4]/b[height<=720]",
                        "--merge-output-format", "mp4", "-o", str(out), url],
                       check=True, capture_output=True, text=True, timeout=900)
    except Exception as e:
        out.unlink(missing_ok=True)
        return row, f"download: {type(e).__name__}"
    row["_channel"] = info.get("channel_url") or row["channel_url"]
    return row, None


def register(row: dict) -> None:
    vid, creator, channel = row["video_id"], row["creator"], row.get("_channel") or row["channel_url"]
    with MANIFEST.open("a", newline="") as f:
        csv.writer(f).writerow([vid, slug(row["title"]), f"{creator} (YouTube, {channel})", row["source_url"],
                                "CC-BY-3.0", "reference", f"data/raw/narrated/{vid}.mp4"])
    m, s = divmod(int(row["duration_s"]), 60)
    with ATTRIBUTION.open("a") as f:
        f.write(f"\n### {vid}\n- Title: {row['title']}\n- Creator: {creator}, {channel}\n- Source: {row['source_url']}\n"
                f"- License: CC BY 3.0 (https://creativecommons.org/licenses/by/3.0/)\n"
                f"- Camera: first person (hands doing the task); English narration. {m}:{s:02d}. "
                f"Feed sample ({CATEGORY_LABEL.get(row['category'], 'Other')})\n- Role: reference\n- Edits:\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-minutes", type=float, default=20)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rows = pending(args.max_minutes)
    print(f"{len(rows)} candidates to download")
    for r in rows:
        print(f"  {r['video_id']}  {r['category']:<20} {int(r['duration_s']):>5}s  {r['creator']}")
    if args.dry_run:
        return
    ok = 0
    with ThreadPoolExecutor(args.workers) as pool:
        for row, problem in pool.map(fetch, rows):
            if problem:
                print(f"{row['video_id']}: skipped ({problem})", flush=True)
                continue
            register(row)  # main thread only, so the CSV and ATTRIBUTION appends don't interleave
            ok += 1
            print(f"{row['video_id']}: downloaded", flush=True)
    print(f"downloaded {ok} of {len(rows)}")


if __name__ == "__main__":
    main()
