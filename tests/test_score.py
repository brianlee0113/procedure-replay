"""Scoring checks with hand-built flags (no API calls). Run: uv run python tests/test_score.py"""

from pr.score import score_video, summarize

CUT = {"type": "cut", "steps": [4], "start_ts": 42.0, "end_ts": 42.0}
SWAP = {"type": "swap", "steps": [2, 4], "start_ts": 20.0, "end_ts": 70.0}
NONE = {"type": "none", "steps": [], "start_ts": None, "end_ts": None}

cases = [
    (CUT, [{"type": "missing", "step": 4, "ts": 44.0}], True),          # within tolerance
    (CUT, [{"type": "missing", "step": 4, "ts": 60.0}], False),         # wrong time
    (CUT, [{"type": "missing", "step": 3, "ts": 42.0}], False),         # wrong step
    (CUT, [{"type": "out_of_order", "step": 4, "ts": 42.0}], False),    # wrong type
    (CUT, [], False),
    (SWAP, [{"type": "out_of_order", "step": 2, "ts": 50.0}], True),
    (SWAP, [{"type": "ok", "step": 2, "ts": 50.0}], False),
    (NONE, [{"type": "ok", "step": 1, "ts": 3.0}], True),
    (NONE, [{"type": "missing", "step": 1, "ts": 3.0}], False),
]
scores = []
for flaw, flags, expected in cases:
    s = score_video(flaw, flags, tol=5.0)
    assert s["ok"] is expected, (flaw, flags, s)
    scores.append(s)
assert summarize(scores) == {"detected": 2, "n_flawed": 7, "false_flags": 1, "n_clean": 2}, summarize(scores)
print(f"{len(cases)} scoring cases pass")
