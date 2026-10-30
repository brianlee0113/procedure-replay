"""Guides in the app: the guide contract (docs/B0_guide_eval_plan.md §2), their storage, clips and covers.

A guide is three files under results/app/guides/<guide_id>/ (not in git):
    guide.json   the contract the AI track produces; the instructor's Draft edits are written into it
    model.json   the untouched model output, kept for evaluation
    meta.json    server-side fields that are not part of the contract: author, visibility, timestamps

Until the B2 pipeline exists, `from_checklist` builds a contract guide from a committed checklist
(results/checklists/<task>.json), so the app can be built against real steps and real footage.
"""

import json
import re
from difflib import SequenceMatcher
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import cv2
from pydantic import BaseModel, ConfigDict, Field, model_validator

from pr.client import RESULTS
from pr.frames import grab_frame, probe, trim
from pr.license_check import ROOT, find_row, local_path
from pr.steps import CHECKLISTS, load_tasks
from pr.transcribe import spoken

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
EPS = 0.01  # seconds; absorbs float rounding in model and label times
QUOTE_MIN_SIMILARITY = 0.9


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a stored guide with v0 fields (inputs_used) is refused, not mapped


class Clip(Strict):
    start_s: float
    end_s: float


class Quote(Strict):
    """Verbatim instructor words from consecutive transcript turns (0-based positions in `turns`)."""
    text: str
    turn_ids: list[int] = Field(min_length=1)
    start_s: float
    end_s: float


class Step(Strict):
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


class Guide(Strict):
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
    inputs_provided: dict[str, bool]  # what the model was given, not proof that it used it
    provenance: dict

    @model_validator(mode="after")
    def steps_in_order(self):
        if [s.index for s in self.steps] != list(range(1, len(self.steps) + 1)):
            raise ValueError("step indexes must be 1, 2, 3, ... in order")
        for a, b in zip(self.steps, self.steps[1:]):
            if b.start_s < a.end_s:
                raise ValueError(f"steps {a.index} and {b.index} overlap or are out of order")
        for s in self.steps:
            c = s.clip
            if not (0 <= c.start_s <= s.start_s < s.end_s <= c.end_s <= self.duration_s + EPS):
                raise ValueError(f"step {s.index}: need 0 <= clip start <= start < end <= clip end <= duration")
            if s.start_s - c.start_s > CLIP_PAD_S + EPS or c.end_s - s.end_s > CLIP_PAD_S + EPS:
                raise ValueError(f"step {s.index}: clip pads the step by more than {CLIP_PAD_S}s")
            if not s.start_s <= s.cover_s <= s.end_s:
                raise ValueError(f"step {s.index}: cover_s must be inside the step")
            if s.quote and not s.quote.start_s <= s.quote.end_s:
                raise ValueError(f"step {s.index}: quote ends before it starts")
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


def normalize(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9' ]+", " ", text.lower()).split())


def best_span(quote: str, words: list[str]) -> tuple[float, int, int]:
    """(similarity, first, end) of the span words[first:end] that best matches the quote (1.0 = verbatim after
    normalizing); `words` are normalized."""
    q = normalize(quote)
    n = len(q.split())
    if not n or not words:
        return 0.0, 0, 0
    spans = ((i, i + k) for k in range(max(1, n - 2), n + 3) for i in range(len(words) - k + 1))
    return max(((SequenceMatcher(None, q, " ".join(words[a:b])).ratio(), a, b) for a, b in spans), default=(0.0, 0, 0))


def quote_similarity(quote: str, said: str) -> float:
    """Best match of the quote against any word span of what was said (1.0 = verbatim after normalizing)."""
    return best_span(quote, normalize(said).split())[0]


def quote_times(quote: str, turns: list[dict]) -> tuple[float, float, float]:
    """(similarity, start_s, end_s) of the quote inside consecutive turns. The transcriber gives no word times,
    so each turn's time is spread over its words by length; a turn runs ~17 s, a step's clip ~10 s."""
    words, times = [], []
    for t in turns:
        ws = normalize(spoken(t["text"])).split()
        total, pos = sum(len(w) + 1 for w in ws) or 1, 0
        for w in ws:
            start = t["start_s"] + (t["end_s"] - t["start_s"]) * pos / total
            pos += len(w) + 1
            words.append(w)
            times.append((start, t["start_s"] + (t["end_s"] - t["start_s"]) * pos / total))
    sim, a, b = best_span(quote, words)
    if b <= a:
        return sim, turns[0]["start_s"], turns[-1]["end_s"]
    return sim, round(times[a][0], 2), round(times[b - 1][1], 2)


def quote_errors(guide: Guide, transcript: dict | None = None) -> list[str]:
    """Quote checks that need the transcript (§2, §4.4): turns exist and are consecutive, the words are in
    them, the quote's times are where its words are (quote_times), and those lie inside the step's clip
    (± CLIP_PAD_S). [] when every quote passes."""
    quoted = [s for s in guide.steps if s.quote]
    if not quoted:
        return []
    if transcript is None:
        path = ROOT / guide.provenance.get("transcript_id", "")
        if not path.is_file():
            return [f"guide has quotes but no readable transcript_id: {path}"]
        transcript = json.loads(path.read_text())
    turns, errors = transcript["turns"], []
    for s in quoted:
        q, where = s.quote, f"step {s.index}"
        ids = q.turn_ids
        if ids != list(range(ids[0], ids[0] + len(ids))) or not 0 <= ids[0] <= ids[-1] < len(turns):
            errors.append(f"{where}: turn_ids {ids} are not consecutive turns of {len(turns)}")
            continue
        said = turns[ids[0]:ids[-1] + 1]
        sim, start, end = quote_times(q.text, said)
        if sim < QUOTE_MIN_SIMILARITY:
            errors.append(f"{where}: quote not in turns {ids} (similarity {sim:.2f})")
        bounds = (said[0]["start_s"], said[-1]["end_s"])  # guides built before quote_times (10/30) used these
        if not any(abs(q.start_s - a) <= EPS and abs(q.end_s - b) <= EPS for a, b in ((start, end), bounds)):
            errors.append(f"{where}: quote times are not where its words are in turns {ids}")
        if q.start_s < s.clip.start_s - CLIP_PAD_S or q.end_s > s.clip.end_s + CLIP_PAD_S:
            errors.append(f"{where}: quoted words fall outside the clip")
    return errors


def from_checklist(task: str, guide_id: str, category: str, tools: list[str] | None = None) -> Guide:
    """Contract guide from a committed checklist (stand-in for the B2 pipeline)."""
    cl = json.loads((CHECKLISTS / f"{task}.json").read_text())
    duration = cl["duration"]
    steps = []
    for s in cl["steps"]:
        steps.append(Step(
            index=s["index"], title=s["title"], instruction=s["description"], done_when=s["done_when"],
            start_s=s["start_s"], end_s=min(s["end_s"], duration),  # the model's last step can end past the video
            clip=padded(s["start_s"], min(s["end_s"], duration), duration),
            cover_s=(s["start_s"] + min(s["end_s"], duration)) / 2, key_objects=s.get("key_objects", [])))
    return Guide(
        guide_id=guide_id, source_video_id=cl["reference_video"], duration_s=duration,
        title=load_tasks()[task]["name"], summary=cl["task_summary"], category=category, tools=tools or [],
        steps=steps, inputs_provided={"video": True, "transcript": False, "on_screen_text": False},
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
