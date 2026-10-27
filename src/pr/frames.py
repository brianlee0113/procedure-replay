"""ffmpeg/OpenCV helpers: probe, 5 fps proxy with a burned-in clock, trimming, frame grabs.

Both models see the same proxy, so proxy frame index f maps to source time f / PROXY_FPS seconds.
The clock is drawn with OpenCV (Homebrew ffmpeg ships without the drawtext filter).
"""

import json
import subprocess
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
PROXY_DIR = ROOT / "data" / "proxy"
PROXY_FPS = 5
PROXY_HEIGHT = 720
# The Files API answered "400 Invalid upload request" for a 128.1 MiB proxy and accepted 123.4 MiB,
# so long proxies are re-encoded below this size.
MAX_UPLOAD_BYTES = 120 * 2**20


def run(cmd: list[str]) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed:\n{' '.join(cmd)}\n{r.stderr[-2000:]}")
    return r.stdout


def probe(path: Path) -> dict:
    """Duration (s), fps, displayed width/height (after rotation), and whether there is audio."""
    out = json.loads(run(["ffprobe", "-v", "error", "-print_format", "json",
                          "-show_streams", "-show_format", str(path)]))
    v = next(s for s in out["streams"] if s["codec_type"] == "video")
    num, den = v["avg_frame_rate"].split("/")
    w, h = int(v["width"]), int(v["height"])
    rotation = 0
    for sd in v.get("side_data_list", []):
        rotation = int(sd.get("rotation", rotation))
    if abs(rotation) % 180 == 90:
        w, h = h, w
    return {
        "duration": float(out["format"]["duration"]),
        "fps": float(num) / float(den) if float(den) else 0.0,
        "width": w,
        "height": h,
        "codec": v["codec_name"],
        "has_audio": any(s["codec_type"] == "audio" for s in out["streams"]),
    }


def fmt_ts(seconds: float) -> str:
    m, s = divmod(seconds, 60)
    return f"{int(m):02d}:{s:04.1f}"


def _draw_clock(frame: np.ndarray, seconds: float) -> None:
    text = fmt_ts(seconds)
    scale = frame.shape[0] / 720 * 0.9
    (tw, th), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 2)
    x, y = 12, 12 + th
    cv2.rectangle(frame, (x - 6, y - th - 6), (x + tw + 6, y + base + 4), (0, 0, 0), -1)
    cv2.putText(frame, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), 2, cv2.LINE_AA)


def make_proxy(src: Path, video_id: str, force: bool = False) -> Path:
    """Re-encode to 5 fps, <=720p, H.264 + AAC, faststart, with an MM:SS.s clock in the top-left corner."""
    PROXY_DIR.mkdir(parents=True, exist_ok=True)
    out = PROXY_DIR / f"{video_id}.mp4"
    if out.exists() and not force:
        return out
    info = probe(src)
    h = min(PROXY_HEIGHT, info["height"]) // 2 * 2
    w = round(info["width"] * h / info["height"] / 2) * 2

    decoder = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(src), "-vf", f"fps={PROXY_FPS},scale={w}:{h}",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], stdout=subprocess.PIPE)
    encode = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}",
              "-r", str(PROXY_FPS), "-i", "-"]
    if info["has_audio"]:
        encode += ["-i", str(src), "-map", "0:v", "-map", "1:a:0", "-c:a", "aac", "-b:a", "96k", "-shortest"]
    encode += ["-c:v", "libx264", "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
    encoder = subprocess.Popen(encode, stdin=subprocess.PIPE)

    frame_bytes = w * h * 3
    idx = 0
    while (buf := decoder.stdout.read(frame_bytes)) and len(buf) == frame_bytes:
        frame = np.frombuffer(buf, np.uint8).reshape(h, w, 3).copy()
        _draw_clock(frame, idx / PROXY_FPS)
        encoder.stdin.write(frame.tobytes())
        idx += 1
    encoder.stdin.close()
    if decoder.wait() != 0 or encoder.wait() != 0:
        out.unlink(missing_ok=True)
        raise RuntimeError(f"proxy encode failed for {src}")
    crf = 23
    while out.stat().st_size > MAX_UPLOAD_BYTES and crf < 35:
        crf += 3
        smaller = out.with_suffix(".tmp.mp4")
        run(["ffmpeg", "-v", "error", "-y", "-i", str(out), "-c:v", "libx264", "-crf", str(crf), "-c:a", "copy",
             "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(smaller)])
        smaller.replace(out)
    return out


def proxy_frame_count(proxy: Path) -> int:
    cap = cv2.VideoCapture(str(proxy))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    return n


def trim(src: Path, start: float, duration: float, out: Path) -> Path:
    """Frame-accurate re-encoded trim [start, start+duration)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}", "-i", str(src), "-t", f"{duration:.3f}",
         "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart",
         str(out)])
    return out


def grab_frame(path: Path, t: float) -> np.ndarray | None:
    cap = cv2.VideoCapture(str(path))
    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
    ok, frame = cap.read()
    cap.release()
    return frame if ok else None
