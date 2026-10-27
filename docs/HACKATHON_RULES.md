# Hackathon rules that constrain this build

Event: Meta Global AI Developer Hackathon, indie track, theme "Push the Frontier" (manufacturing).
Build window: Oct 26 – Nov 4, 2026. Submission due Nov 4, 2026, 9:00 PM ET.

## Official rules (verbatim, received Oct 26, 2026)

> Meta Global AI Developer Hackathon — Rules
>
> Read these before you build. Breaking them can disqualify your project.
>
> New work only. Everything you present has to be built during the hackathon, Oct 26 to Nov 4.
>
> Identify your contributions. Your demo has to show only the features, code and functionality your team built during the event. Judges need to be able to tell what's new. If they can't, the project is disqualified.
>
> Public repo. Your submitted repository must be public.
>
> Teams. Max 4 people, solo is allowed. Pick one track, Indie Developer or Startup, and enter the project in that track only. One person submits for the team.
>
> Demo video. 3 minutes, required on the submission. It's one of the main things judges score.
>
> Banned projects. Disqualified if they break legal, ethical or platform policies, or use code, data or assets you don't have the rights to. Also avoid the generic stuff such as AI medical or health advice, Basic RAG apps, Simple image analyzers, "AI for education" chatbots, Job application screeners, Nutrition coaches, Personality analyzers, Sports analyzers or coaches
>
> Theme. Your project has to fit one of the two problem statements:
> Build for Your World — bring Meta's models into a domain you know and solve a real problem in it.
> Push the Frontier — use Muse Spark, Glimmer, SAM 3 or other Meta models on hard problems in software, robotics, manufacturing, energy or science.
>
> Submit by Wed Nov 4, 9:00 PM ET: https://cerebralvalley.ai/e/meta-ai-developer-hackathon/hackathon/submit
> Public repo, working demo video link, every team member added.
>
> Also in the waiver you agreed to: you must be 18+ and of legal age where you live, and Meta or CV staff, contractors, government-affiliated people and their households can't participate.

## Project policy (stricter than the official rules)

From the project brief, Oct 26, 2026. These govern every commit.

- **New work only**: everything is built Oct 26 – Nov 4, starting from an empty repo, with no pre-existing code of
  mine. Third-party open-source libraries are fine but must be listed.
- **Identify contributions**: README keeps a "Built during the hackathon" section (each component we wrote) and a
  "Third-party" section (libraries, models, datasets). Commit early and often with descriptive messages.
- **Public repo at submission**: never commit secrets, API keys, raw or edited videos, or large binaries. Our code is MIT.
- **Data rights**: the official rule only says we must have the rights to what we use. We make that concrete:
  - Allowed video licenses: **CC0, CC-BY, CC-BY-SA, Pexels, Pixabay, Apache-2.0**.
  - **Never ND** (we cut and reorder videos) and **never NC**. The event has prizes and a Startup track, so
    "non-commercial" is ambiguous; we don't take that risk.
  - Apache-2.0 was added on Oct 26 for CaptainCook4D: it grants use, modification and redistribution, including
    commercial. Its conditions are attribution, a link to the license, and marking modified files. ATTRIBUTION.md
    covers all three; the demo video credits do the same.
  - Every video has source URL, creator and license in `data/manifest.csv` and `ATTRIBUTION.md`.
  - Rejected for licensing: Ego4D / Aria datasets (custom licenses), EPIC-KITCHENS, HD-EPIC, EPFL Smart Kitchen,
    Assembly101 (NC), EgoPER (no license stated).
- **Avoid the banned generic categories**: we are not a chatbot or a simple image analyzer. The demo must show the
  multi-stage pipeline and the quantitative evaluation. The cooking scenario covers recipe steps and order only,
  never nutrition or health advice.
- **3-minute demo video is a main judging factor**: scripts render annotated output videos and a results table.

## How this repo enforces them

| Rule | Enforcement |
| --- | --- |
| Rights on every video | `src/pr/license_check.py` refuses any video whose manifest row lacks an allowed license, creator, or source URL. Every script calls it before touching a file. |
| No videos / secrets in git | `.gitignore` excludes `.env`, `data/raw/`, `data/edited/`, `data/proxy/`, `*.mp4`, `*.mov`, and generated results. |
| Edits are attributed | `src/pr/inject.py` logs every cut/swap under the source video's entry in `ATTRIBUTION.md`. |
| Contributions visible | README "Built during the hackathon" + one commit per build step. |
