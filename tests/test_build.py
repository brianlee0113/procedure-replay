"""B2 builder pieces that need no API call: prompt inputs and postprocess. Run: uv run python tests/test_build.py"""

import copy

from pr.build import Config, postprocess, prompt, schema

TRANSCRIPT = {"video_id": "v", "model": "muse-voice-transcribe-1.0", "turns": [
    {"start_s": 2.0, "end_s": 5.0, "text": "First unplug the drill, always."},
    {"start_s": 9.0, "end_s": 12.0, "text": "Loosen the chuck counterclockwise."},
]}


def step(i, a, b, quote="", ids=()):
    return {"index": i, "title": f"t{i}", "instruction": "i", "done_when": "d", "start_s": a, "end_s": b,
            "key_objects": ["drill"], "quote_text": quote, "quote_turn_ids": list(ids), "on_screen_text": []}


RAW = {"title": "Change a drill bit", "summary": "s", "category": "workshop_tools",
       "category_alternatives": ["workshop_tools", "repair_maintenance", "assembly", "other"], "tools": [],
       "steps": [step(2, 8.0, 14.0, "Loosen the chuck counterclockwise", [1]),
                 step(1, 0.5, 9.0, "First unplug the drill", [0]),
                 step(3, 14.0, 14.3),                                   # too short: dropped
                 step(4, 15.0, 30.0, "tighten it with the key", [1]),   # words not in turn 1
                 step(5, 25.0, 40.0, "x", [7])]}                       # turn does not exist; ends past video


def build(raw, transcript=TRANSCRIPT, cfg=Config()):
    return postprocess(raw, guide_id="g", video_id="v", duration=35.0, cfg=cfg, transcript=transcript,
                       provenance={"transcript_id": "results/transcripts/v.json"})


raw = copy.deepcopy(RAW)
g = build(raw)
assert raw == RAW  # the model answer is kept as it came
assert [s.index for s in g.steps] == [1, 2, 3, 4]
assert [(s.start_s, s.end_s) for s in g.steps] == [(0.5, 8.5), (8.5, 14.0), (15.0, 27.5), (27.5, 35.0)]
assert g.steps[0].clip.start_s == 0.0 and g.steps[3].clip.end_s == 35.0
assert g.steps[1].quote.turn_ids == [1] and (g.steps[1].quote.start_s, g.steps[1].quote.end_s) == (9.0, 12.0)
assert g.steps[0].quote.text == "First unplug the drill"
assert g.steps[2].quote is None and g.steps[3].quote is None
assert [d["index"] for d in g.provenance["dropped_quotes"]] == [3, 4], g.provenance["dropped_quotes"]
assert g.category_alternatives == ["repair_maintenance", "assembly"]
assert g.inputs_provided["transcript"] and not g.inputs_provided["step_names"]

# Without a transcript every quote is dropped and recorded.
g = build(RAW, transcript=None)
assert all(s.quote is None for s in g.steps) and len(g.provenance["dropped_quotes"]) == 4
assert not g.inputs_provided["transcript"]

# Prompt inputs: no step count, no task name; quotes asked for only with a transcript; seeded lists names.
p = prompt(Config(), 35.0, "", [])
assert "about" not in p and "steps)" not in p and 'always "" and []' in p and "on_screen_text" in p
p = prompt(Config(on_screen_text=False, seed_names=["unplug", "remove bit"]), 35.0, "\n#0 [00:02-00:05] hi\n", [3.0])
assert "1. unplug\n2. remove bit" in p and "copy those words exactly" in p and "3.0" in p and "on_screen_text" not in p
assert "on_screen_text" not in schema(Config(on_screen_text=False))["properties"]["steps"]["items"]["properties"]
assert Config().label() == "tr-ost-mute" and Config(audio=True, seed_names=["a"]).label() == "tr-ost-audio-seeded"

# Fixed segments (uniform + captions baseline): times come from the segments, not the model.
g = postprocess({**RAW, "steps": [step(1, 3.0, 4.0), step(2, 0.0, 1.0)]}, guide_id="g", video_id="v", duration=35.0,
                cfg=Config(), transcript=None, provenance={}, segments=[(0.0, 17.5), (17.5, 35.0)])
assert [(s.start_s, s.end_s, s.title) for s in g.steps] == [(0.0, 17.5, "t1"), (17.5, 35.0, "t2")]
assert "give exactly these" in prompt(Config(), 35.0, "", [], [(0.0, 17.5), (17.5, 35.0)])

print("ok")
