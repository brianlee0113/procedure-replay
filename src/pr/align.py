"""align(trainee_timeline, checklist, ref_timeline) -> which checklist step happens where in the trainee video.

STUB (day 1). Plan: describe each reference step by which SAM prompts are present (and how large) during
its span, compute the same per-window signature on the trainee timeline, then find the best monotone
assignment of steps to trainee windows, allowing a step to be unmatched (missing) or matched out of order.
"""


def align(trainee_timeline: dict, checklist: dict, ref_timeline: dict) -> list[dict]:
    """Return one match per checklist step: {step, start_s, end_s, score}; start_s is None if unmatched."""
    return []
