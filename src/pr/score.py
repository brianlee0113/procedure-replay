"""Score detected flags against injected ground truth. This is the success metric, so it is not a stub.

A flawed video counts as detected when at least one flag
- has the right type (cut -> missing, swap -> out_of_order),
- names one of the injected steps, and
- for a swap, has a timestamp within `tol` seconds of the moved span.
A cut has no timestamp check: a step that never happens has no place in the video, and when the task allows
several orders (PC repair: the five parts go in any order) there is no single "where it should have been".
The missing flag's ts is when it should have been noticed (see pr.judge), which is what the Review shows.
An unedited video is a false flag if it has any flag other than "ok".
Detection alone doesn't penalise wrong flags raised next to the right one, so every flag on a flawed video
that matches nothing injected is counted as "extra".
"""

EXPECTED_TYPE = {"cut": "missing", "swap": "out_of_order"}


def flag_matches(flag: dict, flaw: dict, tol: float) -> bool:
    if flag.get("type") != EXPECTED_TYPE[flaw["type"]] or flag.get("step") not in flaw["steps"]:
        return False
    if flaw["type"] == "cut":
        return True
    ts = flag.get("ts")
    return ts is not None and flaw["start_ts"] - tol <= ts <= flaw["end_ts"] + tol


def score_video(flaw: dict, flags: list[dict], tol: float = 5.0) -> dict:
    """Return {kind: flawed|clean, ok: bool, status, n_flags, extra, hit}."""
    raised = [f for f in flags if f.get("type") != "ok"]
    if flaw["type"] == "none":
        return {"kind": "clean", "ok": not raised, "status": "clean" if not raised else "FALSE FLAG",
                "n_flags": len(raised), "extra": len(raised), "hit": None}
    hits = [f for f in raised if flag_matches(f, flaw, tol)]
    return {"kind": "flawed", "ok": bool(hits), "status": "detected" if hits else "missed",
            "n_flags": len(raised), "extra": len(raised) - len(hits), "hit": hits[0] if hits else None}


def incomplete(flaw: dict) -> dict:
    """Score for a video whose report left steps unanswered: it counts as a failure either way."""
    kind = "clean" if flaw["type"] == "none" else "flawed"
    return {"kind": kind, "ok": False, "status": "INCOMPLETE", "n_flags": 0, "extra": 0, "hit": None}


def summarize(scores: list[dict]) -> dict:
    flawed = [s for s in scores if s["kind"] == "flawed"]
    clean = [s for s in scores if s["kind"] == "clean"]
    return {"detected": sum(s["ok"] for s in flawed), "n_flawed": len(flawed),
            "false_flags": sum(not s["ok"] for s in clean), "n_clean": len(clean),
            "extra_on_flawed": sum(s["extra"] for s in flawed)}
