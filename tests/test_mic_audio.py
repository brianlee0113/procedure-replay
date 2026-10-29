"""A recording made with the iPhone standing in for the glasses: the phone's mic track is merged into the silent
glasses video before the guide is built (no API calls). Run: uv run python tests/test_mic_audio.py"""

import os
import subprocess
import tempfile
import time
from pathlib import Path

os.environ["PR_BUILDER"] = "checklist"
os.environ["PR_STAGE_DELAY_S"] = "0"

from fastapi.testclient import TestClient  # noqa: E402

from pr import guides, license_check, server  # noqa: E402
from pr.frames import probe  # noqa: E402

tmp = Path(tempfile.mkdtemp())
guides.GUIDES = tmp / "guides"
server.JOBS, server.REACTIONS, server.PROGRESS = tmp / "jobs", tmp / "reactions.json", tmp / "progress.json"
server.UPLOADS = license_check.ROOT / "data" / "uploads" / "_test_mic"
server.APP_MANIFEST = license_check.APP_MANIFEST = tmp / "manifest_app.csv"
api = TestClient(server.app)

video, mic = tmp / "glasses.mp4", tmp / "mic.m4a"
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=270x480:rate=15:duration=3",
                "-pix_fmt", "yuv420p", str(video)], check=True)
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                "-c:a", "aac", str(mic)], check=True)

r = api.post("/recordings",
             data={"task": "app_recording", "license": "CC-BY-4.0", "creator": "Test Instructor"},
             files={"video": ("rec.mp4", video.read_bytes(), "video/mp4"), "audio": ("mic.m4a", mic.read_bytes(), "audio/mp4")})
assert r.status_code == 202, r.text
job = r.json()
assert job["mic_audio"] and job["stages"]["upload"] == "queued", job
for _ in range(600):
    job = api.get(f"/jobs/{job['id']}").json()
    if job["status"] in ("done", "error"):
        break
    time.sleep(0.05)
stored = license_check.local_path(license_check.find_row(job["video_id"]))
info = probe(stored)
assert info["has_audio"] and 2.5 <= info["duration"] <= 3.5, info  # the mic is now the recording's sound
assert stored.with_name(f"{stored.stem}_silent{stored.suffix}").exists()

server.worker.shutdown(wait=True)
for p in server.UPLOADS.glob("*"):
    p.unlink()
server.UPLOADS.rmdir()
print("ok")
