"""Seed the local app server with demo guides built from the committed checklists (stand-in for B2 output).

    uv run python scripts/seed_guides.py          # writes results/app/guides/*, reactions.json, progress.json

Authors are sample personas for the demo (as in the Figma screens), not real people. The viewer in the demo is
"luis": his own drill guide is private; he saved the other two and stopped at step 4 of the PC repair.
Re-running replaces these three guides and their reactions; app recordings and other guides are kept.
"""

import json
import shutil

from pr import guides
from pr.guides import Meta, from_checklist, now, write_json
from pr.server import PROGRESS, REACTIONS

SEED = [
    ("seed_pc_repair", "pc_repair", "repair_maintenance", ["screwdriver", "cloth"],
     Meta(author="dana", author_name="Dana Ruiz", author_role="IT technician", visibility="public")),
    ("seed_home_cooking", "home_cooking", "cooking", ["knife", "cutting board", "non-stick pan", "wooden spoon"],
     Meta(author="min", author_name="Min Park", author_role="Home cook", visibility="public")),
    ("seed_drill_bit", "drill_bit", "workshop_tools", [],
     Meta(author="luis", author_name="Luis Ortega", author_role="Workshop lead", visibility="private")),
]


def main() -> None:
    reactions = json.loads(REACTIONS.read_text()) if REACTIONS.exists() else {}
    progress = json.loads(PROGRESS.read_text()) if PROGRESS.exists() else {}
    for gid, task, category, tools, meta in SEED:
        shutil.rmtree(guides.GUIDES / gid, ignore_errors=True)
        meta.published_at = now()
        guides.save(from_checklist(task, gid, category, tools), meta)
        reactions[gid] = {"likes": [], "saves": []}
    for gid in ("seed_pc_repair", "seed_home_cooking"):
        reactions[gid] = {"likes": ["luis"], "saves": ["luis"]}
    progress.setdefault("luis", {})["seed_pc_repair"] = 4
    write_json(REACTIONS, reactions)
    write_json(PROGRESS, progress)
    print(f"seeded {len(SEED)} guides in {guides.GUIDES}")


if __name__ == "__main__":
    main()
