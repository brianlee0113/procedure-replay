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

Guides (the app's main flow; contract in docs/B0_guide_eval_plan.md §2). The caller is named by the
X-User header (or ?user=, default "me"); drafts are visible to their author only, private guides to anyone with
the id, public guides also appear in the feed.

    GET    /categories                       category taxonomy (id → label)
    GET    /sources/{video_id}/transcript    timed turns of a licensed video (feeds the simulated glasses speech)
    POST   /recordings                       multipart: video + source_video_id or license + creator (+ marks) → job
    GET    /jobs/{id}                        stages (upload, transcribe, read_text, split, write) + guide_id
    GET    /guides/{id}                      guide, meta, reactions, my progress
    PATCH  /guides/{id}/steps/{index}        author's Draft edit: text, or re-cut start_s / end_s
    POST   /guides/{id}/publish              title / summary / category, visibility private|public
    GET    /guides/{id}/cover.jpg            guide cover; /guides/{id}/steps/{index}/cover.jpg per step
    GET    /guides/{id}/clips/{index}.mp4    the step's loop clip
    POST   /guides/{id}/like|save            DELETE to undo
    PUT    /guides/{id}/progress             {"step": n}: where I stopped
    GET    /feed?category=                   public guides, newest first
    GET    /library                          continue (in progress), saved, mine

A recording goes through the same license gate as dataset videos: it gets a row in data/manifest_app.csv
(not in git) that either inherits the license of the video fed to the mock glasses (source_video_id) or
states one (license + creator, e.g. your own recording under CC-BY-4.0). A row the gate refuses is never
processed. Expert edits are kept in results/app/edits/<task>.json, so the committed checklists and the
evaluation are unchanged.
"""

import json
import os
import re
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from pr import build, guides
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


def store_upload(video_id: str, video: UploadFile, task: str, role: str, source_video_id: str | None,
                 license: str | None, creator: str | None) -> str:
    """Save an app recording with a manifest row that passes the license gate, or refuse it before storing."""
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
    suffix = ".mov" if (video.filename or "").lower().endswith(".mov") else ".mp4"
    dest = UPLOADS / f"{video_id}{suffix}"
    row = {"video_id": video_id, "task": task, "role": role, "local_path": str(dest.relative_to(ROOT)), **rights}
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
    return video_id


@app.post("/reviews", status_code=202)
def create_review(task: str = Form(...), video: UploadFile = File(...), source_video_id: str | None = Form(None),
                  license: str | None = Form(None), creator: str | None = Form(None)) -> dict:
    checklist(task)
    review_id = uuid.uuid4().hex[:12]
    video_id = store_upload(f"app_{review_id}", video, task, "trainee", source_video_id, license, creator)
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


# ---------------------------------------------------------------------------------------------------------
# Guides: record → build → Draft → publish → feed / library
# ---------------------------------------------------------------------------------------------------------

JOBS = APP / "jobs"
REACTIONS = APP / "reactions.json"
PROGRESS = APP / "progress.json"
STAGES = ("upload", "transcribe", "read_text", "split", "write")
# The stand-in builder has nothing to wait for; a short pause per stage lets the app's Building screen show them.
STAGE_DELAY_S = float(os.environ.get("PR_STAGE_DELAY_S", "0.6"))
DEFAULT_CATEGORY = {"pc_repair": "repair_maintenance", "drill_bit": "workshop_tools", "home_cooking": "cooking"}


def current_user(x_user: str | None = Header(None, alias="X-User"), user: str | None = Query(None)) -> str:
    """The X-User header, or ?user= for requests that cannot set headers (images loaded by the app)."""
    return x_user or user or "me"


USER = Depends(current_user)


def read_json(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def b2_builder(job: dict, set_stage) -> guides.Guide:
    """The B2 builder (pr.build) on the uploaded recording itself. A failure fails the job; there is no fallback
    to the checklist, which would show clips the instructor never filmed."""
    guide, raw = build.build_guide(job["video_id"], job["guide_id"], marks=job.get("marks"), set_stage=set_stage)
    write_json(guides.guide_dir(guide.guide_id) / "raw.json", raw)  # the model's answer, before postprocess
    return guide


def checklist_builder(job: dict, set_stage) -> guides.Guide:
    """Offline stand-in, only when PR_BUILDER=checklist (API tests, demo without network): the committed checklist
    of the recording's task, on the dataset's reference video, not the recording."""
    for stage in STAGES[1:]:
        set_stage(stage)
        time.sleep(STAGE_DELAY_S)
    task = job["task"]
    return guides.from_checklist(task, job["guide_id"], DEFAULT_CATEGORY.get(task, "other"))


build_guide = checklist_builder if os.environ.get("PR_BUILDER") == "checklist" else b2_builder


def run_job(job_id: str) -> None:
    path = JOBS / f"{job_id}.json"
    job = json.loads(path.read_text())

    def set_stage(stage: str) -> None:
        job["stages"] = {s: ("done" if STAGES.index(s) < STAGES.index(stage) else
                             "running" if s == stage else "queued") for s in STAGES}
        job["status"] = "running"
        write_json(path, job)

    try:
        if window := job.get("simulate"):  # cut the licensed source here, not in the upload request (it re-encodes)
            set_stage("upload")
            job["simulated_from"] = simulated_capture(job["video_id"], **window)
        guide = build_guide(job, set_stage)
        guides.save(guide, guides.Meta(author=job["author"], author_name=job["author_name"], job_id=job_id))
        job.update(status="done", stages={s: "done" for s in STAGES}, finished=guides.now())
    except Exception as e:  # report any failure to the app instead of leaving the job "running"
        job.update(status="error", error=f"{type(e).__name__}: {e}")
    write_json(path, job)


@app.get("/categories")
def categories() -> dict:
    return guides.CATEGORIES


@app.get("/sources/{video_id}/transcript")
def source_transcript(video_id: str) -> dict:
    """What is said in a licensed video, as timed turns (Muse Voice Transcribe, cached). The app plays these
    through MockDeviceKit's speech recognizer while that video is the simulated glasses feed, standing in for
    the glasses' own on-device recognition of the instructor's voice."""
    from pr.transcribe import transcribe

    try:
        require_allowed(video_id)
    except LicenseError as e:
        raise HTTPException(404, str(e))
    t = transcribe(video_id)
    return {"video_id": video_id, "model": t.get("model"), "lines": caption_lines(t["turns"])}


def caption_lines(turns: list[dict]) -> list[dict]:
    """Muse Voice Transcribe turns can run 20+ s and carry <|speaker_X|> markers inside. Split each turn at
    those markers into caption lines and spread the turn's time over them by length (no word timestamps)."""
    lines = []
    for u in turns:
        parts = [p.strip() for p in re.split(r"<\|speaker_[^|]*\|>", u["text"]) if p.strip()]
        total = sum(len(p) for p in parts) or 1
        t = u["start_s"]
        for p in parts:
            dt = (u["end_s"] - u["start_s"]) * len(p) / total
            lines.append({"start_s": round(t, 2), "end_s": round(t + dt, 2), "text": p})
            t += dt
    return lines


@app.post("/recordings", status_code=202)
def create_recording(task: str = Form(...), video: UploadFile = File(...), source_video_id: str | None = Form(None),
                     license: str | None = Form(None), creator: str | None = Form(None),
                     author_name: str = Form("You"), marks: str | None = Form(None),
                     source_start_s: float | None = Form(None), source_end_s: float | None = Form(None),
                     user: str = USER) -> dict:
    job_id = uuid.uuid4().hex[:12]
    video_id = store_upload(f"app_rec_{job_id}", video, task, "reference", source_video_id, license, creator)
    window = None
    if source_video_id and source_start_s is not None and source_end_s is not None:
        if source_end_s - max(0.0, source_start_s) < 1.0:
            raise HTTPException(422, f"source window {source_start_s:.1f}–{source_end_s:.1f} s is shorter than a second")
        window = {"source_video_id": source_video_id, "start_s": source_start_s, "end_s": source_end_s}
    job = {"id": job_id, "video_id": video_id, "task": task, "guide_id": f"g_{job_id}", "author": user,
           "author_name": author_name, "status": "queued", "created": guides.now(),
           # seconds where the instructor tapped "Mark step" while recording; a hint for the B2 builder
           "marks": parse_marks(marks),
           "simulate": window,  # run_job turns the recording into this stretch of the source (simulated_capture)
           "stages": {s: ("done" if s == "upload" and not window else "queued") for s in STAGES}}
    write_json(JOBS / f"{job_id}.json", job)
    worker.submit(run_job, job_id)
    return job


def simulated_capture(video_id: str, source_video_id: str, start_s: float, end_s: float) -> dict:
    """MockDeviceKit glasses send video only, so the app's file is a silent re-capture. When the app says which
    stretch of the licensed feed video played while it recorded, the recording becomes that stretch of the source,
    with its sound: what real glasses would have seen and heard. The app's own file is kept as <id>_glasses.mp4."""
    from pr.frames import probe, trim

    row = find_row(video_id)
    dest = local_path(row)
    src = local_path(require_allowed(source_video_id))
    duration = probe(src)["duration"]
    start, end = max(0.0, start_s), min(duration, end_s)
    if end - start < 1.0:
        raise HTTPException(422, f"source window {start_s:.1f}–{end_s:.1f} s is shorter than a second")
    dest.rename(dest.with_name(f"{dest.stem}_glasses{dest.suffix}"))
    trim(src, start, end - start, dest.with_suffix(".mp4"))
    if dest.suffix != ".mp4":  # the manifest row points at the stored file; keep it valid
        dest.with_suffix(".mp4").rename(dest)
    return {"source_video_id": source_video_id, "start_s": round(start, 2), "end_s": round(end, 2)}


def parse_marks(marks: str | None) -> list[float]:
    try:
        values = json.loads(marks) if marks else []
        return sorted(float(v) for v in values)
    except (ValueError, TypeError):
        raise HTTPException(422, "marks must be a JSON list of seconds")


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    path = JOBS / f"{job_id}.json"
    if not path.exists():
        raise HTTPException(404, "no such job")
    return json.loads(path.read_text())


def visible(guide_id: str, user: str) -> tuple[guides.Guide, guides.Meta]:
    try:
        guide, meta = guides.load(guide_id)
    except KeyError:
        raise HTTPException(404, "no such guide")
    if meta.visibility == "draft" and meta.author != user:
        raise HTTPException(404, "no such guide")
    return guide, meta


def owned(guide_id: str, user: str) -> tuple[guides.Guide, guides.Meta]:
    guide, meta = visible(guide_id, user)
    if meta.author != user:
        raise HTTPException(403, "only the author can change this guide")
    return guide, meta


def reactions_of(guide_id: str, user: str) -> dict:
    r = read_json(REACTIONS, {}).get(guide_id, {"likes": [], "saves": []})
    return {"likes": len(r["likes"]), "saves": len(r["saves"]), "liked": user in r["likes"], "saved": user in r["saves"]}


def card(guide: guides.Guide, meta: guides.Meta, user: str) -> dict:
    return {"guide_id": guide.guide_id, "title": guide.title, "category": guide.category,
            "category_label": guides.CATEGORIES[guide.category], "steps": len(guide.steps),
            "duration_s": guide.duration_s, "author": meta.author, "author_name": meta.author_name,
            "author_role": meta.author_role, "visibility": meta.visibility, "published_at": meta.published_at,
            "cover_url": f"/guides/{guide.guide_id}/cover.jpg", **reactions_of(guide.guide_id, user)}


@app.get("/guides/{guide_id}")
def get_guide(guide_id: str, user: str = USER) -> dict:
    guide, meta = visible(guide_id, user)
    data = guide.model_dump()
    for s in data["steps"]:
        s["clip_url"] = f"/guides/{guide_id}/clips/{s['index']}.mp4"
        s["cover_url"] = f"/guides/{guide_id}/steps/{s['index']}/cover.jpg"
    return {"guide": data, "meta": meta.model_dump(), "category_label": guides.CATEGORIES[guide.category],
            "reactions": reactions_of(guide_id, user),
            "progress": read_json(PROGRESS, {}).get(user, {}).get(guide_id)}


class GuideStepEdit(BaseModel):
    title: str | None = None
    instruction: str | None = None
    done_when: str | None = None
    start_s: float | None = None
    end_s: float | None = None


@app.patch("/guides/{guide_id}/steps/{index}")
def edit_guide_step(guide_id: str, index: int, edit: GuideStepEdit, user: str = USER) -> dict:
    with lock:
        guide, meta = owned(guide_id, user)
        step = next((s for s in guide.steps if s.index == index), None)
        if step is None:
            raise HTTPException(404, f"no step {index}")
        changes = {k: v for k, v in edit.model_dump().items() if v is not None}
        updated = step.model_copy(update=changes)
        if "start_s" in changes or "end_s" in changes:  # re-cut: the loop clip and cover follow the new bounds
            updated.clip = guides.padded(updated.start_s, updated.end_s, guide.duration_s)
            updated.cover_s = (updated.start_s + updated.end_s) / 2
        try:
            guide = guides.Guide.model_validate({**guide.model_dump(), "steps": [
                (updated if s.index == index else s).model_dump() for s in guide.steps]})
        except ValueError as e:
            raise HTTPException(422, str(e))
        guides.save(guide, meta)
    return get_guide(guide_id, user)["guide"]["steps"][index - 1]


class Publish(BaseModel):
    visibility: guides.Literal["private", "public"]
    title: str | None = None
    summary: str | None = None
    category: guides.Category | None = None


@app.post("/guides/{guide_id}/publish")
def publish(guide_id: str, body: Publish, user: str = USER) -> dict:
    with lock:
        guide, meta = owned(guide_id, user)
        guide = guide.model_copy(update={k: v for k, v in body.model_dump().items() if v is not None and k != "visibility"})
        meta = meta.model_copy(update={"visibility": body.visibility, "published_at": meta.published_at or guides.now()})
        guides.save(guide, meta)
    return card(guide, meta, user)


@app.get("/guides/{guide_id}/cover.jpg")
def guide_cover(guide_id: str, user: str = USER) -> FileResponse:
    return FileResponse(guides.cover(visible(guide_id, user)[0]), media_type="image/jpeg")


@app.get("/guides/{guide_id}/steps/{index}/cover.jpg")
def step_cover(guide_id: str, index: int, user: str = USER) -> FileResponse:
    guide = visible(guide_id, user)[0]
    if not any(s.index == index for s in guide.steps):
        raise HTTPException(404, f"no step {index}")
    return FileResponse(guides.cover(guide, index), media_type="image/jpeg")


@app.get("/guides/{guide_id}/clips/{index}.mp4")
def step_clip(guide_id: str, index: int, user: str = USER) -> FileResponse:
    guide = visible(guide_id, user)[0]
    if not any(s.index == index for s in guide.steps):
        raise HTTPException(404, f"no step {index}")
    return FileResponse(guides.clip(guide, index), media_type="video/mp4")


def react(guide_id: str, kind: str, user: str, on: bool) -> dict:
    visible(guide_id, user)
    with lock:
        data = read_json(REACTIONS, {})
        r = data.setdefault(guide_id, {"likes": [], "saves": []})
        r[kind] = sorted(set(r[kind]) | {user}) if on else [u for u in r[kind] if u != user]
        write_json(REACTIONS, data)
    return reactions_of(guide_id, user)


@app.post("/guides/{guide_id}/like")
def like(guide_id: str, user: str = USER) -> dict:
    return react(guide_id, "likes", user, True)


@app.delete("/guides/{guide_id}/like")
def unlike(guide_id: str, user: str = USER) -> dict:
    return react(guide_id, "likes", user, False)


@app.post("/guides/{guide_id}/save")
def save_guide(guide_id: str, user: str = USER) -> dict:
    return react(guide_id, "saves", user, True)


@app.delete("/guides/{guide_id}/save")
def unsave_guide(guide_id: str, user: str = USER) -> dict:
    return react(guide_id, "saves", user, False)


class Progress(BaseModel):
    step: int


@app.put("/guides/{guide_id}/progress")
def set_progress(guide_id: str, body: Progress, user: str = USER) -> dict:
    guide, _ = visible(guide_id, user)
    if not 1 <= body.step <= len(guide.steps):
        raise HTTPException(422, f"step must be 1..{len(guide.steps)}")
    with lock:
        data = read_json(PROGRESS, {})
        data.setdefault(user, {})[guide_id] = body.step
        write_json(PROGRESS, data)
    return {"guide_id": guide_id, "step": body.step}


@app.get("/feed")
def feed(category: guides.Category | None = None, user: str = USER) -> list[dict]:
    cards = []
    for gid in guides.all_ids():
        guide, meta = guides.load(gid)
        if meta.visibility == "public" and (category is None or guide.category == category):
            cards.append(card(guide, meta, user))
    return sorted(cards, key=lambda c: c["published_at"] or "", reverse=True)


@app.get("/library")
def library(user: str = USER) -> dict:
    progress = read_json(PROGRESS, {}).get(user, {})
    reactions = read_json(REACTIONS, {})
    out = {"continue": [], "saved": [], "mine": []}
    for gid in guides.all_ids():
        guide, meta = guides.load(gid)
        if meta.visibility == "draft" and meta.author != user:
            continue
        c = card(guide, meta, user)
        if meta.author == user:
            out["mine"].append(c)
        if user in reactions.get(gid, {}).get("saves", []):
            out["saved"].append(c)
        if gid in progress and progress[gid] < len(guide.steps):
            step = guide.steps[progress[gid] - 1]
            out["continue"].append({**c, "step": progress[gid], "next_step_title": step.title})
    return out
