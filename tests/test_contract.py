"""Guide contract v1 checks (docs/B0_guide_eval_plan.md §2): the Guide validator and the transcript quote check.
No files or API calls. Run: uv run python tests/test_contract.py"""

from pydantic import ValidationError

from pr.guides import Guide, quote_errors, quote_times

TRANSCRIPT = {"turns": [
    {"start_s": 2.0, "end_s": 5.0, "text": "Okay, first unplug the drill."},
    {"start_s": 6.0, "end_s": 9.5, "text": "Now loosen the chuck, turn it counterclockwise,"},
    {"start_s": 9.5, "end_s": 12.0, "text": "and pull the old bit out."},
]}


def step(index, start, end, **over):
    s = {"index": index, "title": "t", "instruction": "i", "done_when": "d", "start_s": start, "end_s": end,
         "clip": {"start_s": max(0.0, start - 1), "end_s": end + 1}, "cover_s": (start + end) / 2}
    return {**s, **over}


def guide(steps, **over):
    g = {"guide_id": "g", "source_video_id": "v", "duration_s": 20.0, "title": "t", "summary": "s",
         "category": "workshop_tools", "steps": steps, "inputs_provided": {"video": True, "transcript": True},
         "provenance": {}}
    return {**g, **over}


def refused(data, why):
    try:
        Guide.model_validate(data)
    except ValidationError as e:
        assert why in str(e), (why, str(e))
        return
    raise AssertionError(f"accepted, expected: {why}")


ok = Guide.model_validate(guide([step(1, 1.0, 5.0), step(2, 5.0, 12.0)]))
assert ok.inputs_provided["transcript"]

refused(guide([step(1, 1.0, 5.0)], inputs_used={"video": True}), "inputs_used")  # v0 field, not mapped
refused(guide([step(2, 1.0, 5.0)]), "indexes")
refused(guide([step(1, 1.0, 6.0), step(2, 5.0, 12.0)]), "overlap")
refused(guide([step(1, 1.0, 5.0, clip={"start_s": 2.0, "end_s": 6.0})]), "clip start <= start")
refused(guide([step(1, 15.0, 19.5)]), "<= duration")  # clip end 20.5 > 20
refused(guide([step(1, 4.0, 8.0, clip={"start_s": 1.0, "end_s": 9.0})]), "pads the step")
refused(guide([step(1, 1.0, 5.0, cover_s=6.0)]), "cover_s")
refused(guide([step(1, 1.0, 5.0, quote={"text": "x", "turn_ids": [], "start_s": 2.0, "end_s": 5.0})]), "turn_ids")

# Quotes against the transcript.
q = lambda text, ids, a, b: {"text": text, "turn_ids": ids, "start_s": a, "end_s": b}
good = Guide.model_validate(guide([
    step(1, 1.0, 5.0, quote=q("first unplug the drill", [0], 2.0, 5.0)),
    step(2, 5.0, 12.0, quote=q("Now loosen the chuck, turn it counterclockwise, and pull the old bit out", [1, 2], 6.0, 12.0)),
]))
assert quote_errors(good, TRANSCRIPT) == [], quote_errors(good, TRANSCRIPT)
assert quote_errors(ok, None) == []  # no quotes, no transcript needed


def errors(quote, start=5.0, end=12.0):
    return quote_errors(Guide.model_validate(guide([step(1, start, end, quote=quote)])), TRANSCRIPT)


assert "not in turns" in errors(q("tighten the chuck firmly with the key", [1], 6.0, 9.5))[0]
assert "not consecutive" in errors(q("pull the old bit out", [0, 2], 2.0, 12.0))[0]
assert "not consecutive" in errors(q("pull the old bit out", [3], 12.0, 14.0))[0]
assert "where its words are" in errors(q("pull the old bit out", [2], 9.0, 12.0))[0]
assert "outside the clip" in errors(q("first unplug the drill", [0], 2.0, 5.0), start=10.0, end=14.0)[0]

# A quote's times are where its words are in a long turn (no word times: the turn's time spread by length).
LONG = {"turns": [{"start_s": 0.0, "end_s": 20.0,
                   "text": "Lift the car first. <|speaker_A|> Then open the hood and take the oil cap off."}]}
sim, a, b = quote_times("open the hood and take the oil cap off", LONG["turns"])
assert sim == 1.0 and 7.0 < a < 8.0 and b == 20.0, (sim, a, b)  # 24 of 63 characters in
inside = Guide.model_validate(guide([step(1, 8.5, 19.0, quote=q("open the hood and take the oil cap off", [0], a, b))]))
assert quote_errors(inside, LONG) == [], quote_errors(inside, LONG)  # the turn starts 7.5 s before the clip
early = Guide.model_validate(guide([step(1, 8.5, 19.0, quote=q("Lift the car first", [0], *quote_times("Lift the car first", LONG["turns"])[1:]))]))
assert "outside the clip" in quote_errors(early, LONG)[0]
assert "no readable transcript_id" in quote_errors(good)[0]

print("ok")
