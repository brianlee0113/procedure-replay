# ProcedureReplay

Watch one expert do a manual task once. Then check anyone else doing it.

ProcedureReplay turns a first-person video of an expert doing a manual procedure (repairing a PC,
changing a drill bit), recorded hands-free on smart glasses, into an ordered checklist with timestamps and reference frames.
Given a second video of a different person doing the same task, it tracks the same tools and parts,
aligns the video to the checklist, and flags **skipped** or **out-of-order** steps at the exact timestamp.

Built for the Meta Global AI Developer Hackathon (indie track, "Push the Frontier", manufacturing),
Oct 26 – Nov 4, 2026.

## Pipeline

```
reference video ─► license gate ─► 5 fps proxy ─┬─► Muse Spark 1.3  ─► ordered steps + timestamps (checklist)
                                                └─► SAM 3.1 (1 call per object prompt) ─► object presence timeline
trainee video   ─► license gate ─► 5 fps proxy ───► SAM 3.1 ─► presence timeline ─► align to checklist
                                                                                    ─► judge: ok / missing / out_of_order
evaluation: edited videos with a known injected flaw (cut or swap) ─► detected X/6, false flags Y/2
```

- **Muse Spark 1.3** (Meta Model API, Responses API + JSON-schema structured output) segments the
  reference video into steps.
- **SAM 3.1** (Meta Model API) tracks text-prompted tools and parts across every frame.
- Videos are re-encoded to a 5 fps 720p proxy with a burned-in clock, so frame index ↔ seconds is exact
  for both models and SAM's per-frame cost stays low.

Success criterion: detect the injected flaw in ≥5 of 6 edited videos, with 0 false flags on 2 unedited videos.

## Setup

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/), and ffmpeg (`brew install ffmpeg`).

```bash
uv sync
cp .env.example .env          # then put your Meta Model API key in META_API_KEY
uv run python -m pr.license_check
```

## Data

Two first-person scenarios, so the same pipeline covers a factory floor and a home kitchen:

| Scenario | Dataset | Camera | License | Tasks (`config/tasks.yaml`) |
| --- | --- | --- | --- | --- |
| Factory | [IndEgo](https://huggingface.co/datasets/FraunhoferIPK/IndEgo) (Fraunhofer IPK, NeurIPS 2025) | Project Aria glasses | CC BY 4.0 | `pc_repair` (Task 22, 9 steps), `drill_bit` (Task 7, 5 steps) |
| Home | [CaptainCook4D](https://captaincook4d.github.io/captain-cook/) (UT Dallas, NeurIPS 2024) | head-mounted GoPro | Apache-2.0 | `home_cooking` (herb omelet with fried tomatoes, 15 steps) |

Both come with human step labels and real mistake takes. IndEgo takes are correct (`_c_`) or mistake (`_m_`);
CaptainCook4D takes are normal or error. Recipes are partial orders (you can chop the cilantro before or after
taking the tomato), so `import_captaincook.py` also writes the recipe graph to `data/task_graphs/`, and
`inject.py swap` refuses to swap two steps the recipe allows in either order.

Videos never go in git. Download only the 480p videos and annotations (~0.9 GB; the full dataset is ~19 TB):

```bash
uvx --from huggingface_hub hf download FraunhoferIPK/IndEgo --repo-type dataset --local-dir data/raw/indego \
  --include "Mistake_Detection/Task_22/mp4_480/*" \
  --include "Mistake_Detection/Task_22/annotations/keystep_annotations/*" \
  --include "Mistake_Detection/Task_7/mp4_480/*" \
  --include "Mistake_Detection/Task_7/annotations/keystep_annotations/*" \
  --include "Mistake_Detection/renamed_annotation_mistakes/A_Task_22.txt" \
  --include "Mistake_Detection/renamed_annotation_mistakes/A_Task_07.txt"
uv run python scripts/import_indego.py --drop-examples   # manifest, ATTRIBUTION, data/keysteps/, real-mistake labels
```

CaptainCook4D: clone the two small repos (labels + download links), print the curl lines for the 17 omelet
recordings (GoPro 360p, ~80 MB each), run them, then import:

```bash
git clone --depth 1 https://github.com/CaptainCook4D/annotations data/raw/captaincook4d/annotations
git clone --depth 1 https://github.com/CaptainCook4D/downloader  data/raw/captaincook4d/downloader
uv run python scripts/import_captaincook.py --print-downloads > /tmp/cc4d_download.sh   # review, then: sh /tmp/cc4d_download.sh
uv run python scripts/import_captaincook.py   # manifest, ATTRIBUTION, data/keysteps/, data/task_graphs/, real-error labels
```

Every video is listed in `data/manifest.csv` (video_id, task, creator, source_url, license, role, local_path) and
`ATTRIBUTION.md`. Every script refuses a video whose manifest row lacks an allowed license (CC0, CC-BY, CC-BY-SA,
Pexels, Pixabay, Apache-2.0; never ND or NC). Why that list: [docs/HACKATHON_RULES.md](docs/HACKATHON_RULES.md).

`data/ground_truth.jsonl` has one row per trainee video. `injected_flaw.type` is `none`, `cut`, or `swap`;
`steps` are 1-based step numbers from `step_list`; `start_ts`/`end_ts` are seconds in the **edited** video
(for a cut, both equal the splice point; for a swap, the span where the moved block now sits).

## Run

```bash
# smoke tests (each prints PASS/FAIL with evidence)
uv run python scripts/smoke_sam.py data/raw/<video>.mp4 --task pc_repair
uv run python scripts/smoke_steps.py data/raw/<reference>.mp4 --task pc_repair
uv run python scripts/smoke_cross_creator.py data/raw/<a>.mp4 data/raw/<b>.mp4 --task pc_repair

# inject a known flaw into a trainee video (ranges come from IndEgo's keystep labels)
uv run python -m pr.inject cut  --video 22_u14_r03_c_01 --step "add ram"
uv run python -m pr.inject swap --video 22_u15_r03_c_01 --step-a "add battery" --step-b "attach fan"
uv run python -m pr.inject none --video 22_u16_r03_c_01

# full evaluation (--dry-run: cached results only, no API calls)
uv run python scripts/run_eval.py
uv run python tests/test_score.py
```

Every API call is logged with tokens/frames and estimated cost to `results/costs.csv`.

## Built during the hackathon

All code in this repository was written Oct 26 – Nov 4, 2026, starting from an empty repo.

| Component | What it does | Status |
| --- | --- | --- |
| `src/pr/license_check.py` | Manifest access + license gate (CC0/CC-BY/CC-BY-SA/Pexels/Pixabay/Apache-2.0 only) | day 1 |
| `src/pr/client.py` | Meta Model API wrapper: file upload, SAM 3.1 streaming, Muse Spark structured output, retries, cost log | day 1 |
| `src/pr/frames.py` | ffprobe, 5 fps proxy with burned-in clock, trimming, frame grabs | day 1 |
| `src/pr/track.py` | SAM output → per-object presence timeline | day 1 |
| `src/pr/steps.py` | Muse Spark → checklist JSON with timestamps and reference frames | day 1 |
| `src/pr/inject.py` | ffmpeg cut / swap flaw injection by keystep name, ground truth + attribution logging; refuses swaps a recipe allows | day 1 |
| `scripts/import_indego.py` | Registers downloaded IndEgo videos: manifest, attribution, keystep labels, real-mistake labels | day 1 |
| `scripts/import_captaincook.py` | Prints CaptainCook4D download commands; registers videos, step labels, recipe graph, real-error labels | day 1 |
| `src/pr/align.py`, `src/pr/judge.py` | Align trainee timeline to checklist; flag missing / out-of-order | stub |
| `scripts/smoke_*.py` | API smoke tests | day 1 |
| `src/pr/score.py`, `tests/test_score.py` | Scoring rule (detected / false flag) + checks | day 1 |
| `scripts/run_eval.py` | Runs the pipeline over the manifest and scores it against ground truth | day 1 (stages stubbed) |
| `scripts/render_demo.py` | Annotated demo video + results table | TODO |

## Third-party

**Libraries**

| Library | License | Use |
| --- | --- | --- |
| [openai](https://github.com/openai/openai-python) | Apache-2.0 | OpenAI-compatible client for Meta Model API |
| [meta-sam-parser](https://pypi.org/project/meta-sam-parser/) | SAM License (Meta) | Parse SAM 3.1 segmentation output |
| [opencv-python-headless](https://github.com/opencv/opencv-python) | Apache-2.0 / MIT | Frame reading and drawing |
| [numpy](https://numpy.org) | BSD-3-Clause | Arrays |
| [PyYAML](https://pyyaml.org) | MIT | Config |
| [python-dotenv](https://github.com/theskumar/python-dotenv) | BSD-3-Clause | `.env` loading |
| [FFmpeg](https://ffmpeg.org) (CLI, not bundled) | LGPL/GPL | Proxy encoding, cuts, swaps |
| [uv](https://github.com/astral-sh/uv) | Apache-2.0 / MIT | Environment management |

**Models** (via [Meta Model API](https://dev.meta.ai/docs)): Muse Spark 1.3 (`muse-spark-1.3-contributor`), SAM 3.1 (`sam-3.1`).

**Videos**: [IndEgo](https://huggingface.co/datasets/FraunhoferIPK/IndEgo), Fraunhofer IPK (Chavan et al., NeurIPS 2025),
CC BY 4.0, recorded on Project Aria glasses. Keystep and mistake labels are IndEgo's.
[CaptainCook4D](https://captaincook4d.github.io/captain-cook/), Peddi et al. (NeurIPS 2024 Datasets & Benchmarks),
Apache-2.0 videos; step, error and task-graph labels from [CaptainCook4D/annotations](https://github.com/CaptainCook4D/annotations) (MIT).
Per-video list and our edits: [ATTRIBUTION.md](ATTRIBUTION.md).

## License

Our code is MIT ([LICENSE](LICENSE)). Videos keep their original licenses (see ATTRIBUTION.md).
