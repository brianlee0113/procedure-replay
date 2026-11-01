"""build_guide(video_id, config) -> a guide (contract v1, docs/B0_guide_eval_plan.md §2) from the video alone.

The same function builds app recordings and evaluation guides. Its inputs are fixed (§7): the 5 fps proxy with
the on-screen clock (muted unless config.audio), the video's duration, the transcript turns when
config.transcript (transcribed from the original audio, numbered #0, #1, ...), the category taxonomy, and the
instructor's Mark step times when the app sends them. Nothing derived from labels or the task config goes in
(no step count, task name, keysteps or object list), except the step names of the seeded ablation.

One Muse Spark call writes the whole guide. With config.refine, a second pass then looks at each step again in a
short window around it (one call per step) and tightens its start and end to the action, or splits a step that
holds several separate actions (B3 round 2: about a third of the missed label steps were boundary misses).
`postprocess` then makes it valid: steps sorted, clamped to the
video, overlaps cut at their midpoint, re-indexed, the loop clip padded by CLIP_PAD_S, the cover at the middle.
A quote whose words are not in its transcript turns is set to null before the app can show it, and the drop is
recorded in provenance; the untouched model answer is returned too, so evaluation scores the model, not the
filter.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass

from pr import guides
from pr.client import MetaClient
from pr.frames import PROXY_DIR, trim
from pr.track import prepare
from pr.transcribe import context_block, spoken, transcribe

PROMPT_VERSION = "b2-v1"
MIN_STEP_S = 0.5  # shorter steps left after cutting overlaps are dropped


@dataclass
class Config:
    transcript: bool = True       # give the model what was said (no effect on silent videos)
    on_screen_text: bool = True   # ask the model to read text visible in the video (no separate OCR)
    audio: bool = False           # keep the sound in the proxy (ablation 4; off was better in the review runs)
    seed_names: list[str] | None = None  # expert step names (ablation 2 only)
    model: str | None = None      # overrides MODEL_NAME
    category_defs: bool = False   # define each category in the prompt (B3 round 2)
    refine: bool = False          # second pass per step: tighten bounds, split mixed steps (B3 round 2)
    # Iterate set, B3 round 2: refine with split lost 0.08-0.14 step hit F1 (over-splits); bounds-only was
    # within noise of category_defs alone at ~3x the cost. Kept off; category_defs is the B4 config.
    refine_split: bool = True     # with refine, may the second pass split a step

    def label(self) -> str:
        """Short id for result folders, e.g. 'tr-ost-mute'."""
        parts = ["tr" if self.transcript else "notr", "ost" if self.on_screen_text else "noost",
                 "audio" if self.audio else "mute"]
        if self.seed_names:
            parts.append("seeded")
        if self.category_defs:
            parts.append("cat")
        if self.refine:
            parts.append("refine" if self.refine_split else "refine-nosplit")
        if self.model:
            parts.append(self.model)
        return "-".join(parts)


def schema(cfg: Config) -> dict:
    step = {
        "index": {"type": "integer"},
        "title": {"type": "string"},
        "instruction": {"type": "string"},
        "done_when": {"type": "string"},
        "start_s": {"type": "number"},
        "end_s": {"type": "number"},
        "key_objects": {"type": "array", "items": {"type": "string"}},
        "quote_text": {"type": "string"},
        "quote_turn_ids": {"type": "array", "items": {"type": "integer"}},
    }
    if cfg.on_screen_text:
        step["on_screen_text"] = {"type": "array", "items": {"type": "string"}}
    categories = list(guides.CATEGORIES)
    return {
        "type": "object", "additionalProperties": False,
        "required": ["title", "summary", "category", "category_alternatives", "tools", "steps"],
        "properties": {
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "category": {"type": "string", "enum": categories},
            "category_alternatives": {"type": "array", "items": {"type": "string", "enum": categories}},
            "tools": {"type": "array", "items": {"type": "string"}},
            "steps": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                 "required": list(step), "properties": step}},
        },
    }


PROMPT = """This video was filmed from the eyes of a person doing a hands-on job, as with smart glasses. Turn it
into a step-by-step guide that a first-timer can follow while watching one short looping clip per step.
A clock in the top-left corner shows elapsed time as MM:SS.s. The video is {duration:.1f} seconds long.
{steps_rule}
For the guide:
- title: names the job and the object, e.g. "Replace the toner cartridge in a laser printer"
- summary: 1-2 sentences: what the job is and the most important caution
- category: one of {categories}; category_alternatives: up to 2 others that also fit{category_defs}
- tools: tools used, if any

For each step:
- index: 1-based order
- title: short imperative phrase
- instruction: one or two imperative sentences a first-timer can follow
- done_when: the visible end state that shows the step is complete, stated by purpose rather than by the
  exact tool, e.g. "the cartridge is seated and its latch is closed"
- start_s, end_s: seconds, read from the on-screen clock; in time order and not overlapping
- key_objects: the objects the hands handle in the step
{quote_rule}{ost_rule}{context}{marks}"""

STEPS_UNSEEDED = """
Split the video into the steps of the job. A step is one distinct action that changes the state of what
is being worked on; decide how many steps the job needs from the video itself. Skip intros, talk with no
action, and idle time between steps; waiting that is part of the job (for example a pan heating) belongs
to its step.
"""

STEPS_FIXED = """
The guide's steps are fixed at these times (one step each, index = the number below; give exactly these
start_s and end_s). Write each step for what happens in it:
{segments}
"""

STEPS_SEEDED = """
The person who recorded it names its steps as follows. For EACH named step, in this order, find where it
happens and write it as one step (index = the number below):
{names}
"""

QUOTE_RULE = """- quote_text, quote_turn_ids: if the person says something during the step that a trainee should hear
  in their own words (a caution, a tip, why it is done this way), copy those words exactly from the
  transcript below and give the #numbers of the turns they come from (consecutive turns); otherwise ""
  and []. Never paraphrase.
"""

NO_QUOTE_RULE = """- quote_text, quote_turn_ids: always "" and []
"""

OST_RULE = """- on_screen_text: text visible in the video during the step that matters for it (labels, part numbers,
  captions); [] if none
"""

CATEGORY_DEFS = {
    "repair_maintenance": "fixing, servicing or replacing a part of a machine, device, vehicle or fixture "
                          "(a bike, a faucet, a washing machine), including opening a device to swap a part",
    "electronics": "building, soldering or wiring circuits and electronic components themselves",
    "workshop_tools": "setting up, adjusting or maintaining a hand or power tool itself (sharpening a chisel, setting up a saw)",
    "assembly": "putting a product together from its parts (furniture, kits)",
    "cooking": "preparing food or drinks",
    "cleaning_household": "cleaning, laundry, tidying and other chores",
    "crafts": "making things by hand: paper, sewing, knots, painting",
    "other": "anything else",
}

CATEGORY_RULE = """
  Categories, by what is done rather than what the object is made of:
{defs}"""

MARKS = """
While recording, the person tapped "Mark step" at these seconds: {marks}. Treat them as hints of where a
step starts or ends, not as exact boundaries.
"""


def prompt(cfg: Config, duration: float, context: str, marks: list[float],
           segments: list[tuple[float, float]] | None = None) -> str:
    if segments:  # "uniform + captions" baseline: the split is given, only the text is written
        seeded = STEPS_FIXED.format(segments="\n".join(f"{i}. {a:.1f}–{b:.1f} s" for i, (a, b) in enumerate(segments, 1)))
    elif cfg.seed_names:
        seeded = STEPS_SEEDED.format(names="\n".join(f"{i}. {n}" for i, n in enumerate(cfg.seed_names, 1)))
    else:
        seeded = STEPS_UNSEEDED
    defs = CATEGORY_RULE.format(defs="\n".join(f"  - {k}: {v}" for k, v in CATEGORY_DEFS.items())) \
        if cfg.category_defs else ""
    return PROMPT.format(
        duration=duration, steps_rule=seeded, categories=", ".join(guides.CATEGORIES), category_defs=defs,
        quote_rule=QUOTE_RULE if context else NO_QUOTE_RULE,
        ost_rule=OST_RULE if cfg.on_screen_text else "",
        context=context, marks=MARKS.format(marks=", ".join(f"{m:.1f}" for m in marks)) if marks else "")


REFINE_PROMPT = """This clip is a window of a first-person video of a hands-on job. The clock in its top-left corner
shows time in the original video (MM:SS.s); the window runs {w0:.1f}–{w1:.1f} s.

A guide written from the whole video has this step here:
  title: {title}
  instruction: {instruction}
  current bounds: {start:.1f}–{end:.1f} s
{neighbours}
Look at what the hands do in the window and give the step's exact bounds, read from the clock:
- start_s: the moment the hands begin this action (reaching for the object counts; looking around does not)
- end_s: the moment the action's result is reached and the hands move on
Keep the bounds inside the window, and do not take time that belongs to the steps before or after.
{split_rule}"""

SPLIT_RULE = """If, and only if, the step clearly holds two or more separate actions, each with its own visible
result, give one part per action in time order (at most 3); otherwise give exactly one part. Each part has a
short imperative title, a one- or two-sentence instruction, done_when (the visible end state), key_objects,
start_s and end_s."""

NO_SPLIT_RULE = """Give exactly one part: the same step with its corrected start_s and end_s (keep the title,
instruction, done_when and key_objects as they are)."""

REFINE_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["parts", "why"],
    "properties": {
        "parts": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                  "required": ["title", "instruction", "done_when", "key_objects", "start_s", "end_s"],
                  "properties": {"title": {"type": "string"}, "instruction": {"type": "string"},
                                 "done_when": {"type": "string"}, "start_s": {"type": "number"},
                                 "end_s": {"type": "number"},
                                 "key_objects": {"type": "array", "items": {"type": "string"}}}}},
        "why": {"type": "string"},
    },
}
REFINE_PAD_MIN_S, REFINE_PAD_MAX_S = 4.0, 10.0  # window = step +- half its length, clamped to these
REFINE_WORKERS = 3


def refine_window(start: float, end: float, duration: float) -> tuple[float, float]:
    pad = min(REFINE_PAD_MAX_S, max(REFINE_PAD_MIN_S, (end - start) / 2))
    return max(0.0, start - pad), min(duration, end + pad)


def refine_step(steps: list[dict], i: int, prepared: dict, duration: float, cfg: Config,
                client: MetaClient) -> dict:
    """One step looked at again in its window -> {"parts": [...], "why", "window"}; parts keep the step's
    quote and on-screen text on the first part (the quote check drops a quote that ends up outside its clip)."""
    s = steps[i]
    w0, w1 = refine_window(s["start_s"], s["end_s"], duration)
    vid = prepared["video_id"]
    clip = PROXY_DIR / "refine" / f"{vid}__{w0:.2f}-{w1:.2f}.mp4"
    if not clip.exists():
        trim(prepared["proxy"], w0, w1 - w0, clip)
    near = []
    if i > 0:
        near.append(f"  step before: {steps[i - 1]['title']} ({steps[i - 1]['start_s']:.1f}–{steps[i - 1]['end_s']:.1f} s)")
    if i + 1 < len(steps):
        near.append(f"  step after: {steps[i + 1]['title']} ({steps[i + 1]['start_s']:.1f}–{steps[i + 1]['end_s']:.1f} s)")
    text = REFINE_PROMPT.format(w0=w0, w1=w1, title=s["title"], instruction=s["instruction"], start=s["start_s"],
                                end=s["end_s"], neighbours="\n".join(near) + ("\n" if near else ""),
                                split_rule=SPLIT_RULE if cfg.refine_split else NO_SPLIT_RULE)
    answer = client.spark_json(client.upload(clip), text, REFINE_SCHEMA, "guide_step_refine", f"{vid}#step{i + 1}",
                               purpose="refine", model=cfg.model)
    parts = sorted(answer["parts"], key=lambda p: p["start_s"])[:3] if cfg.refine_split else answer["parts"][:1]
    out = []
    for k, p in enumerate(parts):
        a, b = max(w0, min(p["start_s"], w1)), max(w0, min(p["end_s"], w1))
        if b - a < MIN_STEP_S:
            continue
        base = s if not cfg.refine_split or len(parts) == 1 else {**s, **{f: p[f] for f in
                                                  ("title", "instruction", "done_when", "key_objects")}}
        extra = {} if k == 0 else {"quote_text": "", "quote_turn_ids": [], "on_screen_text": []}
        out.append({**base, **extra, "start_s": a, "end_s": b})
    if not out:  # nonsense bounds: keep the first pass
        out = [s]
    return {"parts": out, "why": answer["why"], "window": [w0, w1]}


def refine(raw: dict, prepared: dict, duration: float, cfg: Config, client: MetaClient) -> dict:
    """The first-pass answer with every step looked at again; the first pass is kept under "first_pass"."""
    steps = sorted(raw["steps"], key=lambda s: (s["start_s"], s["end_s"]))
    with ThreadPoolExecutor(REFINE_WORKERS) as pool:
        done = list(pool.map(lambda i: refine_step(steps, i, prepared, duration, cfg, client), range(len(steps))))
    new = [p for d in done for p in d["parts"]]
    for k, p in enumerate(new, 1):
        p["index"] = k
    return {**raw, "steps": new, "first_pass": raw["steps"],
            "refine": [{"index": s["index"], "window": d["window"], "parts": len(d["parts"]), "why": d["why"]}
                       for s, d in zip(steps, done)]}


def postprocess(raw: dict, *, guide_id: str, video_id: str, duration: float, cfg: Config,
                transcript: dict | None, provenance: dict,
                segments: list[tuple[float, float]] | None = None) -> guides.Guide:
    """Model answer -> a Guide that passes the contract validator; bad quotes become null (recorded).
    With fixed segments, step i keeps segment i's times whatever the model wrote."""
    answer = sorted(raw["steps"], key=lambda s: (s["start_s"], s["end_s"]))
    if segments:
        by_index = {s["index"]: s for s in raw["steps"]}
        answer = [{**by_index[i], "start_s": a, "end_s": b} for i, (a, b) in enumerate(segments, 1) if i in by_index]
    steps = []
    for s in answer:
        start, end = max(0.0, min(s["start_s"], duration)), max(0.0, min(s["end_s"], duration))
        if end - start >= MIN_STEP_S:
            steps.append({**s, "start_s": start, "end_s": end})
    for a, b in zip(steps, steps[1:]):
        if b["start_s"] < a["end_s"]:
            a["end_s"] = b["start_s"] = (b["start_s"] + a["end_s"]) / 2
    steps = [s for s in steps if s["end_s"] - s["start_s"] >= MIN_STEP_S]

    turns = (transcript or {}).get("turns", [])
    out, dropped = [], []
    for i, s in enumerate(steps, 1):
        step = guides.Step(
            index=i, title=s["title"], instruction=s["instruction"], done_when=s["done_when"],
            start_s=s["start_s"], end_s=s["end_s"], clip=guides.padded(s["start_s"], s["end_s"], duration),
            cover_s=(s["start_s"] + s["end_s"]) / 2, key_objects=s["key_objects"],
            on_screen_text=s.get("on_screen_text", []))
        ids = s["quote_turn_ids"]
        if s["quote_text"].strip() or ids:
            if not (turns and ids and all(0 <= t < len(turns) for t in ids)):
                dropped.append({"index": i, "reason": "no transcript turns to quote" if not turns else f"bad turn_ids {ids}"})
            else:
                text = spoken(s["quote_text"])
                _, start, end = guides.quote_times(text, turns[min(ids):max(ids) + 1])
                step.quote = guides.Quote(text=text, turn_ids=ids, start_s=start, end_s=end)
        out.append(step)

    guide = guides.Guide(
        guide_id=guide_id, source_video_id=video_id, duration_s=duration, title=raw["title"],
        summary=raw["summary"], category=raw["category"],
        category_alternatives=[c for c in raw["category_alternatives"] if c != raw["category"]][:2],
        tools=raw["tools"], steps=out,
        inputs_provided={"video": True, "transcript": bool(turns), "on_screen_text": cfg.on_screen_text,
                         "audio": cfg.audio, "step_names": bool(cfg.seed_names)},
        provenance=provenance)
    if transcript is not None:
        reasons: dict[int, list[str]] = {}
        for error in guides.quote_errors(guide, transcript):
            head, _, why = error.partition(": ")
            reasons.setdefault(int(head.removeprefix("step ")), []).append(why)
        for index, why in reasons.items():
            guide.steps[index - 1].quote = None
            dropped.append({"index": index, "reason": "; ".join(why)})
    guide.provenance["dropped_quotes"] = sorted(dropped, key=lambda d: d["index"])
    return guides.Guide.model_validate(guide.model_dump())


def build_guide(video_id: str, guide_id: str, cfg: Config | None = None, client: MetaClient | None = None,
                marks: list[float] | None = None, set_stage=lambda stage: None,
                segments=None, first_pass: dict | None = None) -> tuple[guides.Guide, dict]:
    """Build a guide for a licensed video. Returns (guide, raw model answer). set_stage reports progress to
    the app job: transcribe, read_text, split, write. `segments` fixes the split for the uniform + captions
    baseline: a list of (start, end), or a function of the proxy's duration returning one. `first_pass` is a stored
    first-pass answer to refine instead of asking again (evaluation: refine variants share one first pass)."""
    cfg, client = cfg or Config(), client or MetaClient()
    set_stage("transcribe")
    transcript = transcribe(video_id) if cfg.transcript else None
    if transcript is not None and not transcript["turns"]:
        transcript = None  # silent video: nothing to quote, nothing to show
    context = context_block(video_id) if transcript else ""
    p = prepare(video_id, client, audio=cfg.audio)
    duration = p["info"]["duration"]
    set_stage("read_text")  # on-screen text is read in the same call as the split
    set_stage("split")
    if callable(segments):
        segments = segments(duration)
    raw = first_pass or client.spark_json(p["file_id"], prompt(cfg, duration, context, marks or [], segments),
                                          schema(cfg), "guide", p["video_id"],
                                          purpose="baseline" if segments else "guide", model=cfg.model)
    if cfg.refine and not segments:
        raw = refine(raw, p, duration, cfg, client)
    set_stage("write")
    provenance = {"model": cfg.model or client.spark_model, "prompt_version": PROMPT_VERSION,
                  "config": asdict(cfg), "builder": "pr.build" if not segments else "pr.build:uniform+captions",
                  "created_at": guides.now()}
    if transcript:
        provenance.update(transcriber=transcript["model"],
                          transcript_id=f"results/transcripts/{transcript['video_id']}.json")
    guide = postprocess(raw, guide_id=guide_id, video_id=video_id, duration=duration, cfg=cfg,
                        transcript=transcript, provenance=provenance, segments=segments)
    return guide, raw
