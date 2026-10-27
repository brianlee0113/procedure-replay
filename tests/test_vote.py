"""Vote / first-pass / completeness checks on hand-built matches (no API calls). Run: uv run python tests/test_vote.py"""

from pr.align import first_pass, unanswered, vote


def m(index, performed, confidence="high", start=10.0, **extra):
    return {"index": index, "performed": performed, "start_s": start if performed else -1,
            "end_s": start + 5 if performed else -1, "confidence": confidence, "evidence": "seen", **extra}


runs = [[m(1, True, start=10), m(2, False, "medium")],
        [m(1, True, start=14), m(2, True, "low", start=50)],
        [m(1, False, "high"), m(2, False, "low")]]
v = {x["index"]: x for x in vote(runs)}
assert v[1]["performed"] and v[1]["start_s"] == 12 and v[1]["confidence"] == "high", v[1]   # median of agreeing runs
assert not v[2]["performed"] and v[2]["confidence"] == "low", v[2]                           # medium/low tie -> low

overturned = m(3, True, "medium", start=30, first={"performed": False, "start_s": -1, "end_s": -1,
                                                    "confidence": "medium", "evidence": "not seen"})
assert first_pass([overturned])[0]["performed"] is False
assert first_pass([m(1, True)])[0]["performed"] is True

checklist = {"steps": [{"index": 1}, {"index": 2}, {"index": 3}]}
assert unanswered([m(1, True), m(3, False)], checklist) == [2]
print("5 vote cases pass")
