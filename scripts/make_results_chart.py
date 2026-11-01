"""README results chart: step hit F1 of the guide builder vs. the uniform-split baseline, per domain.

Reads the domain table of results/summary_guides_<set>.md, so after B4 rerun with --set test.

    uv run python scripts/make_results_chart.py            # dev  -> docs/assets/results_dev.svg
    uv run python scripts/make_results_chart.py --set test # test -> docs/assets/results_test.svg

One SVG that follows the viewer's light/dark setting (prefers-color-scheme inside the SVG).
"""

from __future__ import annotations

import argparse
import re
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_table(path: Path) -> list[dict]:
    """Rows of the first markdown table: domain, videos, ours, baseline, wins."""
    lines = path.read_text().splitlines()
    head = next(i for i, l in enumerate(lines) if l.startswith("| domain"))
    cols = [c.strip() for c in lines[head].strip("|").split("|")]
    rows = []
    for line in lines[head + 2:]:
        if not line.startswith("|"):
            break
        cells = dict(zip(cols, (c.strip() for c in line.strip("|").split("|"))))
        num = lambda s: float(re.match(r"[-+]?[\d.]+", s).group())
        wins = re.search(r"\((\d+)/(\d+)\)", cells["paired diff (wins)"])
        rows.append({"domain": cells["domain"], "videos": int(cells["videos"]),
                     "ours": num(cells["step hit F1"]), "base": num(cells["uniform+captions"]),
                     "wins": int(wins.group(1)), "n": int(wins.group(2))})
    return rows


def svg(rows: list[dict], subtitle: str) -> str:
    W, left, right = 760, 190, 120
    top, group, bar, gap = 92, 74, 22, 6
    H = top + group * len(rows) + 46
    plot = W - left - right
    x = lambda v: left + plot * v  # F1 is 0..1

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" '
           f'aria-labelledby="t d">',
           '<title id="t">Step hit F1: ProcedureReplay vs. cutting the video into equal parts</title>',
           '<desc id="d">' + escape("; ".join(
               f"{r['domain']}: {r['ours']:.2f} vs {r['base']:.2f}, better on {r['wins']} of {r['n']} videos"
               for r in rows)) + "</desc>",
           """<style>
  .bg{fill:#ffffff} .ink{fill:#1b1b1f} .mute{fill:#6b6b74} .grid{stroke:#e6e6e2}
  .ours{fill:#2f5bd3} .base{fill:#c4c4cc} .oursv{fill:#2f5bd3}
  text{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}
  @media (prefers-color-scheme:dark){
    .bg{fill:#0d1117} .ink{fill:#e6edf3} .mute{fill:#9198a1} .grid{stroke:#262b33}
    .ours{fill:#6f8cff} .base{fill:#4a4f58} .oursv{fill:#8ea5ff}
  }
</style>""",
           f'<rect class="bg" width="{W}" height="{H}" rx="12"/>',
           f'<text class="ink" x="24" y="36" font-size="19" font-weight="700">'
           f'How many of the expert\'s steps the guide gets right</text>',
           f'<text class="mute" x="24" y="60" font-size="13">{escape(subtitle)}</text>']
    # legend
    lx = left
    out += [f'<rect class="ours" x="{lx}" y="72" width="12" height="12" rx="3"/>',
            f'<text class="ink" x="{lx + 18}" y="82.5" font-size="12.5">ProcedureReplay (Muse Spark)</text>',
            f'<rect class="base" x="{lx + 210}" y="72" width="12" height="12" rx="3"/>',
            f'<text class="ink" x="{lx + 228}" y="82.5" font-size="12.5">Equal-length cuts + captions</text>']
    gy0, gy1 = top + 8, top + group * len(rows)
    for v in (0, 0.25, 0.5, 0.75, 1.0):
        out += [f'<line class="grid" x1="{x(v):.1f}" y1="{gy0}" x2="{x(v):.1f}" y2="{gy1}" stroke-width="1"/>',
                f'<text class="mute" x="{x(v):.1f}" y="{gy1 + 18}" font-size="11.5" text-anchor="middle">{v:g}</text>']
    out.append(f'<text class="mute" x="{left + plot / 2:.1f}" y="{gy1 + 36}" font-size="11.5" text-anchor="middle">'
               f'step hit F1 (0–1)</text>')
    for i, r in enumerate(rows):
        y = top + group * i + 16
        out += [f'<text class="ink" x="24" y="{y + bar - 4}" font-size="14.5" font-weight="600">{escape(r["domain"])}</text>',
                f'<text class="mute" x="24" y="{y + bar + gap + bar - 5}" font-size="12">{r["videos"]} videos × 3 runs</text>',
                f'<rect class="ours" x="{left}" y="{y}" width="{x(r["ours"]) - left:.1f}" height="{bar}" rx="4"/>',
                f'<text class="oursv" x="{x(r["ours"]) + 8:.1f}" y="{y + bar - 6}" font-size="14" font-weight="700">'
                f'{r["ours"]:.2f}</text>',
                f'<rect class="base" x="{left}" y="{y + bar + gap}" width="{x(r["base"]) - left:.1f}" height="{bar}" rx="4"/>',
                f'<text class="mute" x="{x(r["base"]) + 8:.1f}" y="{y + 2 * bar + gap - 6}" font-size="13">'
                f'{r["base"]:.2f}</text>',
                f'<text class="ink" x="{W - 24}" y="{y + bar + 2}" font-size="13" text-anchor="end">'
                f'better on</text>',
                f'<text class="ink" x="{W - 24}" y="{y + bar + 19}" font-size="13" font-weight="700" text-anchor="end">'
                f'{r["wins"]}/{r["n"]} videos</text>']
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="dev")
    args = ap.parse_args()
    rows = read_table(ROOT / f"results/summary_guides_{args.set}.md")
    sub = (f"{args.set} set · hit = covers at least half of an expert-labelled step, clip not padded, "
           "judge sees the same action")
    path = ROOT / f"docs/assets/results_{args.set}.svg"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(svg(rows, sub))
    print(path)


if __name__ == "__main__":
    main()
