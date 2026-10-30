"""transcribe(video_id) -> what is said in a video, with turn-level times (Muse Voice Transcribe).

API shape from https://dev.meta.ai/docs/api-reference/voice/transcribe and .../voice/schemas (read Oct 27, 2026):
POST /v1/asr/transcribe, multipart/form-data with a `request` JSON part
({"model": "muse-voice-transcribe-1.0", "audioEncoding": "WAV", "mode": ...}) and an `audio` part
(mono 16-bit PCM WAV at 16 or 24 kHz, at most 10 minutes and 32 MB). The JSON response has `transcript`,
`audioDurationMs` and `turns` [{turnId, startMs, endMs, transcript}]. No word-level timestamps.

Long videos are cut into 9-minute chunks; turn times are shifted back to the video's own timeline.
Results are cached in results/transcripts/<video_id>.json.

    uv run python -m pr.transcribe 22_u17_r03_c_01 cc4d_22_21
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

from dotenv import load_dotenv

from pr.client import BASE_URL, RESULTS, log_cost
from pr.frames import probe
from pr.license_check import ROOT, local_path, require_allowed

MODEL = "muse-voice-transcribe-1.0"
TRANSCRIPTS = RESULTS / "transcripts"
CHUNK_S = 540
SAMPLE_RATE = 24000
SPEAKER = re.compile(r"<\|speaker_[^|]*\|>")  # speaker-change markers inside a turn's text, e.g. <|speaker_A|>


def spoken(text: str) -> str:
    """Turn text without speaker markers, as a person would read it (prompts, quotes)."""
    return " ".join(SPEAKER.sub(" ", text).split())


def _post(wav: bytes, key: str) -> dict:
    boundary = uuid.uuid4().hex
    request = json.dumps({"model": MODEL, "audioEncoding": "WAV", "mode": "ENDPOINTING"})
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"request\"\r\n"
            f"Content-Type: application/json\r\n\r\n{request}\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"audio.wav\"\r\n"
            f"Content-Type: audio/wav\r\n\r\n").encode() + wav + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"{BASE_URL}/asr/transcribe", data=body, method="POST", headers={
        "Authorization": f"Bearer {key}", "Accept": "application/json",
        "Content-Type": f"multipart/form-data; boundary={boundary}"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            # 429 = concurrency or hourly session limit; retry with backoff. Other errors are final.
            if e.code != 429 and e.code < 500 or attempt == 4:
                raise RuntimeError(f"transcribe failed: HTTP {e.code} {e.read()[:300]!r}") from e
            time.sleep(2 ** attempt)


def transcribe(video: str) -> dict:
    """Return {video_id, duration, turns: [{start_s, end_s, text}], transcript}."""
    row = require_allowed(video)
    vid = row["video_id"]
    cached = TRANSCRIPTS / f"{vid}.json"
    if cached.exists():
        return json.loads(cached.read_text())
    load_dotenv(ROOT / ".env")
    key = os.environ.get("META_API_KEY")
    if not key:
        raise SystemExit("META_API_KEY is not set.")
    src = local_path(row)
    duration = probe(src)["duration"]
    turns, texts = [], []
    for start in range(0, int(duration) + 1, CHUNK_S):
        length = min(CHUNK_S, duration - start)
        if length < 1:
            break
        wav = run_bytes(["ffmpeg", "-v", "error", "-ss", str(start), "-t", f"{length:.3f}", "-i", str(src),
                         "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le", "-map_metadata", "-1",
                         "-f", "wav", "-"])
        t0 = time.time()
        r = _post(wav, key)
        log_cost(MODEL, "transcribe", vid, audio_seconds=r.get("audioDurationMs", length * 1000) / 1000,
                 latency_s=time.time() - t0)
        texts.append(r.get("transcript", ""))
        turns += [{"start_s": start + t["startMs"] / 1000, "end_s": start + t["endMs"] / 1000,
                   "text": t["transcript"]} for t in r.get("turns", []) if t.get("transcript", "").strip()]
    out = {"video_id": vid, "duration": duration, "model": MODEL, "turns": turns, "transcript": " ".join(texts).strip()}
    TRANSCRIPTS.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(out, indent=2))
    return out


def run_bytes(cmd: list[str]) -> bytes:
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {r.stderr[-500:].decode(errors='replace')}")
    return r.stdout


def context_block(video: str) -> str:
    """Prompt text listing what was said in the video with times, or "" if nothing was said. Each turn is shown
    with its 0-based position in `turns` (#0, #1, ...), which a guide quote cites as `turn_ids`."""
    turns = transcribe(video)["turns"]
    if not turns:
        return ""
    fmt = lambda s: f"{int(s // 60):02d}:{int(s % 60):02d}"
    lines = "\n".join(f"#{i} [{fmt(t['start_s'])}–{fmt(t['end_s'])}] {spoken(t['text'])}" for i, t in enumerate(turns))
    return ("\nWhat was said in the video (speech-to-text, times from the start of the video; it may contain "
            f"errors and is only a hint, the video is what counts):\n{lines}\n")


if __name__ == "__main__":
    for v in sys.argv[1:]:
        t = transcribe(v)
        print(f"== {t['video_id']} ({t['duration']:.0f}s): {len(t['turns'])} turns")
        for turn in t["turns"]:
            print(f"  [{turn['start_s']:7.1f}–{turn['end_s']:7.1f}] {turn['text']}")
