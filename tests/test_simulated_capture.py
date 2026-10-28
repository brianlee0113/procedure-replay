"""A mock-glasses recording becomes the stretch of the licensed feed video it showed, with sound (no API calls).
Needs the local yt_LPwPomA7BfM video. Run: uv run python tests/test_simulated_capture.py"""

import io
import os
import tempfile
import time
from pathlib import Path

os.environ["PR_BUILDER"] = "checklist"
os.environ["PR_STAGE_DELAY_S"] = "0"

from fastapi.testclient import TestClient  # noqa: E402

from pr import guides, license_check, server  # noqa: E402
from pr.frames import probe  # noqa: E402

SOURCE = "yt_LPwPomA7BfM"
if not license_check.local_path(license_check.find_row(SOURCE)).exists():
    raise SystemExit(f"skipped: {SOURCE} not downloaded")

tmp = Path(tempfile.mkdtemp())
guides.GUIDES = tmp / "guides"
server.JOBS, server.REACTIONS, server.PROGRESS = tmp / "jobs", tmp / "reactions.json", tmp / "progress.json"
server.UPLOADS = license_check.ROOT / "data" / "uploads" / "_test_capture"
server.APP_MANIFEST = license_check.APP_MANIFEST = tmp / "manifest_app.csv"
api = TestClient(server.app)
silent = ("rec.mp4", io.BytesIO(b"silent frames from the mock glasses"), "video/mp4")

# Too short a window is refused.
r = api.post("/recordings", data={"task": "faucet_repair", "source_video_id": SOURCE, "source_start_s": "10",
                                  "source_end_s": "10.4"}, files={"video": silent})
assert r.status_code == 422, r.text

r = api.post("/recordings", data={"task": "faucet_repair", "source_video_id": SOURCE, "source_start_s": "12.5",
                                  "source_end_s": "40"}, files={"video": silent})
assert r.status_code == 202, r.text
job = r.json()
assert job["simulated_from"] == {"source_video_id": SOURCE, "start_s": 12.5, "end_s": 40.0}, job
stored = license_check.local_path(license_check.find_row(job["video_id"]))
info = probe(stored)
assert info["has_audio"] and 27.0 <= info["duration"] <= 28.0, info  # the source stretch, with its narration
assert (stored.with_name(f"{stored.stem}_glasses{stored.suffix}")).read_bytes().startswith(b"silent")

for _ in range(100):
    if api.get(f"/jobs/{job['id']}").json()["status"] in ("done", "error"):
        break
    time.sleep(0.05)
server.worker.shutdown(wait=True)
for p in server.UPLOADS.glob("*"):
    p.unlink()
server.UPLOADS.rmdir()
print("ok")
