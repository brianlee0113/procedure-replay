"""Inject a known flaw into a trainee video by editing, so ground truth is exact.

    uv run python -m pr.inject cut  --video ID --step "add ram"                       # range from keystep labels, ±3 s
    uv run python -m pr.inject swap --video ID --step-a "add battery" --step-b "attach fan"
    uv run python -m pr.inject cut  --video ID --start 42 --end 55.5 --steps 4         # explicit range
    uv run python -m pr.inject swap --video ID --a 20,35 --b 50,70 --steps 2,4
    uv run python -m pr.inject none --video ID          # register an unedited trainee video
    uv run python -m pr.inject --set dev cut --video ID --step "attach fan"   # dev set (prompt tuning)

--step looks the range up in data/keysteps/<video_id>.json (written by scripts/import_indego.py or
scripts/import_captaincook.py) and the step number in the task's `keysteps` list in config/tasks.yaml.
A unique prefix of a step name works. For recipes, swap refuses two steps the recipe lets you do in either order.

Each edit writes data/edited/<new_id>.mp4 and appends:
- a manifest row (same creator / source / license as the source video, role trainee),
- a ground_truth row (data/ground_truth.jsonl, or data/ground_truth_dev.jsonl with --set dev) whose start_ts / end_ts are in the EDITED video's timeline
  (cut: both are the splice point; swap: the span now holding the two moved blocks),
- an edit line under the source video's entry in ATTRIBUTION.md.
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import yaml

from pr.frames import probe, run
from pr.license_check import ROOT, LicenseError, append_manifest_row, load_manifest, local_path, require_allowed

EDITED = ROOT / "data" / "edited"
GROUND_TRUTH = {"test": ROOT / "data" / "ground_truth.jsonl", "dev": ROOT / "data" / "ground_truth_dev.jsonl"}
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
    """The task's keysteps from config/tasks.yaml, else step titles from its reference checklist."""
    cfg = yaml.safe_load((ROOT / "config" / "tasks.yaml").read_text()).get(task, {})
    if cfg.get("keysteps"):
        return cfg["keysteps"]
    path = ROOT / "results" / "checklists" / f"{task}.json"
    return [s["title"] for s in json.loads(path.read_text())["steps"]] if path.exists() else []


def resolve_step(task: str, name: str) -> str:
    """Full step name from an exact name or a unique prefix ('cook the tomatoes' for a long recipe step)."""
    steps = step_list(task)
    if name in steps:
        return name
    hits = [s for s in steps if s.lower().startswith(name.lower())]
    if len(hits) != 1:
        raise SystemExit(f"refused: {name!r} matches {len(hits)} steps of {task}: {hits or steps}")
    return hits[0]


def check_swap_is_an_error(task: str, a: str, b: str) -> None:
    """Recipes are partial orders: swapping two steps the recipe doesn't order is not a mistake, so refuse it."""
    path = ROOT / "data" / "task_graphs" / f"{task}.json"
    if not path.exists():
        return
    before = {tuple(p) for p in json.loads(path.read_text())["before"]}
    if (a, b) not in before and (b, a) not in before:
        raise SystemExit(f"refused: {task}'s recipe allows {a!r} and {b!r} in either order "
                         f"({path.relative_to(ROOT)}), so swapping them is not an error")


def keystep_range(video_id: str, task: str, name: str) -> tuple[float, float, int]:
    """(start, end, 1-based step number) of a labelled keystep in the source video."""
    path = ROOT / "data" / "keysteps" / f"{video_id}.json"
    if not path.exists():
        raise SystemExit(f"refused: no keystep labels at {path.relative_to(ROOT)} "
                         f"(run scripts/import_indego.py or scripts/import_captaincook.py)")
    name = resolve_step(task, name)
    segs = [s for s in json.loads(path.read_text()) if s["step"] == name]
    steps = step_list(task)
    if not segs or name not in steps:
        raise SystemExit(f"refused: step {name!r} not labelled in {video_id}; labelled: "
                         f"{sorted({s['step'] for s in json.loads(path.read_text())})}")
    if len(segs) > 1:
        print(f"note: {name!r} occurs {len(segs)}x in {video_id}; using the first occurrence")
    return segs[0]["start"], segs[0]["end"], steps.index(name) + 1


CUT_PAD = 3.0  # seconds


def padded_cut(video_id: str, start: float, end: float) -> tuple[float, float]:
    """Widen a labelled cut by CUT_PAD on each side, without reaching into a neighbouring labelled step.

    Keystep labels can start after the hands have already picked the part up (dev set: a trainee takes the
    coin battery from the tray 1 s before the 'add battery' label starts), which leaves half the action in
    the edited video.
    """
    segs = json.loads((ROOT / "data" / "keysteps" / f"{video_id}.json").read_text())
    prev_end = max([s["end"] for s in segs if s["end"] <= start], default=0.0)
    next_start = min([s["start"] for s in segs if s["start"] >= end], default=float("inf"))
    return max(start - CUT_PAD, prev_end), min(end + CUT_PAD, next_start)


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
    ap.add_argument("--set", choices=list(GROUND_TRUTH), default="test",
                    help="test = held-out eval set; dev = set used for tuning prompts")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("cut", help="remove [start, end) — one step disappears")
    c.add_argument("--video", required=True)
    c.add_argument("--step", help="keystep name to remove, e.g. 'add ram' (sets --start/--end/--steps)")
    c.add_argument("--start", type=float)
    c.add_argument("--end", type=float)
    c.add_argument("--steps", help="1-based step number(s) removed, e.g. 4")
    s = sub.add_parser("swap", help="exchange two non-overlapping ranges — two steps change order")
    s.add_argument("--video", required=True)
    s.add_argument("--step-a", help="keystep name, e.g. 'add battery' (sets --a and --steps)")
    s.add_argument("--step-b", help="keystep name, e.g. 'attach fan' (sets --b and --steps)")
    s.add_argument("--a", type=parse_range, metavar="S1,E1")
    s.add_argument("--b", type=parse_range, metavar="S2,E2")
    s.add_argument("--steps", help="1-based step numbers swapped, e.g. 2,4")
    n = sub.add_parser("none", help="register an unedited trainee video in ground truth")
    n.add_argument("--video", required=True)
    args = ap.parse_args(argv)

    try:
        row = require_allowed(args.video)
    except LicenseError as e:
        print(f"refused: {e}")
        return 1
    vid, src = row["video_id"], local_path(row)
    if args.cmd == "cut" and args.step:
        args.start, args.end, n = keystep_range(vid, row["task"], args.step)
        args.start, args.end = padded_cut(vid, args.start, args.end)
        args.steps = args.steps or str(n)
    if args.cmd == "swap" and args.step_a and args.step_b:
        check_swap_is_an_error(row["task"], resolve_step(row["task"], args.step_a), resolve_step(row["task"], args.step_b))
        sa, ea, na = keystep_range(vid, row["task"], args.step_a)
        sb, eb, nb = keystep_range(vid, row["task"], args.step_b)
        args.a, args.b, args.steps = (sa, ea), (sb, eb), args.steps or f"{na},{nb}"
    if args.cmd == "cut" and (args.start is None or args.end is None or not args.steps):
        ap.error("cut needs --step, or --start, --end and --steps")
    if args.cmd == "swap" and (args.a is None or args.b is None or not args.steps):
        ap.error("swap needs --step-a and --step-b, or --a, --b and --steps")
    steps = [int(x) for x in args.steps.split(",")] if args.cmd != "none" else []
    names = step_list(row["task"])
    step_names = [names[i - 1] for i in steps if 0 < i <= len(names)]

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
            gt_id = f"{vid}__cut_{a:.1f}-{b:.1f}"
            flaw = {"type": "cut", "steps": steps, "step_names": step_names, "start_ts": a, "end_ts": a,
                    "source_ranges": [[a, b]]}
            desc = f"cut {a:.1f}–{b:.1f} s (removes step {args.steps}{': ' + ', '.join(step_names) if step_names else ''})"
        else:
            (s1, e1), (s2, e2) = sorted([args.a, args.b])
            if not (0 <= s1 < e1 <= s2 < e2 <= dur):
                print(f"refused: need two non-overlapping ranges inside 0–{dur:.2f}")
                return 1
            segments = [(0, s1), (s2, e2), (e1, s2), (s1, e1), (e2, dur)]
            gt_id = f"{vid}__swap_{s1:.1f}-{e1:.1f}_{s2:.1f}-{e2:.1f}"
            # Edited timeline: [0,s1) unchanged, then B, gap, A; everything after e2 is unchanged.
            flaw = {"type": "swap", "steps": steps, "step_names": step_names, "start_ts": s1, "end_ts": e2,
                    "source_ranges": [[s1, e1], [s2, e2]]}
            desc = f"swapped {s1:.1f}–{e1:.1f} s with {s2:.1f}–{e2:.1f} s (steps {args.steps} out of order)"
        segments = [(x, y) for x, y in segments if y - x > 1e-3]
        if any(r["video_id"] == gt_id for r in load_manifest()):
            print(f"refused: {gt_id} already exists in the manifest")
            return 1
        out = EDITED / f"{gt_id}.mp4"
        splice(src, segments, out, info["has_audio"])
        append_manifest_row({**row, "video_id": gt_id, "role": "trainee", "local_path": str(out.relative_to(ROOT))})
        log_attribution(vid, f"{date.today().isoformat()}: {desc} → `{gt_id}`")
        print(f"wrote {out.relative_to(ROOT)} ({probe(out)['duration']:.2f}s, source {dur:.2f}s)")

    with open(GROUND_TRUTH[args.set], "a") as f:
        f.write(json.dumps({"video_id": gt_id, "task": row["task"], "step_list": step_list(row["task"]),
                            "injected_flaw": flaw}) + "\n")
    print(f"ground truth ({args.set}): {gt_id} {flaw['type']} steps={flaw['steps']} at {flaw['start_ts']}–{flaw['end_ts']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
