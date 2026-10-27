"""Guides in the app: the guide contract (docs/B0_guide_eval_plan.md §2), their storage, clips and covers.

A guide is two files under results/app/guides/<guide_id>/ (not in git):
    guide.json   the contract the AI track produces; the instructor's Draft edits are written into it
    model.json   the untouched model output, kept for evaluation
    meta.json    server-side fields that are not part of the contract: author, visibility, timestamps

Until the B2 pipeline exists, `from_checklist` builds a contract guide from a committed checklist
(results/checklists/<task>.json), so the app can be built against real steps and real footage.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import cv2
from pydantic import BaseModel, Field, model_validator

from pr.client import RESULTS
from pr.frames import grab_frame, probe, trim
from pr.license_check import find_row, local_path
from pr.steps import CHECKLISTS, load_tasks

APP = RESULTS / "app"
GUIDES = APP / "guides"

CATEGORIES = {
    "repair_maintenance": "Repair & maintenance",
    "electronics": "Electronics",
    "workshop_tools": "Workshop tools",
    "assembly": "Assembly",
    "cooking": "Cooking",
    "cleaning_household": "Cleaning & household",
    "crafts": "Crafts",
    "other": "Other",
}
Category = Literal[tuple(CATEGORIES)]
Visibility = Literal["draft", "private", "public"]
CLIP_PAD_S = 1.0


class Clip(BaseModel):
    start_s: float
    end_s: float


class Quote(BaseModel):
    text: str
    start_s: float


class Step(BaseModel):
    index: int
    title: str
    instruction: str
    done_when: str
    start_s: float
    end_s: float
    clip: Clip
    cover_s: float
    key_objects: list[str] = []
    quote: Quote | None = None
    on_screen_text: list[str] = []


class Guide(BaseModel):
    """Contract v1: produced by the AI track, consumed unchanged by the app."""
    contract_version: Literal[1] = 1
    guide_id: str
    source_video_id: str
    duration_s: float
    language: str = "en"
    title: str
    summary: str
    category: Category
    category_alternatives: list[Category] = []
    tools: list[str] = []
    steps: list[Step]
    inputs_used: dict[str, bool]
    provenance: dict

    @model_validator(mode="after")
    def steps_in_order(self):
        for a, b in zip(self.steps, self.steps[1:]):
            if b.start_s < a.end_s:
                raise ValueError(f"steps {a.index} and {b.index} overlap or are out of order")
        for s in self.steps:
            if not (s.start_s < s.end_s and s.clip.start_s <= s.start_s and s.clip.end_s >= s.end_s):
                raise ValueError(f"step {s.index}: clip must contain [start_s, end_s]")
        return self


class Meta(BaseModel):
    author: str
    author_name: str
    author_role: str = ""
    visibility: Visibility = "draft"
    created_at: str = Field(default_factory=lambda: now())
    published_at: str | None = None
    job_id: str | None = None


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)


def guide_dir(guide_id: str) -> Path:
    if not re.fullmatch(r"[a-z0-9_-]+", guide_id):
        raise KeyError(guide_id)
    return GUIDES / guide_id


def save(guide: Guide, meta: Meta) -> None:
    d = guide_dir(guide.guide_id)
    if not (d / "model.json").exists():
        write_json(d / "model.json", guide.model_dump())
    write_json(d / "guide.json", guide.model_dump())
    write_json(d / "meta.json", meta.model_dump())


def load(guide_id: str) -> tuple[Guide, Meta]:
    d = guide_dir(guide_id)
    if not (d / "guide.json").exists():
        raise KeyError(guide_id)
    return (Guide.model_validate_json((d / "guide.json").read_text()),
            Meta.model_validate_json((d / "meta.json").read_text()))


def all_ids() -> list[str]:
    return sorted(p.parent.name for p in GUIDES.glob("*/guide.json")) if GUIDES.exists() else []


def padded(start_s: float, end_s: float, duration_s: float) -> Clip:
    """Loop clip: the step plus up to CLIP_PAD_S each side, inside the video (labels can overrun it slightly)."""
    return Clip(start_s=min(start_s, max(0.0, start_s - CLIP_PAD_S)),
                end_s=max(end_s, min(duration_s, end_s + CLIP_PAD_S)))


def from_checklist(task: str, guide_id: str, category: str, tools: list[str] | None = None) -> Guide:
    """Contract guide from a committed checklist (stand-in for the B2 pipeline)."""
    cl = json.loads((CHECKLISTS / f"{task}.json").read_text())
    duration = cl["duration"]
    steps = []
    for s in cl["steps"]:
        steps.append(Step(
            index=s["index"], title=s["title"], instruction=s["description"], done_when=s["done_when"],
            start_s=s["start_s"], end_s=s["end_s"],
            clip=padded(s["start_s"], s["end_s"], duration),
            cover_s=(s["start_s"] + s["end_s"]) / 2, key_objects=s.get("key_objects", [])))
    return Guide(
        guide_id=guide_id, source_video_id=cl["reference_video"], duration_s=duration,
        title=load_tasks()[task]["name"], summary=cl["task_summary"], category=category, tools=tools or [],
        steps=steps, inputs_used={"video": True, "transcript": False, "on_screen_text": False},
        provenance={"model": cl.get("model", ""), "builder": "from_checklist", "task": task, "created_at": now()})


def source_path(guide: Guide) -> Path:
    return local_path(find_row(guide.source_video_id))


def clip(guide: Guide, index: int) -> Path:
    """The step's loop clip, cut from the source video on first request and cached."""
    step = next(s for s in guide.steps if s.index == index)
    out = guide_dir(guide.guide_id) / "clips" / f"{index:02d}_{step.clip.start_s:.2f}_{step.clip.end_s:.2f}.mp4"
    if not out.exists():
        trim(source_path(guide), step.clip.start_s, step.clip.end_s - step.clip.start_s, out)
    return out


def cover(guide: Guide, index: int | None = None) -> Path:
    """JPEG of the step's cover frame; with no index, the guide cover (the middle step's frame)."""
    step = guide.steps[len(guide.steps) // 2] if index is None else next(s for s in guide.steps if s.index == index)
    out = guide_dir(guide.guide_id) / "covers" / f"{step.index:02d}_{step.cover_s:.2f}.jpg"
    if not out.exists():
        frame = grab_frame(source_path(guide), step.cover_s)
        if frame is None:
            raise FileNotFoundError(f"no frame at {step.cover_s}s in {guide.source_video_id}")
        out.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(out), frame)
    return out


def duration_of(path: Path) -> float:
    return probe(path)["duration"]
