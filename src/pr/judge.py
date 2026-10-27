"""judge(matches, ...) -> flags.

A flag is {"type": "ok" | "missing" | "out_of_order", "step": <1-based keystep number>, "name", "ts": <seconds in
the trainee video>, "detail", "checklist_steps": [...]}. run_eval scores any flag that is not "ok".

Checklist steps (Muse Spark's split of the reference) are first folded into keysteps via `keystep_of`; several
checklist steps can share one keystep ("add oil" + "heat the pan" -> "heat 1 tbsp oil ...").

- missing: no checklist step of the keystep was performed, and Muse Spark was at least moderately sure.
  ts = when it should have been noticed: the first performed step that must come after it, else the end of
  the last performed step.
- out_of_order: keystep times break a "must come before" rule (pr.order). The fewest steps that explain all
  broken rules are flagged (greedy: drop the step in most broken rules first). Steps closer than MARGIN
  seconds never count as out of order.
"""

MARGIN = 2.0


def judge(matches: list[dict], keystep_of: dict[int, str], keysteps: list[str],
          before: set[tuple[str, str]]) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for m in matches:
        k = keystep_of.get(m["index"])
        if k in keysteps:
            groups.setdefault(k, []).append(m)

    start, end, missing = {}, {}, []
    for k, ms in groups.items():
        done = [m for m in ms if m["performed"] and m["start_s"] >= 0]
        if done:
            start[k] = min(m["start_s"] for m in done)
            end[k] = max(m["end_s"] for m in done)
        elif any(m["confidence"] != "low" for m in ms):
            missing.append(k)

    def flag(type_, k, ts, detail):
        return {"type": type_, "step": keysteps.index(k) + 1, "name": k, "ts": ts, "detail": detail,
                "checklist_steps": [m["index"] for m in groups[k]]}

    flags = []
    for k in missing:
        after = [start[b] for a, b in before if a == k and b in start]
        ts = min(after) if after else max(end.values(), default=0.0)
        why = "; ".join(m["evidence"] for m in groups[k])
        flags.append(flag("missing", k, ts, f"not seen in the video. {why}"))

    broken = [(a, b) for a, b in before if a in start and b in start and start[b] + MARGIN < start[a]]
    while broken:
        count: dict[str, int] = {}
        for a, b in broken:
            count[a] = count.get(a, 0) + 1
            count[b] = count.get(b, 0) + 1
        worst = max(count, key=lambda k: (count[k], start[k]))
        rules = [f"should come before {b!r}" if a == worst else f"should come after {a!r}"
                 for a, b in broken if worst in (a, b)]
        flags.append(flag("out_of_order", worst, start[worst], "; ".join(rules)))
        broken = [(a, b) for a, b in broken if worst not in (a, b)]

    flagged = {f["name"] for f in flags}
    flags += [flag("ok", k, start[k], "done") for k in sorted(start, key=start.get) if k not in flagged]
    return flags
