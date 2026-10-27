"""align(trainee_video, checklist) -> which checklist step happens where in the trainee video.

Muse Spark watches the trainee's proxy (same on-screen clock as the reference) with the reference checklist
and reports, per step, whether the hands actually do it and when. Smoke tests showed SAM 3.1 cannot see small
parts (RAM, coin battery) on 480p glasses footage, so object presence can't decide "was this done"; SAM is
used for evidence and visuals instead.

Reports are cached in results/reports/run<N>/<video_id>.json, keyed by the prompts, checklist, model and
video content, so re-scoring costs nothing and any change re-runs. Separate runs (`run`) are independent calls,
used to measure run-to-run variance and to vote.
"""

import hashlib
import json
from collections import Counter
from statistics import median

from pr.client import RESULTS, MetaClient, sha256_file, spark_model_name
from pr.license_check import ROOT, local_path, require_allowed
from pr.track import prepare

REPORTS = RESULTS / "reports"
FIELDS = ("performed", "start_s", "end_s", "confidence", "evidence")

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
- performed: true only if you can see the trainee's hands carry out this step's main action on the right
  object somewhere in the video. Picking a part up or reaching toward it is not enough. "Done when" says what
  the step is for; the camera may not show every detail of it, so do not require every detail.
  Judge by purpose: the same result reached with a different tool or method counts as performed
  (e.g. a nut loosened with pliers instead of a wrench). A different order also still counts.
  Each moment of the video belongs to at most one step: do not credit two steps with the same action.
- start_s, end_s: when the trainee does it, read from the on-screen clock; -1 and -1 if not performed
- confidence: how sure you are about "performed" (low / medium / high)
- evidence: one short sentence on what you saw, or what is absent
notes: anything else a trainer should know, in one or two sentences.
"""

# A step the full review calls "not performed" is checked again on its own: with the whole checklist in view,
# Muse Spark overlooks short actions on small parts (dev set: 3 false "missing" flags on one correct take).
# Re-checking unsure "performed" answers too was tried on the dev set and made it worse (a false flag on a
# correct take, one cut missed), so it is not done.
RECHECK_PROMPT = """You are checking a trainee's first-person video of the task: {task_name}.
A clock in the top-left corner shows elapsed time as MM:SS.s. The video is {duration:.1f} seconds long.

Watch the whole video carefully for ONE step only:
{step}

Short actions on small parts are easy to miss, so look at every moment the hands work on the object.
Judge by purpose: the same result reached with a different tool or method counts. Picking a part up or
reaching toward it without carrying out the action does not count.
Report this step with index {index}: performed, start_s/end_s from the on-screen clock (-1 if not performed),
confidence, and evidence (one short sentence). notes: empty.
"""


def checklist_lines(checklist: dict) -> str:
    return "\n".join(f"{s['index']}. {s['title']} — {s['description']}"
                     + (f" Done when: {s['done_when']}" if s.get("done_when") else "") for s in checklist["steps"])


def align(video: str, checklist: dict, client: MetaClient | None, task_name: str, run: int = 1) -> list[dict] | None:
    """Return one match per checklist step: {index, title, performed, start_s, end_s, confidence, evidence}.

    With client=None only a cached report is used (None if there is none). A step the re-check overturned keeps
    its first answer in "first" (see first_pass).
    """
    cached = REPORTS / f"run{run}" / f"{video}.json"
    model = client.spark_model if client else spark_model_name()
    video_hash = sha256_file(local_path(require_allowed(video)))
    key = hashlib.sha1((PROMPT + RECHECK_PROMPT + checklist_lines(checklist) + model + video_hash)
                       .encode()).hexdigest()[:12]
    if cached.exists() and json.loads(cached.read_text()).get("key") == key:
        return json.loads(cached.read_text())["steps"]
    if client is None:
        return None
    p = prepare(video, client)
    duration = p["info"]["duration"]
    prompt = PROMPT.format(task_name=task_name, duration=duration, steps=checklist_lines(checklist))
    print(f"  Muse Spark ({model}) reviewing {p['video_id']} against {len(checklist['steps'])} steps (run {run})…")
    report = client.spark_json(p["file_id"], prompt, SCHEMA, "trainee_report", p["video_id"], purpose="review")
    lines = dict(zip((s["index"] for s in checklist["steps"]), checklist_lines(checklist).splitlines()))

    def ask_one(index: int) -> dict | None:
        prompt = RECHECK_PROMPT.format(task_name=task_name, duration=duration, step=lines[index], index=index)
        again = client.spark_json(p["file_id"], prompt, SCHEMA, "trainee_report", p["video_id"], purpose="recheck")
        return next((x for x in again["steps"] if x["index"] == index), None)

    # The schema can't force one answer per step: drop unknown and repeated indices, ask for any step left out.
    steps, seen = [], set()
    for s in report["steps"]:
        if s["index"] in lines and s["index"] not in seen:
            steps.append(s)
            seen.add(s["index"])
    for index in lines:
        if index not in seen and (found := ask_one(index)):
            steps.append({**found, "asked_alone": True})
    steps.sort(key=lambda s: s["index"])

    for s in steps:
        if s["performed"] or s["confidence"] == "low" or s.get("asked_alone"):
            continue
        found = s["recheck"] = ask_one(s["index"])
        if found and found["performed"]:
            s["first"] = {k: s[k] for k in FIELDS}
            s.update({k: found[k] for k in FIELDS})
    titles = {s["index"]: s["title"] for s in checklist["steps"]}
    for s in steps:
        s["title"] = titles.get(s["index"], "?")
    report.update({"steps": steps, "video_id": p["video_id"], "task": checklist["task"], "duration": duration,
                   "model": model, "video_sha256": video_hash, "run": run, "key": key})
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(report, indent=2))
    return steps


def unanswered(matches: list[dict], checklist: dict) -> list[int]:
    """Checklist steps the report has no answer for. Such a report can't be judged: a skipped step would vanish."""
    have = {m["index"] for m in matches}
    return [s["index"] for s in checklist["steps"] if s["index"] not in have]


def first_pass(matches: list[dict]) -> list[dict]:
    """The matches as the full review gave them, before the re-check overturned any "not performed"."""
    return [{**m, **m["first"]} if "first" in m else m for m in matches]


def vote(runs: list[list[dict]]) -> list[dict]:
    """Per-step majority over independent runs. Times are the median over the runs that agree.

    Confidence is the most common one among the agreeing runs; a tie goes to the less sure one, so a
    split vote on "not performed" doesn't raise a missing flag.
    """
    order = ["low", "medium", "high"]
    out = []
    for index in sorted({m["index"] for ms in runs for m in ms}):
        answers = [m for ms in runs for m in ms if m["index"] == index]
        performed = sum(m["performed"] for m in answers) * 2 > len(answers)
        agree = [m for m in answers if m["performed"] == performed]
        counts = Counter(m["confidence"] for m in agree)
        top = max(counts.values())
        out.append({"index": index, "title": agree[0].get("title", "?"), "performed": performed,
                    "start_s": median(m["start_s"] for m in agree) if performed else -1,
                    "end_s": median(m["end_s"] for m in agree) if performed else -1,
                    "confidence": min((c for c in counts if counts[c] == top), key=order.index),
                    "evidence": f"{len(agree)}/{len(answers)} runs: {agree[0]['evidence']}"})
    return out


def keystep_of(checklist: dict) -> dict[int, str]:
    """Map each checklist step to the labelled keystep it overlaps most on the reference video.

    A checklist built from the expert's step names carries them ("keystep"). Otherwise the checklist is
    Muse Spark's own split, and each step is matched by time overlap; steps that overlap no keystep are left out.
    """
    if all("keystep" in s for s in checklist["steps"]):
        return {s["index"]: s["keystep"] for s in checklist["steps"]}
    labels = json.loads((ROOT / "data" / "keysteps" / f"{checklist['reference_video']}.json").read_text())
    out = {}
    for s in checklist["steps"]:
        best = max(labels, key=lambda l: min(l["end"], s["end_s"]) - max(l["start"], s["start_s"]))
        if min(best["end"], s["end_s"]) - max(best["start"], s["start_s"]) > 0:
            out[s["index"]] = best["step"]
    return out
