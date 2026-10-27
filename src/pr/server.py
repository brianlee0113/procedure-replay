"""Local HTTP server for the iPhone app: serves Guides, takes recordings, returns Reviews.

    uv run uvicorn pr.server:app --host 0.0.0.0 --port 8000

Runs on the Mac next to the pipeline, so the Meta API key never leaves it. Endpoints:

    GET  /tasks                              tasks that have a Guide
    GET  /guide/{task}                       checklist (with the expert's edits) + frame URLs
    GET  /guide/{task}/frames/{index}.jpg    reference frame of one step
    PUT  /guide/{task}/steps/{index}         expert edit: title / description / done_when
    POST /reviews                            multipart: task, video, and source_video_id or license + creator
    GET  /reviews/{id}                       status, then per-step answers and flags
    GET  /videos/{id}                        the uploaded recording, for evidence playback

A recording goes through the same license gate as dataset videos: it gets a row in data/manifest_app.csv
(not in git) that either inherits the license of the video fed to the mock glasses (source_video_id) or
states one (license + creator, e.g. your own recording under CC-BY-4.0). A row the gate refuses is never
processed. Expert edits are kept in results/app/edits/<task>.json, so the committed checklists and the
evaluation are unchanged.
"""

import json
import shutil
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from pr.align import align, keystep_of, unanswered
from pr.client import RESULTS, MetaClient
from pr.judge import judge
from pr.license_check import (APP_MANIFEST, FIELDS, ROOT, LicenseError, append_manifest_row, check_row, find_row,
                              load_all, local_path, require_allowed)
from pr.order import keystep_pairs
from pr.steps import CHECKLISTS, load_tasks

UPLOADS = ROOT / "data" / "uploads"
APP = RESULTS / "app"
EDITS = APP / "edits"
REVIEWS = APP / "reviews"
EDITABLE = ("title", "description", "done_when")

app = FastAPI(title="ProcedureReplay")
# One review at a time: Muse Spark calls are rate limited and each review uploads a whole video.
worker = ThreadPoolExecutor(max_workers=1)
lock = threading.Lock()
_client: MetaClient | None = None


def client() -> MetaClient:
    global _client
    _client = _client or MetaClient()
    return _client


def eval_ids() -> set[str]:
    """Videos of the dev and test sets and their source takes: never used to learn order rules (as in run_eval)."""
    ids = set()
    for name in ("ground_truth.jsonl", "ground_truth_dev.jsonl"):
        path = ROOT / "data" / name
        if path.exists():
            ids |= {json.loads(l)["video_id"] for l in path.read_text().splitlines() if l.strip()}
    return ids | {v.split("__")[0] for v in ids}


def checklist(task: str) -> dict:
    path = CHECKLISTS / f"{task}.json"
    if not path.exists():
        raise HTTPException(404, f"no Guide for task {task!r}")
    data = json.loads(path.read_text())
    edits = EDITS / f"{task}.json"
    if edits.exists():
        changed = json.loads(edits.read_text())
        for s in data["steps"]:
            s.update(changed.get(str(s["index"]), {}))
    return data


def write_json(path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)


@app.get("/tasks")
def tasks() -> list[dict]:
    cfg = load_tasks()
    return [{"task": t, "name": c["name"], "steps": len(json.loads((CHECKLISTS / f"{t}.json").read_text())["steps"])}
            for t, c in cfg.items() if (CHECKLISTS / f"{t}.json").exists()]


@app.get("/guide/{task}")
def guide(task: str) -> dict:
    data = checklist(task)
    for s in data["steps"]:
        s["frame_url"] = f"/guide/{task}/frames/{s['index']}.jpg"
    data["name"] = load_tasks()[task]["name"]
    return data


@app.get("/guide/{task}/frames/{index}.jpg")
def frame(task: str, index: int) -> FileResponse:
    path = CHECKLISTS / f"{task}_step{index:02d}.jpg"
    if not path.exists():
        raise HTTPException(404, "no frame")
    return FileResponse(path, media_type="image/jpeg")


class StepEdit(BaseModel):
    title: str | None = None
    description: str | None = None
    done_when: str | None = None


@app.put("/guide/{task}/steps/{index}")
def edit_step(task: str, index: int, edit: StepEdit) -> dict:
    if not any(s["index"] == index for s in checklist(task)["steps"]):
        raise HTTPException(404, f"no step {index}")
    path = EDITS / f"{task}.json"
    with lock:
        edits = json.loads(path.read_text()) if path.exists() else {}
        edits.setdefault(str(index), {}).update({k: v for k, v in edit.model_dump().items() if v is not None})
        write_json(path, edits)
    return next(s for s in guide(task)["steps"] if s["index"] == index)


def run_review(review_id: str, video_id: str, task: str) -> None:
    path = REVIEWS / f"{review_id}.json"
    state = json.loads(path.read_text())
    try:
        write_json(path, {**state, "status": "running"})
        cfg = load_tasks()[task]
        cl = checklist(task)
        matches = align(video_id, cl, client(), cfg["name"])
        if gaps := unanswered(matches, cl):
            raise RuntimeError(f"the review has no answer for steps {gaps}")
        before = keystep_pairs(task, load_all(), eval_ids())
        flags = judge(matches, keystep_of(cl), cfg["keysteps"], before)
        write_json(path, {**state, "status": "done", "steps": matches, "flags": flags,
                          "finished": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    except Exception as e:  # report any failure to the app instead of leaving the review "running"
        write_json(path, {**state, "status": "error", "error": f"{type(e).__name__}: {e}"})


@app.post("/reviews", status_code=202)
def create_review(task: str = Form(...), video: UploadFile = File(...), source_video_id: str | None = Form(None),
                  license: str | None = Form(None), creator: str | None = Form(None)) -> dict:
    checklist(task)
    if source_video_id:
        try:
            src = require_allowed(source_video_id)
        except LicenseError as e:
            raise HTTPException(403, str(e))
        rights = {k: src[k] for k in ("creator", "source_url", "license")}
    elif license and creator:
        rights = {"creator": creator, "source_url": "recorded with the ProcedureReplay app", "license": license}
    else:
        raise HTTPException(400, "send source_video_id (the video fed to the mock glasses) or license + creator")

    review_id = uuid.uuid4().hex[:12]
    video_id = f"app_{review_id}"
    suffix = ".mov" if (video.filename or "").lower().endswith(".mov") else ".mp4"
    dest = UPLOADS / f"{video_id}{suffix}"
    row = {"video_id": video_id, "task": task, "role": "trainee", "local_path": str(dest.relative_to(ROOT)), **rights}
    if problems := check_row(row):  # refuse before anything is stored
        raise HTTPException(403, f"{video_id}: refused — " + "; ".join(problems))
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as f:
        shutil.copyfileobj(video.file, f)
    with lock:
        if not APP_MANIFEST.exists():
            APP_MANIFEST.write_text(",".join(FIELDS) + "\n")
        append_manifest_row(row, APP_MANIFEST)
    require_allowed(video_id)

    state = {"id": review_id, "video_id": video_id, "task": task, "status": "queued",
             "video_url": f"/videos/{review_id}", "source_video_id": source_video_id,
             "created": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    write_json(REVIEWS / f"{review_id}.json", state)
    worker.submit(run_review, review_id, video_id, task)
    return state


@app.get("/reviews/{review_id}")
def get_review(review_id: str) -> dict:
    path = REVIEWS / f"{review_id}.json"
    if not path.exists():
        raise HTTPException(404, "no such review")
    return json.loads(path.read_text())


@app.get("/videos/{review_id}")
def video(review_id: str) -> FileResponse:
    try:
        row = find_row(f"app_{review_id}")
    except LicenseError:
        raise HTTPException(404, "no such video")
    return FileResponse(local_path(row), media_type="video/quicktime" if row["local_path"].endswith(".mov")
                        else "video/mp4")
