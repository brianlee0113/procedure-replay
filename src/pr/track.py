"""track(video, object_prompts) -> per-prompt presence timeline from SAM 3.1.

One SAM request per (video, prompt), since SAM 3.1 takes one concept per request.
Raw SAM output (boxes + one_bit masks) is kept in results/tracks/raw/ for render_demo; the timeline keeps
only per-frame counts, box area, and confidence, cached in results/tracks/<video_id>.json.
"""

import json
import re
from pathlib import Path

from meta_sam_parser import CompletedOutcome, SegmentationBoxRecord, video_segmentation_format

from pr.client import RESULTS, MetaClient
from pr.frames import PROXY_DIR, PROXY_FPS, make_proxy, probe, proxy_frame_count, trim
from pr.license_check import local_path, require_allowed

TRACKS = RESULTS / "tracks"


def prepare(video: str, client: MetaClient, clip: tuple[float, float] | None = None, audio: bool = True) -> dict:
    """License gate -> optional (start, duration) clip -> 5 fps proxy -> upload.

    `video` is a manifest video_id or local path. A clip gets its own id, e.g. `toner_ref__30s+30s`.
    Without audio the proxy id gets a `__mute` suffix.
    """
    row = require_allowed(video)
    src = local_path(row)
    if not src.exists():
        raise FileNotFoundError(f"{row['video_id']}: {src} not found (place the licensed file there)")
    vid = row["video_id"]
    if clip:
        vid = f"{vid}__{clip[0]:g}s+{clip[1]:g}s"
        src = trim(src, clip[0], clip[1], PROXY_DIR / f"{vid}_src.mp4")
    if not audio:
        vid = f"{vid}__mute"
    proxy = make_proxy(src, vid, audio=audio)
    return {"row": row, "video_id": vid, "proxy": proxy, "info": probe(proxy),
            "n_frames": proxy_frame_count(proxy), "file_id": client.upload(proxy)}


def parse_sam(text: str, width: int, height: int) -> dict[int, list[dict]]:
    """SAM output text -> {frame_index: [{id, box, area, conf}]}. Area is a fraction of the frame."""
    parser = video_segmentation_format().create_parser()
    parser.push(text if text.endswith("\n") else text + "\n", emit=False)
    result = parser.finish(CompletedOutcome()).result
    for d in result.diagnostics:
        print(f"  sam-parser {d.severity}: {d.code} on line {d.line}")
    frames: dict[int, list[dict]] = {}
    for r in result.records:
        if not isinstance(r, SegmentationBoxRecord) or r.frame is None:
            continue
        box = [r.left, r.top, r.right, r.bottom]
        area = (r.right - r.left) * (r.bottom - r.top) / (width * height)
        frames.setdefault(r.frame.frame_index, []).append(
            {"id": r.object_id, "box": box, "area": round(area, 5), "conf": r.confidence})
    return frames


def _slug(prompt: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", prompt.lower()).strip("_")


def track(video: str, object_prompts: list[str], client: MetaClient, prepared: dict | None = None) -> dict:
    """Return {video_id, fps, n_frames, prompts: {prompt: {coverage, frames: {f: [...]}}}}. Cached per prompt."""
    p = prepared or prepare(video, client)
    vid, n = p["video_id"], p["n_frames"]
    out_path = TRACKS / f"{vid}.json"
    (TRACKS / "raw").mkdir(parents=True, exist_ok=True)
    timeline = json.loads(out_path.read_text()) if out_path.exists() else {
        "video_id": vid, "fps": PROXY_FPS, "n_frames": n, "prompts": {}}

    for prompt in object_prompts:
        if prompt in timeline["prompts"]:
            continue
        print(f"  SAM 3.1 '{prompt}' on {vid} ({n} frames)…")
        text = client.sam_track(p["file_id"], prompt, vid, n_frames=n)
        (TRACKS / "raw" / f"{vid}__{_slug(prompt)}.txt").write_text(text)
        frames = parse_sam(text, p["info"]["width"], p["info"]["height"])
        timeline["prompts"][prompt] = {
            "coverage": round(100 * len(frames) / max(n, 1), 1),
            "frames": {str(f): recs for f, recs in sorted(frames.items())},
        }
        out_path.write_text(json.dumps(timeline))
    return timeline


def presence(timeline: dict, prompt: str) -> list[bool]:
    """Per-frame presence of `prompt` (any instance) as a dense list of length n_frames."""
    frames = timeline["prompts"][prompt]["frames"]
    return [str(f) in frames for f in range(timeline["n_frames"])]
