"""Score detected flags against injected ground truth. This is the success metric, so it is not a stub.

A flawed video counts as detected when at least one flag
- has the right type (cut -> missing, swap -> out_of_order),
- names one of the injected steps, and
- for a swap, has a timestamp within `tol` seconds of the moved span.
A cut has no timestamp check: a step that never happens has no place in the video, and when the task allows
several orders (PC repair: the five parts go in any order) there is no single "where it should have been".
The missing flag's ts is when it should have been noticed (see pr.judge), which is what the Review shows.
An unedited video is a false flag if it has any flag other than "ok".
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
    """Return {kind: flawed|clean, ok: bool, status, n_flags, hit}."""
    raised = [f for f in flags if f.get("type") != "ok"]
    if flaw["type"] == "none":
        return {"kind": "clean", "ok": not raised, "status": "clean" if not raised else "FALSE FLAG",
                "n_flags": len(raised), "hit": None}
    hit = next((f for f in raised if flag_matches(f, flaw, tol)), None)
    return {"kind": "flawed", "ok": hit is not None, "status": "detected" if hit else "missed",
            "n_flags": len(raised), "hit": hit}


def summarize(scores: list[dict]) -> dict:
    flawed = [s for s in scores if s["kind"] == "flawed"]
    clean = [s for s in scores if s["kind"] == "clean"]
    return {"detected": sum(s["ok"] for s in flawed), "n_flawed": len(flawed),
            "false_flags": sum(not s["ok"] for s in clean), "n_clean": len(clean)}
