"""Guide API end to end in a temp directory (no Meta API calls; the stand-in builder uses committed checklists).
Needs the local IndEgo drill-bit reference video for the clip check. Run: uv run python tests/test_guides_api.py"""

import io
import os
import tempfile
import time
from pathlib import Path

os.environ["PR_STAGE_DELAY_S"] = "0"
os.environ["PR_BUILDER"] = "checklist"  # offline stand-in; the real builder would call the Meta API

from fastapi.testclient import TestClient  # noqa: E402

from pr import guides, license_check, server  # noqa: E402

tmp = Path(tempfile.mkdtemp())
guides.GUIDES = tmp / "guides"
server.JOBS, server.REACTIONS, server.PROGRESS = tmp / "jobs", tmp / "reactions.json", tmp / "progress.json"
server.UPLOADS = license_check.ROOT / "data" / "uploads" / "_test"  # store_upload needs a path under the repo
server.APP_MANIFEST = license_check.APP_MANIFEST = tmp / "manifest_app.csv"

api = TestClient(server.app)
LUIS, MIN = {"X-User": "luis"}, {"X-User": "min"}
fake_video = ("rec.mp4", io.BytesIO(b"not really a video"), "video/mp4")

# A recording whose rights the gate refuses is never stored.
r = api.post("/recordings", data={"task": "drill_bit", "license": "CC-BY-NC-4.0", "creator": "x"},
             files={"video": fake_video}, headers=LUIS)
assert r.status_code == 403, r.text

# Upload → job → stages → guide.
r = api.post("/recordings", data={"task": "drill_bit", "source_video_id": "07_u01_r02_c_01", "author_name": "Luis Ortega",
                                  "marks": "[12.5, 3.0]"},
             files={"video": fake_video}, headers=LUIS)
assert r.status_code == 202, r.text
job = r.json()
assert job["stages"]["upload"] == "done" and job["stages"]["split"] == "queued" and job["marks"] == [3.0, 12.5]
for _ in range(100):
    job = api.get(f"/jobs/{job['id']}").json()
    if job["status"] in ("done", "error"):
        break
    time.sleep(0.05)
assert job["status"] == "done", job
assert set(job["stages"].values()) == {"done"}
gid = job["guide_id"]

# Drafts are the author's only.
g = api.get(f"/guides/{gid}", headers=LUIS).json()
assert g["meta"]["visibility"] == "draft" and g["guide"]["category"] == "workshop_tools"
assert len(g["guide"]["steps"]) == 5 and g["guide"]["steps"][0]["clip_url"].endswith("/clips/1.mp4")
assert set(g["guide"]) >= {"inputs_provided", "provenance"} and "inputs_used" not in g["guide"]  # contract v1
assert api.get(f"/guides/{gid}", headers=MIN).status_code == 404
assert api.get(f"/guides/{gid}?user=luis").status_code == 200  # images can't send headers
assert api.get("/feed", headers=MIN).json() == []

# Draft edit: text, then a re-cut that moves the loop clip; overlapping cuts are refused.
s = api.patch(f"/guides/{gid}/steps/2", json={"title": "Take out the old bit"}, headers=LUIS).json()
assert s["title"] == "Take out the old bit"
s = api.patch(f"/guides/{gid}/steps/2", json={"start_s": 8.0, "end_s": 16.0}, headers=LUIS).json()
assert (s["clip"]["start_s"], s["clip"]["end_s"]) == (7.0, 17.0), s["clip"]
assert api.patch(f"/guides/{gid}/steps/2", json={"end_s": 30.0}, headers=LUIS).status_code == 422
model = guides.Guide.model_validate_json((guides.GUIDES / gid / "model.json").read_text())
assert model.steps[1].title != "Take out the old bit"  # the model's output is kept for evaluation

# Publish: only the author; public guides reach the feed, filtered by category.
assert api.post(f"/guides/{gid}/publish", json={"visibility": "public"}, headers=MIN).status_code == 404
c = api.post(f"/guides/{gid}/publish", json={"visibility": "public", "title": "Change a drill bit",
                                             "category": "workshop_tools"}, headers=LUIS).json()
assert c["title"] == "Change a drill bit" and c["published_at"]
assert [x["guide_id"] for x in api.get("/feed", headers=MIN).json()] == [gid]
assert api.get("/feed?category=cooking", headers=MIN).json() == []
assert api.post(f"/guides/{gid}/publish", json={"visibility": "public"}, headers=MIN).status_code == 403

# Reactions, progress, library.
assert api.post(f"/guides/{gid}/like", headers=MIN).json() == {"likes": 1, "saves": 0, "liked": True, "saved": False}
api.post(f"/guides/{gid}/save", headers=MIN)
assert api.put(f"/guides/{gid}/progress", json={"step": 9}, headers=MIN).status_code == 422
api.put(f"/guides/{gid}/progress", json={"step": 3}, headers=MIN)
lib = api.get("/library", headers=MIN).json()
assert [x["guide_id"] for x in lib["saved"]] == [gid] and lib["mine"] == []
assert lib["continue"][0]["step"] == 3 and lib["continue"][0]["next_step_title"] == "Insert the new drill bit"
assert [x["guide_id"] for x in lib["liked"]] == [gid]
lib = api.get("/library", headers=LUIS).json()
assert [x["guide_id"] for x in lib["mine"]] == [gid]
assert lib["profile"] == {"guides": 1, "learners": 1, "likes": 1}  # min liked it and opened step 3
assert api.delete(f"/guides/{gid}/like", headers=MIN).json()["likes"] == 0

# Clip and covers come from the source footage.
if guides.source_path(guides.load(gid)[0]).exists():
    r = api.get(f"/guides/{gid}/clips/2.mp4", headers=MIN)
    assert r.status_code == 200 and r.headers["content-type"] == "video/mp4" and len(r.content) > 10_000
    assert 9.5 <= guides.duration_of(next((guides.GUIDES / gid / "clips").glob("02_*.mp4"))) <= 10.5
    assert api.get(f"/guides/{gid}/cover.jpg", headers=MIN).content[:2] == b"\xff\xd8"
else:
    print("skipped clip check: drill-bit reference video not downloaded")

server.worker.shutdown(wait=True)
for p in server.UPLOADS.glob("*"):
    p.unlink()
server.UPLOADS.rmdir()
print("ok")
