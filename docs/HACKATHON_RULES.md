# Hackathon rules that constrain this build

Event: Meta Global AI Developer Hackathon, indie track, theme "Push the Frontier" (manufacturing).
Build window: Oct 26 – Nov 4, 2026. Submission due Nov 4, 2026, 9:00 PM ET.

Copied from the project brief on Oct 26, 2026 (day 1). These rules govern every commit.

- **New work only**: everything must be built Oct 26 – Nov 4. Start from an empty repo. Do not copy any
  pre-existing code of mine. Third-party open-source libraries are fine but must be listed.
- **Identify contributions**: judges must be able to tell what was built during the event. Maintain a
  "Built during the hackathon" section in README listing each component we wrote, and a "Third-party"
  section listing libraries, models, and video sources. Commit early and often with descriptive messages
  so history shows the progression.
- **Public repo at submission**: assume the repo will be public. Never commit secrets, API keys, raw or
  edited videos, or large binaries. Add an MIT LICENSE for our code.
- **No data/assets without rights**: only use videos licensed CC0, CC-BY, CC-BY-SA, or Pexels/Pixabay
  license. Exclude ND (no derivatives — we edit videos) and NC. Every video must have source URL, creator,
  and license recorded in `data/manifest.csv` and `ATTRIBUTION.md`.
- **3-minute demo video is a main judging factor**: we need scripts that render annotated output videos
  and a results table for it.
- **Avoid looking like a "simple image analyzer"**: the demo must make the multi-stage pipeline and the
  quantitative evaluation visible.

## How this repo enforces them

| Rule | Enforcement |
| --- | --- |
| Rights on every video | `src/pr/license_check.py` refuses any video whose manifest row lacks an allowed license, creator, or source URL. Every script calls it before touching a file. |
| No videos / secrets in git | `.gitignore` excludes `.env`, `data/raw/`, `data/edited/`, `data/proxy/`, `*.mp4`, `*.mov`, and generated results. |
| Edits are attributed | `src/pr/inject.py` logs every cut/swap under the source video's entry in `ATTRIBUTION.md`. |
| Contributions visible | README "Built during the hackathon" + one commit per build step. |
