# B0 — Guide contract v1 and evaluation plan (draft for review)

Status: draft, 2026-10-27. Nothing here is implemented yet. Written to be reviewed (Codex review #1)
before any code or API call.

## 1. What changed and what B0 must decide

The product is now: an instructor wears Meta glasses and does a job while explaining it out loud;
Meta's multimodal model turns the recording into a step-by-step guide (steps, one looping clip per
step, instructions, title, summary, category); trainees watch it on an iPhone; public guides appear in a
feed. The previous pipeline is different in two ways that matter for evaluation:

1. It was given the expert's step names (`keysteps` in `config/tasks.yaml`) and only had to locate
   them. The new flow must **find the steps itself** from video plus narration. When we tried the
   unseeded split earlier on the dev set, it did not line up with the expert's steps (two PC steps
   swapped names, several recipe steps merged) — see the docstring in `src/pr/steps.py`.
2. The old metric was "did the trainee review catch the injected flaw". The new output is a guide, so
   we need metrics for **segmentation, instruction quality, guide metadata and narration use**.

The AI track's goal is **coverage**: show that one model and one app handle professional tasks
(factory work) through everyday ones (home cooking), with numbers per domain.

B0 decides: (a) the guide JSON contract the app will consume, (b) the metrics, (c) the data and splits,
(d) the iteration protocol and the stopping rule. Implementation starts after review.

## 2. Guide JSON contract v1

One file per guide, produced by the AI track, consumed unchanged by the app (track A). Server-side
fields (author, visibility, likes, saves) are **not** part of this contract.

```json
{
  "contract_version": 1,
  "guide_id": "string",
  "source_video_id": "string (manifest.csv video_id)",
  "duration_s": 491.7,
  "language": "en",
  "title": "Repair a desktop PC: battery, RAM, cables",
  "summary": "1–2 sentences: what the job is and the most important caution.",
  "category": "repair_maintenance",
  "category_alternatives": ["electronics"],
  "tools": ["screwdriver", "cloth"],
  "steps": [
    {
      "index": 1,
      "title": "Open the computer case",
      "instruction": "One or two imperative sentences a trainee can follow.",
      "done_when": "Observable end state, stated by purpose.",
      "start_s": 6.2,
      "end_s": 31.5,
      "clip": {"start_s": 5.2, "end_s": 32.5},
      "cover_s": 18.0,
      "key_objects": ["computer case"],
      "quote": {"text": "verbatim instructor sentence or null", "start_s": 12.4} ,
      "on_screen_text": ["DDR4 8GB"]
    }
  ],
  "inputs_used": {"video": true, "transcript": true, "on_screen_text": true},
  "provenance": {"model": "muse-spark-1.3-contributor", "transcriber": "muse-voice-transcribe-1.0",
                 "prompt_version": "string", "created_at": "ISO-8601", "est_usd": 0.0}
}
```

Rules: steps are in time order and do not overlap; `clip` may pad the step by ≤1 s each side and is
what the app loops; `quote` is either null or a sentence that exists in the transcript (never
paraphrased); `category` comes from a fixed taxonomy (section 4.3).

## 3. Data and splits

### 3.1 What we have (human step labels with start/end seconds, `data/keysteps/`)

| Domain | Source | Labelled takes | Participants | Narration |
|---|---|---|---|---|
| Factory: PC repair (9 steps, ~2–8 min) | IndEgo Task 22, CC BY 4.0 | 15 correct + 31 with mistakes | 5 (correct takes) | none |
| Factory: drill bit (5 steps, ~1 min) | IndEgo Task 7, CC BY 4.0 | 22 correct + 21 with mistakes | 6 | none |
| Home cooking: herb omelet (15 steps, ~12–30 min) | CaptainCook4D, Apache-2.0 | 17 (6 normal, 11 with mistakes) | — | none |

No video in these sets contains speech (checked 2026-10-27 with Muse Voice Transcribe, ~57 min).

### 3.2 What we need to add (B1, in progress)

- **Narrated videos, English only, existing footage, first-person only** (no self-recording).
  Selection rule (2026-10-27): the camera is at the worker's eyes or chest with their hands doing the
  task, as with smart glasses; the person doing the task explains it out loud in English; one task or
  recipe; CC0 / CC BY / CC BY-SA / Pexels / Pixabay / Apache-2.0 / MIT (no NC, no ND). Third-person
  cooking shows were dropped. These videos have no human step labels, so we label them ourselves
  (section 3.4).

  Chosen and downloaded (license re-checked with yt-dlp metadata; first-person checked on frames):

  | video_id | Domain | Video | Length |
  |---|---|---|---|
  | `yt_P-pHllvP0wo` | Cooking (restaurant) | POV Restaurant Cooking: Make this order with me #6, Abraham Moreno | 10:36 |
  | `yt_LPwPomA7BfM` | Repair (plumbing) | Dripping Faucet Repair, The Old Corona (burned-in captions) | 1:20 |

  Candidates under the same rule (CC BY label and English captions found; viewpoint inferred from 3
  frames; not watched yet):

  | Domain | Video | Length | Note |
  |---|---|---|---|
  | Cooking | POV Restaurant Cooking: The SCORCHER Burrito, Abraham Moreno — https://www.youtube.com/watch?v=jFQnSWX7tqs | 11:18 | step-by-step recipe |
  | Cooking | POV Restaurant Cooking: Cucumber water, Abraham Moreno — https://www.youtube.com/watch?v=2mOy0TZFpBg | 17:39 | a drink; cut to < 15 min |
  | Cooking (home) | EASY FRIED RICE, POV COOKING, Ghanzi — https://www.youtube.com/watch?v=U-nqknHm9hY | 5:14 | home stove, vertical video |
  | Cooking (home) | How to make AguaChile, POV Cooking, Abraham Moreno — https://www.youtube.com/watch?v=JxvMxtewo3Q | 20:33 | long, needs a cut |
  | Maintenance | GY6 50cc Full Oil Service, scooter POV, Oddspite rides — https://www.youtube.com/watch?v=YOnnEBwWII4 | 19:18 | chapters; e.g. 01:42–08:26 only |
  | Plumbing | Inline PVC Pipe Repair, Ultra Plumbing & Drain Cleaning — https://www.youtube.com/watch?v=e4F572BB7W8 | 5:43 | burned-in captions |
  | Electrical | POV Service Electrical: Range Install, Aesir Electric — https://www.youtube.com/watch?v=rYylNdLF3QA | 9:41 | weaker: less hands-on framing |
  | Workshop | Sprocket Welding, Google Glass POV Test, Attoparsec — https://www.youtube.com/watch?v=Ff0Y2yo_8gQ | 16:51 | **filmed on Google Glass** |

  No narrated first-person factory or assembly-line video under CC BY was found; the factory domain
  stays on IndEgo (first-person, no speech). CC BY requires credit and a "changes were made" note
  (`ATTRIBUTION.md`, demo credits).
- **Optional: one assembly dataset.** IndustReal is Apache-2.0 but has no speech (segmentation only).
  HoloAssist is CDLA-Permissive-2.0 (commercial use and changes allowed) with instructor speech, but
  CDLA is not yet on our license list — a decision for the user.

### 3.3 Splits

- Split by **participant**, not by take, so the same person's style never appears in both dev and test.
  - PC repair: dev = u14, u15; test = u01, u16, u17 (reference take u17_r03_c_01 stays in test only as
    an input, never used for prompt tuning).
  - Drill bit: dev = u14, u15, u16; test = u01, u02, u17.
  - Omelet: no participant IDs in our labels; split by take, normal takes 3 dev / 3 test, takes with
    mistakes used only for segmentation metrics (dev).
  - Narrated set: too small to split; treated as **test-only showcase**, with one extra narrated video
    held for dev if we find enough.
- Test is run **once**, at B4, with the frozen configuration. Everything in B2–B3 uses dev only.

### 3.4 Labelling the narrated videos

For each narrated video: one person (the user) marks step start/end seconds and a short step name,
watching at 1×, before any model output is seen. Claude may prepare a blank template (video duration,
transcript with timestamps) but does not propose boundaries, to avoid anchoring the labels on the model.

## 4. Metrics

### 4.1 Segmentation (all labelled videos)

Align predicted steps to human steps with an **order-preserving** alignment (dynamic programming over
temporal IoU), because a guide's steps are ordered.

- **Step recall / precision / F1** at temporal IoU ≥ 0.3 (one-to-one).
- **Coverage recall (merge-tolerant):** a human step counts as covered if one predicted step covers
  ≥ 50% of it. Reported next to strict recall because label granularity differs (the omelet has 15
  fine steps; a good guide may merge "add cilantro" and "add pepper").
- **Granularity ratio:** predicted step count / human step count.
- **Boundary error:** median |Δstart| and |Δend| in seconds over matched steps, plus the same divided by
  the human step length.
- **Clip usefulness:** share of human steps whose matched clip covers ≥ 70% of the human interval and is
  ≤ 2× its length (a clip a trainee can loop without hunting).

### 4.2 Instruction quality (matched steps)

Rubric, each item 0/1, per step:
1. Action matches what the hands do (judged against the human step label and the clip).
2. Key objects are correct; no object or tool that is not in the clip.
3. `done_when` is observable in the clip and correct.
4. Instruction is actionable for a first-timer (imperative, specific, ≤ 2 sentences).

Scoring: an LLM judge scores all steps from the human label, the guide step and 3 frames from the clip;
the user hand-scores a random 20% sample and we report judge–human agreement. **Open question for
review:** which judge model (Muse Spark judging its own output risks self-preference; a different model
costs more and adds a dependency).

### 4.3 Guide metadata

- **Category exact match** against a fixed taxonomy v1: `repair_maintenance`, `electronics`,
  `workshop_tools`, `assembly`, `cooking`, `cleaning_household`, `crafts`, `other`. Ground truth set by
  us per task. Top-2 match reported too.
- **Title** (0/1): names the actual task and object.
- **Summary** (0/1): faithful, no step or claim that is not in the video.

### 4.4 Narration use (narrated videos only)

- **Quote fidelity:** every non-null `quote` must match a transcript sentence (normalized edit similarity
  ≥ 0.9) and its time must fall inside the step's clip. Target: 100% — a fabricated quote is a hard
  failure because the app shows it as the instructor's words.
- **Narration lift (ablation):** the same metrics with and without the transcript in the prompt. The
  demo claim "the model uses what the instructor says" needs this to be positive.

### 4.5 Reliability and cost

- Each dev configuration runs **3 times**; report mean and min–max (run-to-run variance was large in the
  review experiments).
- Cost and latency per guide from `results/costs.csv` (a steps call has cost about $0.007 so far).

## 5. Targets (proposed, to be challenged in review)

| Metric | Target on test |
|---|---|
| Coverage recall | ≥ 0.80 per domain |
| Strict step F1 (IoU ≥ 0.3) | ≥ 0.60 |
| Median boundary error | ≤ 5 s, or ≤ 15% of step length |
| Instruction rubric (all 4 items) | ≥ 85% of steps |
| Category top-1 | ≥ 90% of guides |
| Quote fidelity | 100% |
| Narration lift | coverage recall and rubric both higher with transcript |

## 6. Ablations planned (B2–B3)

1. Video only vs video + transcript (narrated set).
2. Unseeded vs seeded with expert step names (labelled sets) — tells us how much of the earlier score
   came from the names.
3. On-screen text extraction on vs off.
4. Audio in the video on vs off (earlier review experiments: off was better with Muse Spark 1.3).

## 7. Iteration protocol (B2–B4)

One round = change one thing → run dev 3× → metrics table (`results/summary_guides_dev.md`) →
Codex review → decide. Rounds planned: baseline (B2), 2–3 iterations (B3), freeze and test (B4).
Stopping rule: freeze on 2026-11-01 regardless of targets; report test numbers as they are.

## 8. Questions for the reviewer

1. Is order-preserving IoU alignment plus merge-tolerant coverage a fair way to compare against labels
   with different granularity, or should we evaluate against merged label groups instead?
2. Participant-level split: with 5–6 participants per factory task, is a 2–3 / 3 split enough, or
   should we use leave-one-participant-out on dev?
3. Judge model choice for the instruction rubric (section 4.2) and whether 20% human spot-check is
   enough to trust it.
4. Is labelling the narrated videos ourselves (section 3.4) acceptable, and how do we keep the labels
   independent of the model?
5. Are the targets in section 5 meaningful, or should they be relative (e.g., beat a fixed-interval
   baseline that cuts the video into N equal parts)?
6. Anything in the contract (section 2) that would make the app or the evaluation harder later.
