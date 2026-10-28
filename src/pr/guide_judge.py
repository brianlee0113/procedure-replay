"""judge_guide(guide, labels, ...) -> per-step judgments for pr.guide_eval (docs/B0_guide_eval_plan.md §4.1–4.2).

One Muse Spark call per predicted step that has candidate units. The call sees the step's loop clip (cut from
the muted 5 fps proxy, so the clock shows source-video time), what was said inside the clip, the guide step,
and the candidate labels, numbered. It answers, per candidate, whether the step is the same action, and the
4-item rubric. Matching is done in code from these answers, never by the judge.

The judge is a separate call with its own prompt from the builder (same model family; self-preference is
checked by blind human scoring, §7 and §4.2). Answers are cached per (guide, step, JUDGE_VERSION).
"""

import json
from pathlib import Path

from pr.client import MetaClient
from pr.frames import PROXY_DIR, trim
from pr.guide_eval import Unit, candidates, coarse_units, fine_units, preds_of
from pr.track import prepare

JUDGE_VERSION = "j-v1"
RUBRIC = ["action_matches", "objects_correct", "done_when_observable", "actionable"]

SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["candidates", "rubric"],
    "properties": {
        "candidates": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["number", "same_action", "why"],
            "properties": {"number": {"type": "integer"}, "same_action": {"type": "boolean"},
                           "why": {"type": "string"}}}},
        "rubric": {"type": "object", "additionalProperties": False, "required": RUBRIC + ["why"],
                   "properties": {**{k: {"type": "boolean"} for k in RUBRIC}, "why": {"type": "string"}}},
    },
}

PROMPT = """You are checking one step of a step-by-step guide that was written from a first-person video of a
hands-on job. The attached clip is the part of the video the guide loops for this step. The clock in its
top-left corner shows time in the original video (MM:SS.s).

The guide step:
  title: {title}
  instruction: {instruction}
  done when: {done_when}
  key objects: {objects}
  step bounds: {start:.1f}–{end:.1f} s (the clip adds up to 1 s on each side)
{said}
A person who watched the whole video labelled these steps, which overlap this guide step in time:
{labels}

1. For each numbered label: same_action = true if the guide step describes that action, i.e. a trainee who
   follows the guide step would be doing what the label names. A label made of several actions joined by
   " + " is the same action only if the guide step covers every one of them. Partial or different actions
   that happen to share the time span are false.
2. Rubric for the guide step, judged against what the clip shows:
   - action_matches: the instruction matches what the hands do in the clip
   - objects_correct: the key objects are right, and no object or tool is named that is not in the clip
   - done_when_observable: the done-when state can be seen in the clip and is correct
   - actionable: a first-timer can act on the instruction (imperative, specific, at most 2 sentences)
Give a short reason for each answer."""


def step_clip(proxy: Path, proxy_id: str, step) -> Path:
    out = PROXY_DIR / "judge" / f"{proxy_id}__{step.clip.start_s:.2f}-{step.clip.end_s:.2f}.mp4"
    return out if out.exists() else trim(proxy, step.clip.start_s, step.clip.end_s - step.clip.start_s, out)


def said_in(transcript: dict | None, start: float, end: float) -> str:
    turns = [t for t in (transcript or {}).get("turns", []) if t["end_s"] > start and t["start_s"] < end]
    if not turns:
        return ""
    lines = "\n".join(f"  [{t['start_s']:.1f}–{t['end_s']:.1f} s] {t['text']}" for t in turns)
    return f"\nWhat was said during the clip (speech-to-text):\n{lines}\n"


def judge_guide(guide, labels: list[dict], merges: list[list[str]], cache_path: Path,
                client: MetaClient | None = None, transcript: dict | None = None, model: str | None = None) -> dict:
    """{step index: {"same_action": {unit key: bool}, "rubric": {...}, "why": {...}}}, cached in cache_path."""
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    cache = cache if cache.get("judge_version") == JUDGE_VERSION else {"judge_version": JUDGE_VERSION, "steps": {}}
    units = list({u.key: u for u in fine_units(labels) + coarse_units(labels, merges)}.values())
    cands = candidates(preds_of(guide), units)
    todo = [s for s in guide.steps if cands[s.index] and str(s.index) not in cache["steps"]]
    if todo:
        client = client or MetaClient()
        p = prepare(guide.source_video_id, client, audio=False)
        for s in todo:
            cache["steps"][str(s.index)] = judge_step(s, cands[s.index], p, client, transcript, model)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(cache, indent=2))
    return {int(i): v for i, v in cache["steps"].items()}


def judge_step(step, units: list[Unit], prepared: dict, client: MetaClient, transcript: dict | None,
               model: str | None) -> dict:
    clip = step_clip(prepared["proxy"], prepared["video_id"], step)
    labels = "\n".join(f"  {n}. {' + '.join(u.labels)}  ({u.start:.1f}–{u.end:.1f} s)" for n, u in enumerate(units, 1))
    text = PROMPT.format(title=step.title, instruction=step.instruction, done_when=step.done_when,
                         objects=", ".join(step.key_objects) or "none", start=step.start_s, end=step.end_s,
                         said=said_in(transcript, step.clip.start_s, step.clip.end_s), labels=labels)
    answer = client.spark_json(client.upload(clip), text, SCHEMA, "guide_step_judgment",
                               f"{prepared['video_id']}#step{step.index}", purpose="judge", model=model)
    by_number = {c["number"]: c for c in answer["candidates"]}
    return {
        "same_action": {u.key: bool(by_number.get(n, {}).get("same_action")) for n, u in enumerate(units, 1)},
        "rubric": {k: answer["rubric"][k] for k in RUBRIC},
        "why": {"candidates": {u.key: by_number.get(n, {}).get("why", "no answer") for n, u in enumerate(units, 1)},
                "rubric": answer["rubric"]["why"]},
        "judge_version": JUDGE_VERSION, "model": model or client.spark_model,
    }
