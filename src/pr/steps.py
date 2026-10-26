"""extract_steps(ref_video) -> checklist JSON via Muse Spark structured output.

The proxy shows an MM:SS.s clock in its top-left corner; Muse Spark's frame sampling is undocumented,
so the prompt asks it to read step boundaries from that clock.
"""

import json
from pathlib import Path

import cv2
import yaml

from pr.client import RESULTS, MetaClient
from pr.frames import grab_frame
from pr.track import prepare

ROOT = Path(__file__).resolve().parents[2]
CHECKLISTS = RESULTS / "checklists"

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["task_summary", "steps"],
    "properties": {
        "task_summary": {"type": "string"},
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["index", "title", "description", "start_s", "end_s", "key_objects"],
                "properties": {
                    "index": {"type": "integer"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "start_s": {"type": "number"},
                    "end_s": {"type": "number"},
                    "key_objects": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
}

PROMPT = """This video shows one person performing the manual task: {task_name}.
A clock in the top-left corner shows elapsed time as MM:SS.s. The video is {duration:.1f} seconds long.

Split the video into the ordered physical steps a trainee must perform to complete the task
(about {expected} steps). Each step is one distinct action that changes the state of the object being
worked on. Skip intros, talking, and idle time between steps.

For each step give:
- index: 1-based order
- title: short imperative phrase, e.g. "Remove the old toner cartridge"
- description: one sentence on what the hands do
- start_s, end_s: seconds, read from the on-screen clock; steps must not overlap and must be in time order
- key_objects: which of these objects are handled in the step: {objects}
"""


def load_tasks() -> dict:
    return yaml.safe_load((ROOT / "config" / "tasks.yaml").read_text())


def extract_steps(ref_video: str, task: str, client: MetaClient) -> dict:
    cfg = load_tasks()[task]
    p = prepare(ref_video, client)
    vid, duration = p["video_id"], p["info"]["duration"]
    prompt = PROMPT.format(task_name=cfg["name"], duration=duration, expected=cfg["expected_steps"],
                           objects=", ".join(cfg["object_prompts"]))
    print(f"  Muse Spark ({client.spark_model}) segmenting {vid} ({duration:.0f}s)…")
    checklist = client.spark_json(p["file_id"], prompt, SCHEMA, "procedure_checklist", vid, purpose="steps")
    checklist.update({"task": task, "reference_video": vid, "duration": duration, "model": client.spark_model})

    CHECKLISTS.mkdir(parents=True, exist_ok=True)
    for step in checklist["steps"]:
        frame = grab_frame(p["proxy"], (step["start_s"] + step["end_s"]) / 2)
        if frame is not None:
            name = f"{task}_step{step['index']:02d}.jpg"
            cv2.imwrite(str(CHECKLISTS / name), frame)
            step["reference_frame"] = f"results/checklists/{name}"
    (CHECKLISTS / f"{task}.json").write_text(json.dumps(checklist, indent=2))
    return checklist


def validate(checklist: dict, duration: float, expected: int) -> list[str]:
    """Problems with a checklist; empty means it is usable."""
    steps = checklist.get("steps", [])
    problems = []
    if abs(len(steps) - expected) > 2:
        problems.append(f"{len(steps)} steps, expected {expected}±2")
    for i, s in enumerate(steps):
        if s["index"] != i + 1:
            problems.append(f"step {i + 1} has index {s['index']}")
        if not 0 <= s["start_s"] < s["end_s"] <= duration + 1:
            problems.append(f"step {s['index']} span {s['start_s']}–{s['end_s']} invalid for {duration:.1f}s video")
        if i and s["start_s"] < steps[i - 1]["end_s"] - 0.5:
            problems.append(f"step {s['index']} overlaps or precedes step {s['index'] - 1}")
    return problems
