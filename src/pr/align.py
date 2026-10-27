"""align(trainee_video, checklist) -> which checklist step happens where in the trainee video.

Muse Spark watches the trainee's proxy (same on-screen clock as the reference) with the reference checklist
and reports, per step, whether the hands actually do it and when. Smoke tests showed SAM 3.1 cannot see small
parts (RAM, coin battery) on 480p glasses footage, so object presence can't decide "was this done"; SAM is
used for evidence and visuals instead.

Reports are cached in results/reports/<video_id>.json, so re-scoring costs nothing.
"""

import json

from pr.client import RESULTS, MetaClient
from pr.license_check import ROOT
from pr.track import prepare

REPORTS = RESULTS / "reports"

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["steps", "notes"],
    "properties": {
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["index", "performed", "start_s", "end_s", "confidence", "evidence"],
                "properties": {
                    "index": {"type": "integer"},
                    "performed": {"type": "boolean"},
                    "start_s": {"type": "number"},
                    "end_s": {"type": "number"},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                    "evidence": {"type": "string"},
                },
            },
        },
        "notes": {"type": "string"},
    },
}

PROMPT = """You are checking a trainee's first-person video of the task: {task_name}.
A clock in the top-left corner shows elapsed time as MM:SS.s. The video is {duration:.1f} seconds long.

An expert's recording of the same task was split into this checklist:
{steps}

For EVERY checklist step, in checklist order, report:
- index: the checklist number
- performed: true only if you can see the trainee's hands actually do this step somewhere in the video.
  The trainee may do steps in a different order than the checklist; that still counts as performed.
- start_s, end_s: when the trainee does it, read from the on-screen clock; -1 and -1 if not performed
- confidence: how sure you are about "performed" (low / medium / high)
- evidence: one short sentence on what you saw, or what is absent
notes: anything else a trainer should know, in one or two sentences.
"""


def checklist_lines(checklist: dict) -> str:
    return "\n".join(f"{s['index']}. {s['title']} — {s['description']}" for s in checklist["steps"])


def align(video: str, checklist: dict, client: MetaClient | None, task_name: str) -> list[dict] | None:
    """Return one match per checklist step: {index, title, performed, start_s, end_s, confidence, evidence}.

    With client=None only a cached report is used (None if there is none).
    """
    cached = REPORTS / f"{video}.json"
    if cached.exists():
        return json.loads(cached.read_text())["steps"]
    if client is None:
        return None
    p = prepare(video, client)
    prompt = PROMPT.format(task_name=task_name, duration=p["info"]["duration"], steps=checklist_lines(checklist))
    print(f"  Muse Spark ({client.spark_model}) reviewing {p['video_id']} against {len(checklist['steps'])} steps…")
    report = client.spark_json(p["file_id"], prompt, SCHEMA, "trainee_report", p["video_id"], purpose="review")
    titles = {s["index"]: s["title"] for s in checklist["steps"]}
    for s in report["steps"]:
        s["title"] = titles.get(s["index"], "?")
    report.update({"video_id": p["video_id"], "task": checklist["task"], "duration": p["info"]["duration"],
                   "model": client.spark_model})
    REPORTS.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(report, indent=2))
    return report["steps"]


def keystep_of(checklist: dict) -> dict[int, str]:
    """Map each checklist step to the labelled keystep it overlaps most on the reference video.

    The checklist is Muse Spark's own split; ground truth and order rules use the dataset's keystep names.
    Steps that overlap no keystep are left out.
    """
    labels = json.loads((ROOT / "data" / "keysteps" / f"{checklist['reference_video']}.json").read_text())
    out = {}
    for s in checklist["steps"]:
        best = max(labels, key=lambda l: min(l["end"], s["end_s"]) - max(l["start"], s["start_s"]))
        if min(best["end"], s["end_s"]) - max(best["start"], s["start_s"]) > 0:
            out[s["index"]] = best["step"]
    return out
