"""Register downloaded IndEgo videos: manifest rows, ATTRIBUTION entries, keystep labels, real-mistake labels.

IndEgo (Fraunhofer IPK, NeurIPS 2025) is CC BY 4.0 and was recorded on Project Aria glasses.
Download only what we use (the full dataset is ~19 TB) — see README "Data". Then:

    uv run python scripts/import_indego.py                   # every task in config/tasks.yaml found on disk
    uv run python scripts/import_indego.py --drop-examples   # also remove the example_ template rows

Idempotent: videos already in the manifest are skipped.
Writes data/keysteps/<video_id>.json ([{step, start, end}], seconds) and data/indego_mistakes.jsonl
(IndEgo's own labels for its mistake takes, e.g. "didn't add ram").
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

import yaml

from pr.license_check import ROOT, append_manifest_row, load_manifest

HF = "https://huggingface.co/datasets/FraunhoferIPK/IndEgo/blob/main/Mistake_Detection"
LICENSE = "CC-BY-4.0"
CREDIT = "IndEgo, Fraunhofer IPK (Chavan et al., NeurIPS 2025)"
NAME = re.compile(r"^(?P<task>\d+)_(?P<user>u\d+)_r\d+_(?P<cond>[cm])_\d+$")
KEYSTEPS = ROOT / "data" / "keysteps"
MISTAKES = ROOT / "data" / "indego_mistakes.jsonl"
ATTRIBUTION = ROOT / "ATTRIBUTION.md"

DATASET_ENTRY = f"""### IndEgo dataset
- Title: IndEgo — industrial egocentric dataset, Mistake_Detection subset
- Creator: {CREDIT}
- Source: https://huggingface.co/datasets/FraunhoferIPK/IndEgo
- License: CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/)
- Camera: Project Aria glasses (first-person). We use the 480p MP4s and the keystep annotations.
"""


def keysteps_from_via(path: Path) -> list[dict]:
    """IndEgo keystep files are VGG Image Annotator projects; temporal segments live in `metadata`."""
    d = json.loads(path.read_text())
    options = next(iter(d["attribute"].values()))["options"]
    segs = [{"step": options[next(iter(m["av"].values()))], "start": round(m["z"][0], 2), "end": round(m["z"][1], 2)}
            for m in d["metadata"].values() if len(m.get("z", [])) == 2 and m.get("av")]
    return sorted(segs, key=lambda s: s["start"])


def mistake_labels(path: Path) -> dict[str, str]:
    """A_Task_NN.txt lines look like `22_u14_r03_m_03: [0,0,1,0,0,0,0,0,0] didn't add ram`."""
    out = {}
    for line in path.read_text().splitlines():
        m = re.match(r"^(\S+):\s*\[[^\]]*\]\s*(.*)$", line.strip())
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


def drop_examples() -> None:
    man = ROOT / "data" / "manifest.csv"
    lines = man.read_text().splitlines()
    man.write_text("\n".join(l for l in lines if not l.startswith("example_")) + "\n")
    gt = ROOT / "data" / "ground_truth.jsonl"
    rows = [l for l in gt.read_text().splitlines() if l.strip() and not json.loads(l)["video_id"].startswith("example_")]
    gt.write_text("".join(r + "\n" for r in rows))


def add_attribution(entries: list[str]) -> None:
    text = ATTRIBUTION.read_text().replace("_None yet. Add an entry per video when placing it in `data/raw/`._\n", "")
    if "### IndEgo dataset" not in text:
        text = text.rstrip("\n") + "\n\n" + DATASET_ENTRY
    ATTRIBUTION.write_text(text.rstrip("\n") + "\n" + "".join(entries))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="data/raw/indego", help="--local-dir used for the download")
    ap.add_argument("--drop-examples", action="store_true")
    args = ap.parse_args()

    root = ROOT / args.root / "Mistake_Detection"
    if not root.exists():
        print(f"not found: {root} — download first (README, Data)")
        return 1
    if args.drop_examples:
        drop_examples()

    tasks = yaml.safe_load((ROOT / "config" / "tasks.yaml").read_text())
    known = {r["video_id"] for r in load_manifest()}
    mistakes_seen = {json.loads(l)["video_id"] for l in MISTAKES.read_text().splitlines()} if MISTAKES.exists() else set()
    KEYSTEPS.mkdir(parents=True, exist_ok=True)
    entries, new_mistakes = [], []

    for key, cfg in tasks.items():
        if "indego_task" not in cfg:
            continue
        n = cfg["indego_task"]
        task_dir = root / f"Task_{n}"
        videos = sorted((task_dir / "mp4_480").glob("*.mp4")) or sorted((task_dir / "mp4").glob("*.mp4"))
        if not videos:
            continue
        labels_file = root / "renamed_annotation_mistakes" / f"A_Task_{n:02d}.txt"
        labels = mistake_labels(labels_file) if labels_file.exists() else {}
        counts, added = Counter(), 0
        for v in videos:
            vid = v.stem.removesuffix("_480")
            m = NAME.match(vid)
            if not m:
                print(f"  skip unrecognised file name: {v.name}")
                continue
            counts[(m["user"], m["cond"])] += 1
            ks = task_dir / "annotations" / "keystep_annotations" / f"{vid}_keystep.json"
            if ks.exists():
                (KEYSTEPS / f"{vid}.json").write_text(json.dumps(keysteps_from_via(ks), indent=1))
            if m["cond"] == "m" and vid in labels and vid not in mistakes_seen:
                new_mistakes.append({"video_id": vid, "task": key, "indego_label": labels[vid]})
            if vid in known:
                continue
            url = f"{HF}/Task_{n}/{v.parent.name}/{v.name}"
            append_manifest_row({"video_id": vid, "task": key, "creator": f"{CREDIT}, participant {m['user']}",
                                 "source_url": url, "license": LICENSE,
                                 "role": "reference" if vid == cfg["reference"] else "trainee",
                                 "local_path": str(v.relative_to(ROOT))})
            entries.append(f"\n### {vid}\n- IndEgo Task {n} ({cfg['name']}), participant {m['user']}, "
                           f"{'correct' if m['cond'] == 'c' else 'mistake'} take · {LICENSE} · {url}\n- Edits:\n")
            added += 1
        users = sorted({u for u, _ in counts})
        summary = ", ".join(f"{u} {counts[(u, 'c')]}c/{counts[(u, 'm')]}m" for u in users)
        ref_ok = "found" if any(v.stem.removesuffix("_480") == cfg["reference"] for v in videos) else "MISSING"
        print(f"{key} (Task {n}): {len(videos)} videos, {added} new · reference {cfg['reference']} {ref_ok}\n  {summary}")

    if entries:
        add_attribution(entries)
    if new_mistakes:
        with open(MISTAKES, "a") as f:
            f.writelines(json.dumps(r) + "\n" for r in new_mistakes)
    print(f"\nmanifest +{len(entries)} rows, keysteps in {KEYSTEPS.relative_to(ROOT)}/, "
          f"{len(new_mistakes)} real-mistake labels -> {MISTAKES.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
