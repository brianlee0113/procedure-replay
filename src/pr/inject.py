"""Inject a known flaw into a trainee video by editing, so ground truth is exact.

    uv run python -m pr.inject cut  --video ID --start 42 --end 55.5 --steps 4
    uv run python -m pr.inject swap --video ID --a 20,35 --b 50,70 --steps 2,4
    uv run python -m pr.inject none --video ID          # register an unedited trainee video

Each edit writes data/edited/<new_id>.mp4 and appends:
- a manifest row (same creator / source / license as the source video, role trainee),
- a ground_truth row whose start_ts / end_ts are in the EDITED video's timeline
  (cut: both are the splice point; swap: the span now holding the two moved blocks),
- an edit line under the source video's entry in ATTRIBUTION.md.
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from pr.frames import probe, run
from pr.license_check import ROOT, LicenseError, append_manifest_row, load_manifest, local_path, require_allowed

EDITED = ROOT / "data" / "edited"
GROUND_TRUTH = ROOT / "data" / "ground_truth.jsonl"
ATTRIBUTION = ROOT / "ATTRIBUTION.md"


def splice(src: Path, segments: list[tuple[float, float]], out: Path, has_audio: bool) -> None:
    """Concatenate [start, end) segments of src in the given order, frame-accurately (re-encode)."""
    parts, labels = [], []
    for i, (s, e) in enumerate(segments):
        parts.append(f"[0:v]trim=start={s:.3f}:end={e:.3f},setpts=PTS-STARTPTS[v{i}]")
        labels.append(f"[v{i}]")
        if has_audio:
            parts.append(f"[0:a]atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS[a{i}]")
            labels.append(f"[a{i}]")
    parts.append(f"{''.join(labels)}concat=n={len(segments)}:v=1:a={int(has_audio)}[v]" + ("[a]" if has_audio else ""))
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-filter_complex", ";".join(parts), "-map", "[v]"]
    if has_audio:
        cmd += ["-map", "[a]", "-c:a", "aac"]
    cmd += ["-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
    out.parent.mkdir(parents=True, exist_ok=True)
    run(cmd)


def step_list(task: str) -> list[str]:
    """Step titles from the task's reference checklist, if smoke_steps / run_eval has produced it."""
    path = ROOT / "results" / "checklists" / f"{task}.json"
    return [s["title"] for s in json.loads(path.read_text())["steps"]] if path.exists() else []


def log_attribution(source_id: str, line: str) -> None:
    text = ATTRIBUTION.read_text()
    heading = f"### {source_id}"
    lines = text.splitlines()
    starts = [i for i, l in enumerate(lines) if l.strip() == heading]
    if not starts:
        lines += ["", f"{heading}", "- Title / Creator / Source / License: TODO — entry missing, fill in", "- Edits:"]
        insert_at = len(lines)
    else:
        insert_at = next((j for j in range(starts[-1] + 1, len(lines))
                          if lines[j].startswith(("### ", "## ", "<!--"))), len(lines))
        while insert_at > starts[-1] + 1 and not lines[insert_at - 1].strip():
            insert_at -= 1
    lines.insert(insert_at, f"  - {line}")
    ATTRIBUTION.write_text("\n".join(lines) + "\n")


def parse_range(s: str) -> tuple[float, float]:
    a, b = (float(x) for x in s.split(","))
    return a, b


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("cut", help="remove [start, end) — one step disappears")
    c.add_argument("--video", required=True)
    c.add_argument("--start", type=float, required=True)
    c.add_argument("--end", type=float, required=True)
    c.add_argument("--steps", required=True, help="1-based step number(s) removed, e.g. 4")
    s = sub.add_parser("swap", help="exchange two non-overlapping ranges — two steps change order")
    s.add_argument("--video", required=True)
    s.add_argument("--a", type=parse_range, required=True, metavar="S1,E1")
    s.add_argument("--b", type=parse_range, required=True, metavar="S2,E2")
    s.add_argument("--steps", required=True, help="1-based step numbers swapped, e.g. 2,4")
    n = sub.add_parser("none", help="register an unedited trainee video in ground truth")
    n.add_argument("--video", required=True)
    args = ap.parse_args(argv)

    try:
        row = require_allowed(args.video)
    except LicenseError as e:
        print(f"refused: {e}")
        return 1
    vid, src = row["video_id"], local_path(row)
    steps = [int(x) for x in args.steps.split(",")] if args.cmd != "none" else []

    if args.cmd == "none":
        flaw = {"type": "none", "steps": [], "start_ts": None, "end_ts": None}
        gt_id = vid
    else:
        if not src.exists():
            print(f"refused: {src} not found")
            return 1
        info = probe(src)
        dur = info["duration"]
        if args.cmd == "cut":
            a, b = args.start, args.end
            if not 0 <= a < b <= dur:
                print(f"refused: need 0 <= start < end <= {dur:.2f}")
                return 1
            segments = [(0, a), (b, dur)]
            gt_id = f"{vid}__cut_{a:g}-{b:g}"
            flaw = {"type": "cut", "steps": steps, "start_ts": a, "end_ts": a, "source_ranges": [[a, b]]}
            desc = f"cut {a:g}–{b:g} s (removes step {args.steps})"
        else:
            (s1, e1), (s2, e2) = sorted([args.a, args.b])
            if not (0 <= s1 < e1 <= s2 < e2 <= dur):
                print(f"refused: need two non-overlapping ranges inside 0–{dur:.2f}")
                return 1
            segments = [(0, s1), (s2, e2), (e1, s2), (s1, e1), (e2, dur)]
            gt_id = f"{vid}__swap_{s1:g}-{e1:g}_{s2:g}-{e2:g}"
            # Edited timeline: [0,s1) unchanged, then B, gap, A; everything after e2 is unchanged.
            flaw = {"type": "swap", "steps": steps, "start_ts": s1, "end_ts": e2,
                    "source_ranges": [[s1, e1], [s2, e2]]}
            desc = f"swapped {s1:g}–{e1:g} s with {s2:g}–{e2:g} s (steps {args.steps} out of order)"
        segments = [(x, y) for x, y in segments if y - x > 1e-3]
        if any(r["video_id"] == gt_id for r in load_manifest()):
            print(f"refused: {gt_id} already exists in the manifest")
            return 1
        out = EDITED / f"{gt_id}.mp4"
        splice(src, segments, out, info["has_audio"])
        append_manifest_row({**row, "video_id": gt_id, "role": "trainee", "local_path": str(out.relative_to(ROOT))})
        log_attribution(vid, f"{date.today().isoformat()}: {desc} → `{gt_id}`")
        print(f"wrote {out.relative_to(ROOT)} ({probe(out)['duration']:.2f}s, source {dur:.2f}s)")

    with open(GROUND_TRUTH, "a") as f:
        f.write(json.dumps({"video_id": gt_id, "task": row["task"], "step_list": step_list(row["task"]),
                            "injected_flaw": flaw}) + "\n")
    print(f"ground truth: {gt_id} {flaw['type']} steps={flaw['steps']} at {flaw['start_ts']}–{flaw['end_ts']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
