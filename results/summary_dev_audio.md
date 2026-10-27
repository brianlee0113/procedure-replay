# Audio experiments (dev set)

Run 2026-10-27. Dev set only: 9 injected flaws + 2 clean videos, 3 independent review runs per variant,
scored with re-check (the default pipeline). The test set was not run.

## Is anything said in the videos?

Muse Voice Transcribe (`muse-voice-transcribe-1.0`) on the three reference videos (PC repair 8:12,
drill bit 0:51, omelet 11:51) and three dev trainee videos (PC 2:19, drill 1:02, omelet 31:42):
**no speech at all** (0 turns in ~57 min of audio; a synthetic speech clip through the same client
transcribes correctly). The sound is tools, parts and the room, so a transcript-in-the-prompt variant was
not run.

## Results

| Variant | Detected per run | Mean | False flags per run | Extra flags on flawed (sum) | Vote |
|---|---|---|---|---|---|
| a. Muse Spark 1.3, with audio (baseline, `summary_dev.md`) | 4 / 3 / 5 of 9 | 4.0 | 0 / 0 / 0 of 2 | 9 | 4/9, 0/2 |
| b. Muse Spark 1.3, **no audio** (`--mute`) | 4 / 6 / 6 of 9 | 5.3 | 0 / 0 / 0 of 2 | 5 | 5/9, 0/2 |
| c. Muse Spark 1.2, with audio (`--model muse-spark-1.2-contributor`) | 4 / 4 / 6 of 9 | 4.7 | 0 / 0 / 0 of 2 | 4 | 4/9, 0/2 |

Detections per video over the 3 runs:

| Flawed video | a. 1.3 audio | b. 1.3 mute | c. 1.2 audio |
|---|---|---|---|
| PC swap close/test (22_u17) | 3 | 3 | 3 |
| Drill swap insert bit/plug in (07_u16) | **0** | **3** | 1 |
| Omelet swap scoop/pour (cc4d_22_24) | 2 | 2 | 3 |
| PC cut fan (22_u15) | 0 | 0 | 0 |
| PC cut power (22_u16) | 0 | 0 | 0 |
| PC cut battery (22_u01) | 1 | 1 | 1 |
| Drill cut remove bit (07_u15) | 1 | 1 | 1 |
| Drill cut unplug (07_u02) | 3 | 3 | 3 |
| Omelet cut pepper (cc4d_22_24) | 2 | 3 | 2 |
| **Total of 27** | **12** | **16** | **14** |

Without the re-check, the muted variant raises false flags on the clean videos in 5 of 6 run-videos
(1.3 with audio: 2 of 6; 1.2: 0 of 6), so the re-check stays.

Muse Spark 1.2 returned JSON cut off mid-object 4 times in 3 runs (now asked again automatically);
1.3 never did.

## Reading

Muting is no worse than the baseline on any video and better on two (the drill swap goes from 0/3 to 3/3),
with no false flags and fewer extra flags. That matches Meta's note that audio understanding in Muse Spark
1.3 is not fully supported and can degrade quality. 1.2 with audio sits in between and is less reliable.
3 runs on 11 videos is still small; the two PC cuts (fan, power) are missed by every variant.

Cost of these experiments: $0.50 (transcription $0.06, reviews $0.44).
