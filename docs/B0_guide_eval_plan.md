# B0 — Guide contract v1 and evaluation plan (draft v4)

Status: draft v4, 2026-10-28, after Codex review #3. Nothing here is implemented yet. Changes are listed
in sections 9 (v3 → v4), 10 (v2 → v3) and 11 (v1 → v2). Order of work: fix splits, label groups and
the primary metric (sections 3–4) → check and secure narrated dev/test videos (3.2) → make the
contract code changes (2) → run the B2 baseline.

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

One `guide.json` per guide, produced by the AI track, validated by the `Guide` model
(`src/pr/guides.py`) and served by the server. The guide holds **times, not media files**: the server
cuts each step's loop clip and cover from the licensed source video on request and adds `clip_url` and
`cover_url` to every step (`GET /guides/{id}`, `src/pr/server.py`). This is what lets an instructor's
Draft edit of a step's start/end re-cut its clip without re-running the model. The app (track A) reads
the server's response, never the source video. Server-side fields (author, visibility, likes, saves) are
**not** part of this contract.

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
      "quote": {"text": "verbatim instructor words", "turn_ids": [4], "start_s": 12.4, "end_s": 15.9},
      "on_screen_text": ["DDR4 8GB"]
    }
  ],
  "inputs_provided": {"video": true, "transcript": true, "on_screen_text": true},
  "provenance": {"model": "muse-spark-1.3-contributor", "transcriber": "muse-voice-transcribe-1.0",
                 "transcript_id": "results/transcripts/<video_id>.json",
                 "prompt_version": "string", "created_at": "ISO-8601", "est_usd": 0.0}
}
```

Rules:
- Steps are in time order and **do not overlap** (the app loops one clip at a time). Real work can
  overlap (the omelet labels have the egg cracked while tomatoes cook); the evaluation tolerates that
  (section 4.1), the contract does not.
- `clip` pads the step by ≤ 1 s each side (`CLIP_PAD_S`) and must contain `[start_s, end_s]`; it is
  the range the server cuts and the app loops. `cover_s` lies inside the step.
- `quote` is null or words that appear verbatim in the transcript turns `turn_ids`: consecutive turns,
  **numbered from 0** by their position in `turns` of the transcript file. The prompt shows each turn
  with that number (`#4 [00:12–00:15] …`), so the model can cite it. Muse Voice Transcribe gives no word
  timestamps, so `start_s`/`end_s` are where the quoted words are estimated to be: each turn's time spread
  over its words by length (`guides.quote_times`; 10/30). Turns run ~17 s and clips ~10 s, so the turn
  bounds dropped 63 of 170 quotes that were said inside the clip. Guides built before 10/30 carry the turn
  bounds, which the check still accepts.
- `inputs_provided` records what was **given** to the model; it does not claim the model used it. Use
  is measured by the ablation in 4.4.
- `category` comes from a fixed taxonomy (section 4.3).

**Code changes to make before B2 output exists** (the contract above is the target; today's code has
the v0 fields):
- `src/pr/guides.py` `Guide` model: `Quote` gains `end_s` and `turn_ids`; `inputs_used` →
  `inputs_provided`. The validator checks, per step:
  `0 ≤ clip.start_s ≤ start_s < end_s ≤ clip.end_s ≤ duration_s`, padding ≤ `CLIP_PAD_S` on each side,
  `start_s ≤ cover_s ≤ end_s`, indexes 1, 2, 3, … in order, and steps not overlapping.
- **Transcript check, separate from the model** (it needs the transcript file named in
  `provenance.transcript_id`): every `turn_ids` entry exists and the turns are consecutive, the quote
  text matches them (4.4), and the turns lie inside the clip. Run by the B2 builder before saving and
  by the evaluator.
- **Stored guides** (`results/app/guides/`, not in git): all six today (`seed_*` and three `g_*` from
  test uploads) carry `inputs_used` in `guide.json` and `model.json`. None is real model output (all
  come from `from_checklist`), so they are **deleted and regenerated**, not migrated: seeds by re-running
  `scripts/seed_guides.py`, `g_*` by re-running `tests/test_guides_api.py`. The model refuses the old
  fields rather than silently mapping them.
- `from_checklist` writes the new fields; `tests/test_guides_api.py` asserts the new contract
  (`inputs_provided`, `quote` shape, validator failures on a bad clip and a bad cover).
- `ios/ProcedureReplay/API.swift`: `Quote` and the guide struct follow the same fields.
- `src/pr/transcribe.py` `context_block`: prefix each turn with `#<index>`.
- **B2 dependency:** `build_guide` in `src/pr/server.py` is still `checklist_builder`, which returns the
  committed checklist for the task. B2 replaces it with the real builder, which runs on the uploaded
  recording; `source_video_id` must name that recording (and pass the license gate), not the dataset's
  reference video.

## 3. Data and splits

### 3.1 What we have (human step labels with start/end seconds, `data/keysteps/`)

| Domain | Source | Labelled takes | Participants (takes) | Narration |
|---|---|---|---|---|
| Factory: PC repair (9 steps, ~2–8 min) | IndEgo Task 22, CC BY 4.0 | 15 correct + 31 with mistakes | u01 (12), u02 (6, mistakes only), u14 (8), u15 (6), u16 (6), u17 (8) | none |
| Factory: drill bit (5 steps, ~1 min) | IndEgo Task 7, CC BY 4.0 | 22 correct + 21 with mistakes | u01 (8), u02 (8), u14 (8), u15 (7), u16 (6), u17 (6) | none |
| Home cooking: herb omelet (15 steps, ~12–30 min) | CaptainCook4D, Apache-2.0 | 17 (6 normal, 11 with mistakes) | person 1 (4), 3 (4, mistakes only), 6 (5), 7 (4) — `manifest.csv` | none |

No video in these sets contains speech (checked 2026-10-27 with Muse Voice Transcribe, ~57 min).

A take "with mistakes" is still a valid segmentation target: its labels describe what the person
actually did, and the guide is judged against that.

### 3.2 Narrated videos (B1, in progress)

- **English only, existing footage, first-person only** (no self-recording). Selection rule
  (2026-10-27): the camera is at the worker's eyes or chest with their hands doing the task, as with
  smart glasses; the person doing the task explains it out loud in English; one task or recipe;
  CC0 / CC BY / CC BY-SA / Pexels / Pixabay / Apache-2.0 / MIT (no NC, no ND). Third-person cooking
  shows were dropped. These videos have no human step labels, so we label them ourselves (3.4).

  Downloaded (license re-checked with yt-dlp metadata; first-person checked on frames):

  | video_id | Domain | Video | Length |
  |---|---|---|---|
  | `yt_P-pHllvP0wo` | Cooking (restaurant) | POV Restaurant Cooking: Make this order with me #6, Abraham Moreno | 10:36 |
  | `yt_LPwPomA7BfM` | Repair (plumbing) | Dripping Faucet Repair, The Old Corona (burned-in captions) | 1:20 |

  Candidates under the same rule (CC BY label and English captions found; viewpoint inferred from 3
  frames; speech and picture not checked yet):

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

- **Narrated split (by creator, so no creator is in both):**

  | Split | Cooking | Repair |
  |---|---|---|
  | dev | Ghanzi, EASY FRIED RICE (candidate; to download and check) | `yt_LPwPomA7BfM`, The Old Corona |
  | test | `yt_P-pHllvP0wo`, Abraham Moreno | Ultra Plumbing, Inline PVC Pipe Repair (candidate; to download and check) |

  All other Abraham Moreno videos stay out of dev. **Before B2, all four videos are checked for real
  speech (transcribed), first-person picture (watched, not 3 frames) and license.** A video that fails
  is replaced by another creator's video under the same rule. The transcript → guide path must run end
  to end on the dev videos before B2 counts as started.

  With one test video per domain, narrated test results are reported as **case results** (per video,
  with what went wrong), not as a domain accuracy figure.

- **Claim limit.** None of these was filmed on Meta glasses, and we do not record our own. Results show
  that the model builds guides from **first-person narrated work video**; they do not show the
  glasses capture flow. The capture path is covered only by the iOS spike (mock glasses stream), and
  the demo and write-up say so.
- **Optional: one assembly dataset.** IndustReal is Apache-2.0 but has no speech (segmentation only).
  HoloAssist is CDLA-Permissive-2.0 (commercial use and changes allowed) with instructor speech, but
  CDLA is not yet on our license list — a decision for the user.

### 3.3 Exposure in earlier work and the splits

Every video sent to a model so far (`data/ground_truth*.jsonl`, `data/proxy/`, `results/`), by participant:

| Exposure | Meaning | PC repair | Drill bit | Omelet |
|---|---|---|---|---|
| reference | step prompts and guides were built on it | u17 | u01 | person 6 |
| old dev | review prompts were tuned on it | u01, u15, u16, u17 | u02, u15, u16, u17 | person 1 |
| old eval | used in earlier evaluations, never in guide or step-prompt tuning | u14 | u14 | person 7 |
| never sent | no model call found for any take (logs, proxies, results) | u02 | — | person 3 |

"Old eval" is not a single frozen run: the old test set was scored by two pipelines (README, test-set
history), and `results/costs.csv` has repeated review and re-check calls on `22_u14_r03_c_01`,
`07_u14_r04_c_01` and `cc4d_22_6`; `cc4d_22_6` was also used in the SAM tracking trial, and `cc4d_22_8`
was viewed when picking the reference. The new guide prompt has never seen them.

Rule: a participant with any **reference** or **old dev** exposure is dev-only. Test participants come
from "never sent" first, then "old eval".

| Task | dev participants | test participants |
|---|---|---|
| PC repair | u01, u15, u16, u17 | u02 (never sent; mistake takes only), u14 (old eval) |
| Drill bit | u01, u02, u15, u16, u17 | u14 (old eval) |
| Omelet | person 1, person 6 | person 3 (never sent; mistake takes only), person 7 (old eval) |
| Narrated | 3.2 | 3.2 |

Reporting on test:
- **Never sent and old eval are reported separately**, and **correct and mistake takes separately**
  (PC u02 and omelet person 3 have only mistake takes, so they say nothing about correct takes).
- Drill bit has no never-sent participant. Its test number is reported as **"held out from guide
  tuning, used in earlier evaluations"** and is not presented as an independent test.
- The test as a whole is exploratory: a few participants per task, one annotator per dataset.
- During B2–B3, leave-one-participant-out on dev is allowed as a cross-check (report per-participant
  numbers). Test participants stay out of every run until B4.
- Test is run **once**, at B4, with the frozen configuration.

### 3.4 Labelling the narrated videos and the label groups

**Narrated labels.** For each narrated video: one person (the user) marks step start/end seconds and a
short step name, watching at 1×, before any model output is seen. Claude may prepare a blank template
(video duration, transcript with timestamps) but does not propose boundaries, to avoid anchoring the
labels on the model. Labels for dev videos are made before B2; for test videos, before B4.

**Label units** are fixed before B2 from the labels and the step text only, never from model output,
and the user approves them. Two label sets per video:
- **Fine units** (primary metric). Labels whose start and end are identical **in that video** become one
  unit; nothing else is merged. This is computed per video, not per task: the omelet "scoop the
  tomatoes" + "put tomatoes on a serving plate" are identical in 7 of 17 takes (one unit there) and only
  partly overlap in 4 (two units there). Partly overlapping or concurrent labels (the egg cracked while
  the tomatoes cook) stay separate. A unit made of several labels is matched only by a step whose text
  describes **all** of its actions (the labels give no way to tell them apart in time).
- **Coarse units** (secondary metric). `data/label_groups/<task>.json` lists `allowed_merges`, a fixed
  set of **disjoint** groups of steps a good guide may reasonably show as one (e.g., omelet "add the
  chopped cilantro" + "add 1/2 tsp ground black pepper"; "stop stirring" + "transfer omelette"). In each
  video, a group is merged **only if all its labels exist in that video and are adjacent** there (no
  other label starts between them in time order); otherwise its labels stay as fine units. A step can
  be labelled twice in one video (10 of 106 takes, e.g. drill "remove bit" redone): labels are sorted by
  start, and a merge is applied left to right wherever a run of consecutive labels is exactly the
  group's set. This covers
  mistake takes with a step left out and takes with steps swapped. A merged unit's interval runs from
  the earliest start to the latest end of its labels, and it counts as **one** unit. The rule is
  applied mechanically by the evaluator, never chosen after seeing a prediction.

## 4. Metrics

### 4.1 Segmentation (all labelled videos)

**Primary: step hit F1 on fine units.** A predicted step *p* hits a fine unit *g* when all three hold:
1. **Overlap** — *p* covers ≥ 50% of *g*'s interval. (Only these pairs go to the judge.)
2. **Same action** — the judge (4.2) says *p*'s title and instruction describe *g*'s action (all of
   them, for a multi-label unit).
3. **Not too long** — *p*'s clip is ≤ max(2 × |g|, |g| + 6 s). The `+ 6 s` term is for short steps:
   drill labels have a median of 5.9 s and 103 of 199 are ≤ 6 s, so 1 s padding plus a little slack
   would otherwise fail on length alone. (Median label length: PC 10.9 s, omelet 23.9 s.)

Hits are matched one-to-one (maximum bipartite matching over hit pairs). Recall = matched fine units /
fine units; precision = matched predicted steps / predicted steps. Each predicted step and each unit is
used at most once, so one long step earns at most one true positive, however many labels it covers.
Reported per domain, and per video for the paired comparison in section 5.

The length cap does not stop a long omelet step from containing other work (2 × a multi-minute label is
long). That is measured separately, not by failing the hit, because concurrent work (the egg cracked
while the tomatoes cook) and waiting that is part of the job (the pan heating) are normal:

Secondary:
- **Clip focus** (matched steps): computed from the label intervals, no judge: whether the clip holds
  ≥ 10 s of a **different, non-concurrent** labelled step (a label that does not overlap *g* in time).
  Reported as the share of matched clips without such a stretch. Concurrent labels and waiting inside
  *g*'s own interval never count against it.
- **Merge-tolerant hit F1:** the same rule on coarse units (3.4). For a merged unit the judge must
  confirm that the text and the clip contain **each** of its actions; the length cap uses the merged
  interval.
- **Length ratio:** clip length / matched unit length, median and max per domain.
- **Temporal IoU F1** at IoU ≥ 0.3, one-to-one, no semantic check (comparable with the uniform baseline).
- **Order agreement:** Kendall τ between predicted and label order over matched steps, ignoring pairs of
  labels that overlap in time.
- **Granularity ratio:** predicted step count / label unit count.
- **Boundary error:** median |Δstart| and |Δend| in seconds over matched steps, and divided by label length.

### 4.2 Instruction quality (matched steps)

Rubric, each item 0/1, per step:
1. Action matches what the hands do.
2. Key objects are correct; no object or tool that is not in the clip.
3. `done_when` is observable in the clip and correct.
4. Instruction is actionable for a first-timer (imperative, specific, ≤ 2 sentences).

**Judge input:** the whole step clip (video), the transcript turns inside the clip, the human label, and
the guide step. The same call answers "same action" for 4.1; clip focus is computed from labels.

**Judge model:** open (section 8). A model other than Muse Spark avoids self-preference but adds cost and
a dependency; either way the human check below is required.

**Human check** (test only, run 1 of the frozen configuration). The user scores items **blind to
configuration and model** (shuffled, no run IDs). The sample covers the matching, not only matched
steps, so false matches and misses are checked too:

| Domain | Sample |
|---|---|
| PC, drill, omelet (each) | 20 items from the main configuration: 10 judge-accepted pairs, 5 judge-rejected pairs (overlap ≥ 50% but "same action" said no), 5 unmatched predicted steps; plus 5 accepted pairs from "uniform + captions" (section 5), mixed in blind |
| Narrated cooking, narrated repair | **every** step of the one test video, all candidate pairs, main configuration |
| Metadata (4.3) | every test guide (title, summary, category; about 32 guides) |

Drawing: random, fixed seed. If a category has fewer items than its quota, all of them are taken and
the rest is filled from the other categories of the same domain (accepted first). **The actual number
of items per category is recorded** and shown next to every agreement figure.

Unmatched predicted steps: the user sees the step's clip and text, the labels that overlap it in time
(any overlap) and the video's full label list, and answers whether one of those labels is the same
action. A "yes" is a miss by the judge or the overlap rule, and is reported as such.

What is scored on which item: "same action" on every pair and every unmatched step; the 4 rubric
items on accepted pairs only (a smaller denominator, e.g. 10 + 5 baseline).

Rule, per domain and per judged item, on **that item's actual count n**: agreement is reported as a count
(e.g. "same action 18/20", "done_when 9/10"). If disagreement is ≥ 15% of n, more items are drawn the same
way, as many as are available up to n again. If disagreement is still ≥ 15% of the enlarged count, that
metric is shown for that domain as **"verification incomplete"**, with the user's scores on the sampled
items next to it; it is not replaced by a sample score or reported as a domain number. The user's
score is final on every disagreement (one annotator; stated as a limitation).

The human check is done on **run 1** of the 3 test runs only. Every test table that shows a 3-run mean
says so next to the judged metrics.

### 4.3 Guide metadata

- **Category exact match** against a fixed taxonomy v1: `repair_maintenance`, `electronics`,
  `workshop_tools`, `assembly`, `cooking`, `cleaning_household`, `crafts`, `other`. Ground truth set by
  us per task. Top-2 match reported too.
- **Title** (0/1): names the actual task and object.
- **Summary** (0/1): faithful, no step or claim that is not in the video.

### 4.4 Narration use (narrated videos only)

- **Quote fidelity:** every non-null `quote` appears in its `turn_ids` (normalized edit similarity ≥ 0.9
  against a span of those turns) and the quoted words' estimated times lie **inside** the step's clip
  (± 1 s), so the words the app shows are heard in the clip it loops. Target 100% — the app shows it as the instructor's
  words, so a fabricated quote is a hard failure.
- **Quote rate:** share of steps with a non-null quote, reported next to fidelity (all-null quotes
  would pass fidelity trivially).
- **Narration ablation:** the same metrics with and without the transcript in the prompt. With 4
  narrated videos this is reported **per video** (delta per metric, mean and range over 3 runs) with the
  failure cases written out, not as a pass/fail. Both repair videos have burned-in captions, so removing
  the transcript leaves the words on screen: there it measures the **added effect of the transcript
  text**, not the effect of narration as such.

### 4.5 Reliability and cost

- Each dev configuration runs **3 times**; report mean and min–max (run-to-run variance was large in the
  review experiments).
- Cost and latency per guide from `results/costs.csv` (a steps call has cost about $0.007 so far).

## 5. Baselines and targets

**Baselines** (never given the label step count):
- **Uniform:** cut the video into equal parts of length L = median label length of that domain's **dev**
  labels. Compared on temporal IoU F1 and boundary error only (it has no text).
- **Uniform + captions:** the same parts, each described by Muse Spark with the same step prompt minus
  segmentation and **the same inputs** as the main configuration (video, transcript, on-screen text,
  audio setting). Compared on step hit F1 and the rubric; this separates "finds good steps" from
  "writes good text".

**Hard requirements (must hold on test):** contract validity 100% (the `Guide` validator passes; the
server can cut every clip and cover); quote fidelity 100%, reported with the quote rate.

**Comparative goal:** report, per domain, the **per-video paired difference** in step hit F1 (main −
uniform + captions), the number of videos where the main configuration wins, and the mean and range of
the difference. No significance is claimed. Absolute numbers are reported as they are; no absolute
target is claimed.

**What "test once" means:** the configuration is frozen once (B4). That frozen configuration, and the
baselines, are run 3 times each on test, and no change is made after seeing any test number. Means and
ranges in test tables are over those 3 runs.

**Pairing:** main run *k* is paired with baseline run *k* (k = 1, 2, 3; same video, same judge
model). The per-video difference is averaged over the 3 pairs; its range is the min–max over the pairs.

## 6. Ablations planned (B2–B3)

1. Video only vs video + transcript (narrated set).
2. Unseeded vs seeded with expert step names (labelled sets) — tells us how much of the earlier score
   came from the names.
3. On-screen text on vs off. "On" means the prompt asks the model to read text visible in the video
   into `on_screen_text`; there is no separate OCR step. "Off" removes that instruction and the field.
4. Audio in the video on vs off (earlier review experiments: off was better with Muse Spark 1.3).

**Builder inputs are fixed** (`src/pr/build.py`), the same for app recordings and evaluation: the video
(5 fps proxy with the clock, sound removed unless ablation 4), its duration, the transcript turns when
transcript is on (transcribed from the **original** audio before the proxy is muted), the category
taxonomy, and the instructor's Mark step times when the app sends them. Nothing derived from labels or
task config goes in: no step count, no task name, no `keysteps`, no `object_prompts`, except the names
in ablation 2. `inputs_provided` and `provenance.prompt_version` record the configuration of every run.

## 7. Iteration protocol (B2–B4)

One round = change one thing → run the **iterate set** 3× → metrics table
(`results/summary_guides_dev.md`) → Codex review → decide. The iterate set (`config/splits.yaml`) is every
correct/normal take of the dev participants plus one fixed take with mistakes per dev participant (PC 12 +
4, drill 18 + 5, omelet 4 + 2) and the narrated dev videos. The full dev set (76 labelled takes + narrated
dev) is run at the B2 baseline and once before the freeze. Cost and time per round are measured at the
B2 baseline, not assumed.

**Early judge check (dev):** after the B2 baseline, the user blind-scores 30 dev items drawn as in 4.2
(10 per labelled domain, baseline items mixed in), so a judge that favours its own model's output is
found before B3 tunes against it, not at B4. Rounds planned: baseline (B2), 2–3 iterations (B3), freeze and test (B4).
Stopping rule: freeze on 2026-11-01 regardless of results; report test numbers as they are.

## 8. Open questions

1. ~~Judge model~~ — closed 2026-10-28: Muse Spark (it takes the clip video directly), with the early dev
   check in §7 and the B4 human check.
2. Whether to add HoloAssist (CDLA-Permissive-2.0) to the license list (3.2).
3. Whether 2 narrated test videos (one per domain) are enough for the demo claim, or B1 should find a
   third (another domain, e.g. maintenance).

## 8a. Changes after the B2 design review (2026-10-28)

- Iterate set adds one fixed mistake take per dev participant; full dev at baseline and before freeze.
- Builder inputs fixed and free of label-derived data (no step count, task name, keysteps, objects).
- On-screen text = the model reads it from the video; transcript taken from the original audio.
- Early blind judge check on 30 dev items after the B2 baseline.
- Repeated labels in one video: merges applied left to right on consecutive runs.
- Clip focus computed from label intervals instead of asked of the judge (deterministic, one less judged item).
- Judge model: Muse Spark, a separate call and prompt from the builder (§8 question 1 closed).

## 9. Changes from v3 (Codex review #3)

- "Clean clip" removed from the primary hit; replaced by a secondary "clip focus" metric that ignores
  concurrent labels and waiting inside the step.
- Fine units: a multi-label unit needs every action in the text. Coarse units: disjoint fixed groups,
  merged only where all labels exist and are adjacent in that video; merged interval = earliest start to
  latest end.
- Human check: actual counts per category and per item, shortfall filled from other categories, rate
  computed on each item's actual n, extra draw limited to what exists; unmatched-step procedure
  defined; 5 baseline pairs per domain mixed in; run-1-only limitation shown in tables.
- Contract: full validator ranges, a separate transcript check, stored guides deleted and regenerated
  (none is real model output), seed script and API test listed, B2 dependency on `build_guide` and
  `source_video_id`.
- "Never sent" means no call found in the logs. Main/baseline run pairing defined.

## 10. Changes from v2 (Codex review #2)

- Exposure: "old test only" → "old eval" (two test pipelines and repeated review calls, not one frozen
  run). Drill test is not presented as independent; never-sent / old-eval and correct / mistake takes are
  reported separately.
- Primary metric uses per-video fine units only; `allowed_merges` moved to a secondary score on a fixed
  coarse set where each merge is one unit. "Clean clip" judged in addition to the length cap; length
  ratio reported.
- Contract matches the server design: times only, server cuts clips and covers; `cover_s` kept;
  0-based `turn_ids` shown in the prompt; list of code changes before B2.
- Human check samples accepted, rejected and unmatched pairs; agreement as counts; double-the-sample
  rule, then "verification incomplete"; narrated test fully scored.
- Baselines get the same inputs; goal is the per-video paired difference; "test once" defined; quote
  rate and "quote inside clip"; burned-in captions caveat for the narration ablation.

## 11. Changes from v1 (Codex review #1)

- Splits redone from actual exposure (3.3): the v1 test participants PC u17 and drill u01 were the
  reference videos the earlier guides were built on; both are now dev-only. Omelet now splits by person
  (`manifest.csv` has person IDs), not by take.
- Primary metric is now semantic + overlap + clip length (step hit F1), against label groups fixed in
  advance; temporal IoU F1 is secondary; order is measured separately so overlapping labels are not
  penalized. v1's 50%-coverage recall, which one long step could inflate, is dropped.
- Narrated videos: one dev video per domain before B2, test by a different creator; claim limit stated.
- Judge sees the whole clip and transcript; human check is a fixed blind stratified sample with a rule
  for disagreement.
- Contract: (bundle with clip/cover assets — reverted in v3), `quote.turn_ids` and `end_s`, `inputs_used` →
  `inputs_provided`, transcript reference in provenance.
- Absolute targets replaced by baselines + hard requirements; narration effect reported per video.
