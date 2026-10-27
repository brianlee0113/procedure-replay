"""Meta Model API wrapper: Files upload, SAM 3.1 streaming segmentation, Muse Spark structured output.

API shapes follow https://dev.meta.ai/docs (read Oct 26, 2026):
- Both models use the Responses API (POST /v1/responses) on base URL https://api.meta.ai/v1.
- Video goes in an `input_video` part as a `file_id` from POST /v1/files (purpose=user_data).
- SAM 3.1 takes ONE noun-phrase concept per request; output is special-token text, one line per frame.
- Muse Spark structured output on the Responses API is `text.format` with a json_schema.
Every call appends a row to results/costs.csv.
"""

import csv
import hashlib
import json
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path

import openai
from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"
COSTS_CSV = RESULTS / "costs.csv"
FILE_CACHE = RESULTS / ".file_cache.json"
BASE_URL = "https://api.meta.ai/v1"

# USD, from https://dev.meta.ai/docs/pricing-rate-limits (Oct 26, 2026). Text: per 1M tokens.
TOKEN_PRICES = {
    "muse-spark-1.3-contributor": {"input": 0.10, "cached": 0.002, "output": 0.20},
    "muse-spark-1.2-contributor": {"input": 0.10, "cached": 0.002, "output": 0.20},
    "muse-spark-1.3": {"input": 1.25, "cached": 0.15, "output": 4.25},
    "muse-wonder-1.0": {"input": 4.00, "cached": 0.20, "output": 20.00},
}
SAM_PRICE_PER_FRAME = 0.20 / 1000
# Muse Voice Transcribe: $0.18 per hour of audio, billed in whole seconds.
TRANSCRIBE_PRICE_PER_HOUR = 0.18
SAM_MIN_FRAMES = 50

COST_FIELDS = ["ts", "model", "purpose", "video_id", "input_tokens", "cached_tokens",
               "output_tokens", "video_frames", "est_usd", "latency_s"]

RETRYABLE = (openai.RateLimitError, openai.APIConnectionError, openai.APITimeoutError,
             openai.InternalServerError)


def _retry(fn, attempts: int = 5):
    """Exponential backoff with jitter on 429/5xx/connection errors; honors Retry-After. Never retries a 400."""
    delay = 0.5
    for i in range(attempts):
        try:
            return fn()
        except RETRYABLE as e:
            if i == attempts - 1:
                raise
            wait = delay + random.uniform(0, delay)
            response = getattr(e, "response", None)
            if response is not None and response.headers.get("retry-after"):
                wait = max(wait, float(response.headers["retry-after"]))
            print(f"  retry {i + 1}/{attempts - 1} after {type(e).__name__}, waiting {wait:.1f}s")
            time.sleep(wait)
            delay *= 2


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def log_cost(model: str, purpose: str, video_id: str, *, input_tokens=0, cached_tokens=0,
             output_tokens=0, video_frames=0, latency_s=0.0, audio_seconds=0.0) -> float:
    if model.startswith("muse-voice-transcribe"):
        usd = int(audio_seconds) * TRANSCRIBE_PRICE_PER_HOUR / 3600
    elif model in TOKEN_PRICES:
        p = TOKEN_PRICES[model]
        usd = ((input_tokens - cached_tokens) * p["input"] + cached_tokens * p["cached"]
               + output_tokens * p["output"]) / 1e6
    elif model.startswith("sam"):
        usd = max(video_frames, SAM_MIN_FRAMES) * SAM_PRICE_PER_FRAME
    else:
        usd = float("nan")
    RESULTS.mkdir(exist_ok=True)
    new = not COSTS_CSV.exists()
    with open(COSTS_CSV, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COST_FIELDS)
        if new:
            w.writeheader()
        w.writerow({"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "model": model,
                    "purpose": purpose, "video_id": video_id, "input_tokens": input_tokens,
                    "cached_tokens": cached_tokens, "output_tokens": output_tokens,
                    "video_frames": video_frames, "est_usd": f"{usd:.6f}", "latency_s": f"{latency_s:.1f}"})
    return usd


def spark_model_name() -> str:
    """The Muse Spark model MetaClient would use, without needing an API key (for cache checks)."""
    load_dotenv(ROOT / ".env")
    return os.environ.get("MODEL_NAME") or "muse-spark-1.3-contributor"


class MetaClient:
    def __init__(self):
        load_dotenv(ROOT / ".env")
        key = os.environ.get("META_API_KEY")
        if not key:
            raise SystemExit("META_API_KEY is not set. Copy .env.example to .env and add your key.")
        self.spark_model = spark_model_name()
        self.sam_model = os.environ.get("SAM_MODEL") or "sam-3.1"
        # Retries are handled by _retry so streams and uploads share one policy.
        self.api = OpenAI(base_url=BASE_URL, api_key=key, max_retries=0, timeout=900)

    def upload(self, path: Path) -> str:
        """Upload once per file content (sha256 cache); files expire after 7 days to stay under the team quota."""
        cache = json.loads(FILE_CACHE.read_text()) if FILE_CACHE.exists() else {}
        digest = sha256_file(path)
        if digest in cache:
            return cache[digest]

        def do():
            with open(path, "rb") as f:
                return self.api.files.create(purpose="user_data", file=f,
                                             expires_after={"anchor": "created_at", "seconds": 7 * 86400})

        file_id = _retry(do).id
        cache[digest] = file_id
        RESULTS.mkdir(exist_ok=True)
        FILE_CACHE.write_text(json.dumps(cache, indent=1))
        return file_id

    def sam_track(self, file_id: str, prompt: str, video_id: str, n_frames: int) -> str:
        """Run one SAM 3.1 concept prompt over a whole video. Returns the raw output text (one line per frame).

        n_frames is only a cost fallback in case usage.video_frames_processed is missing.
        """
        def do():
            t0 = time.time()
            lines = []
            with self.api.responses.stream(
                model=self.sam_model,
                input=[{"type": "message", "role": "user", "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_video", "file_id": file_id},
                ]}],
                metadata={"include_confidence": "true", "mask_encoding": "one_bit"},
            ) as stream:
                for event in stream:
                    if event.type == "response.output_text.delta":
                        lines.append(event.delta if event.delta.endswith("\n") else event.delta + "\n")
                final = stream.get_final_response()
            return "".join(lines), final, time.time() - t0

        text, final, latency = _retry(do)
        usage = final.usage.model_dump() if final.usage else {}
        frames = usage.get("video_frames_processed") or n_frames
        log_cost(self.sam_model, f"track:{prompt}", video_id, video_frames=frames, latency_s=latency)
        return text

    def spark_json(self, file_id: str, prompt: str, schema: dict, schema_name: str, video_id: str,
                   purpose: str = "steps", model: str | None = None) -> dict:
        """Ask Muse Spark about a video and get JSON constrained to `schema`. `model` overrides MODEL_NAME."""
        model = model or self.spark_model

        def do():
            t0 = time.time()
            r = self.api.responses.create(
                model=model,
                input=[{"type": "message", "role": "user", "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_video", "file_id": file_id},
                ]}],
                text={"format": {"type": "json_schema", "name": schema_name, "schema": schema, "strict": True}},
                # Reasoning shares the output budget; docs recommend >= 4000.
                max_output_tokens=16000,
            )
            return r, time.time() - t0

        r, latency = _retry(do)
        u = r.usage
        cached = (u.input_tokens_details.cached_tokens or 0) if u and u.input_tokens_details else 0
        log_cost(model, purpose, video_id, input_tokens=u.input_tokens if u else 0,
                 cached_tokens=cached, output_tokens=u.output_tokens if u else 0, latency_s=latency)
        if not r.output_text:
            raise RuntimeError(f"Muse Spark returned no text (status={r.status}, "
                               f"incomplete={getattr(r, 'incomplete_details', None)})")
        return json.loads(r.output_text)
