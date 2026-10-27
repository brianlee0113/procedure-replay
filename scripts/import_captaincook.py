"""Register downloaded CaptainCook4D recordings: manifest rows, ATTRIBUTION entries, step labels, recipe graph, real errors.

CaptainCook4D (Peddi et al., NeurIPS 2024 Datasets & Benchmarks) is Apache-2.0: people cooking recipes in real
kitchens, filmed with a head-mounted GoPro, with step labels and deliberate-error takes. Tasks are picked up from
config/tasks.yaml entries that have `captaincook_activity`. Steps in tasks.yaml are written in the same short form
`step_name()` produces.

    git clone --depth 1 https://github.com/CaptainCook4D/annotations data/raw/captaincook4d/annotations
    git clone --depth 1 https://github.com/CaptainCook4D/downloader  data/raw/captaincook4d/downloader
    uv run python scripts/import_captaincook.py --print-downloads > /tmp/cc4d.sh   # curl lines; you run them
    uv run python scripts/import_captaincook.py

Idempotent: videos already in the manifest are skipped.
Writes data/keysteps/<video_id>.json ([{step, start, end}], seconds), data/task_graphs/<task>.json
({steps, before: [[a, b], ...]} = every pair the recipe forces into an order) and data/captaincook_mistakes.jsonl.
"""

import argparse
import csv
import json
import sys
from pathlib import Path

import yaml

from pr.license_check import ROOT, append_manifest_row, load_manifest

LICENSE = "Apache-2.0"
CREDIT = "CaptainCook4D, Peddi et al. (NeurIPS 2024 Datasets & Benchmarks), UT Dallas"
PREFIX = "cc4d_"
KEYSTEPS = ROOT / "data" / "keysteps"
GRAPHS = ROOT / "data" / "task_graphs"
MISTAKES = ROOT / "data" / "captaincook_mistakes.jsonl"
ATTRIBUTION = ROOT / "ATTRIBUTION.md"

DATASET_ENTRY = f"""### CaptainCook4D dataset
- Title: CaptainCook4D — a dataset for understanding errors in procedural activities (GoPro 360p videos, step and error annotations)
- Creator: {CREDIT}
- Source: https://captaincook4d.github.io/captain-cook/ · videos via https://github.com/CaptainCook4D/downloader · annotations https://github.com/CaptainCook4D/annotations (MIT)
- License: Apache License 2.0 (https://www.apache.org/licenses/LICENSE-2.0). Edited copies are marked under each video below.
- Camera: head-mounted GoPro (first-person), real kitchens.
"""


def step_name(description: str) -> str:
    """'Chop-Chop 2 tbsp cilantro' -> 'chop 2 tbsp cilantro'; 'add-1/2 tsp pepper' -> 'add 1/2 tsp pepper'."""
    verb, _, rest = description.partition("-")
    verb, rest = verb.strip(), rest.strip()
    name = rest if rest.lower().startswith(verb.lower()) else f"{verb} {rest}".strip()
    return name[:1].lower() + name[1:]


def video_id(recording_id: str) -> str:
    return f"{PREFIX}{recording_id}"


def recipe_order(graph: dict) -> tuple[list[str], list[list[str]]]:
    """Step names and every (a before b) pair implied by the task graph's edges (transitive closure)."""
    names = {int(k): step_name(v) for k, v in graph["steps"].items() if v not in ("START", "END")}
    succ: dict[int, set[int]] = {}
    for a, b in graph["edges"]:
        succ.setdefault(a, set()).add(b)

    def reach(a: int, seen: set[int]) -> set[int]:
        for b in succ.get(a, ()):
            if b not in seen:
                seen.add(b)
                reach(b, seen)
        return seen

    before = sorted([names[a], names[b]] for a in names for b in reach(a, set()) if b in names)
    return sorted(names.values()), before


def load(ann: Path, activity: str):
    activities = {r["activity_name"]: int(r["activity_idx"])
                  for r in csv.DictReader(open(ann / "annotation_csv" / "activity_step_description.csv"))}
    if activity not in activities:
        raise SystemExit(f"unknown captaincook_activity {activity!r}; known: {sorted(activities)}")
    aid = activities[activity]
    recs = [r for r in json.loads((ann / "annotation_json" / "error_annotations.json").read_text())
            if r["activity_id"] == aid]
    info = {r["recording_id"]: r for r in csv.DictReader(open(ann / "metadata" / "video_information.csv"))}
    graph = json.loads((ann / "task_graphs" / f"{''.join(c for c in activity.lower() if c.isalpha())}.json").read_text())
    return recs, info, graph


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="data/raw/captaincook4d", help="holds annotations/, downloader/, videos/")
    ap.add_argument("--print-downloads", action="store_true",
                    help="print curl commands for the GoPro 360p videos of every configured recipe, then exit")
    args = ap.parse_args()

    root = ROOT / args.root
    ann, videos = root / "annotations", root / "videos"
    links_file = root / "downloader" / "metadata" / "download_links.json"
    for p in (ann, links_file):
        if not p.exists():
            print(f"not found: {p.relative_to(ROOT)} — clone the two repos first (README, Data)")
            return 1
    links = json.loads(links_file.read_text())
    tasks = {k: v for k, v in yaml.safe_load((ROOT / "config" / "tasks.yaml").read_text()).items()
             if v.get("captaincook_activity")}

    if args.print_downloads:
        print(f"mkdir -p {videos.relative_to(ROOT)}")
        for key, cfg in tasks.items():
            recs, _, _ = load(ann, cfg["captaincook_activity"])
            print(f"# {key}: {cfg['captaincook_activity']} — {len(recs)} recordings")
            for r in recs:
                url = links.get(r["recording_id"], {}).get("gopro_360p")
                out = videos / f"{r['recording_id']}_360p.mp4"
                print(f"curl -L -C - -o {out.relative_to(ROOT)} '{url}'" if url else f"# {r['recording_id']}: no GoPro 360p")
        return 0

    known = {r["video_id"] for r in load_manifest()}
    mistakes_seen = {json.loads(l)["video_id"] for l in MISTAKES.read_text().splitlines()} if MISTAKES.exists() else set()
    KEYSTEPS.mkdir(parents=True, exist_ok=True)
    GRAPHS.mkdir(parents=True, exist_ok=True)
    entries, new_mistakes = [], []

    for key, cfg in tasks.items():
        recs, info, graph = load(ann, cfg["captaincook_activity"])
        steps, before = recipe_order(graph)
        missing = [s for s in cfg.get("keysteps", []) if s not in steps]
        if missing:
            print(f"  warning: tasks.yaml keysteps not in the recipe graph: {missing}")
        (GRAPHS / f"{key}.json").write_text(json.dumps({"steps": steps, "before": before}, indent=1))
        added, n_ok, n_err, ref_ok = 0, 0, 0, "MISSING"
        for r in recs:
            rid, vid = r["recording_id"], video_id(r["recording_id"])
            v = videos / f"{rid}_360p.mp4"
            if not v.exists():
                continue
            ref_ok = "found" if vid == cfg["reference"] else ref_ok
            n_err += r["is_error"]
            n_ok += not r["is_error"]
            segs = sorted(({"step": step_name(s["description"]), "start": round(s["start_time"], 2),
                            "end": round(s["end_time"], 2)} for s in r["step_annotations"] if s["start_time"] >= 0),
                          key=lambda s: s["start"])
            (KEYSTEPS / f"{vid}.json").write_text(json.dumps(segs, indent=1))
            if r["is_error"] and vid not in mistakes_seen:
                errors = [{"step": step_name(s["description"]), "tag": e["tag"], "description": e.get("description", "")}
                          for s in r["step_annotations"] for e in s.get("errors", [])]
                new_mistakes.append({"video_id": vid, "task": key, "errors": errors})
            if vid in known:
                continue
            person = info.get(rid, {}).get("person_id", "?")
            url = links[rid]["gopro_360p"]
            append_manifest_row({"video_id": vid, "task": key, "creator": f"{CREDIT}, person {person}",
                                 "source_url": url, "license": LICENSE,
                                 "role": "reference" if vid == cfg["reference"] else "trainee",
                                 "local_path": str(v.relative_to(ROOT))})
            entries.append(f"\n### {vid}\n- CaptainCook4D recording {rid} ({cfg['captaincook_activity']}), person {person}, "
                           f"{'error' if r['is_error'] else 'normal'} take · {LICENSE} · {url}\n- Edits:\n")
            added += 1
        print(f"{key} ({cfg['captaincook_activity']}): {n_ok + n_err} videos on disk of {len(recs)} "
              f"({n_ok} normal / {n_err} error), {added} new · reference {cfg['reference']} {ref_ok}")

    if entries:
        text = ATTRIBUTION.read_text().replace("_None yet. Add an entry per video when placing it in `data/raw/`._\n", "")
        if "### CaptainCook4D dataset" not in text:
            text = text.rstrip("\n") + "\n\n" + DATASET_ENTRY
        ATTRIBUTION.write_text(text.rstrip("\n") + "\n" + "".join(entries))
    if new_mistakes:
        with open(MISTAKES, "a") as f:
            f.writelines(json.dumps(r) + "\n" for r in new_mistakes)
    print(f"\nmanifest +{len(entries)} rows, keysteps in {KEYSTEPS.relative_to(ROOT)}/, recipe graphs in "
          f"{GRAPHS.relative_to(ROOT)}/, {len(new_mistakes)} real-error labels -> {MISTAKES.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
