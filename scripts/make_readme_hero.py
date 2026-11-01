"""Build the README hero video: the instructor's first-person recording on the left, the iPhone app on the right.

Left: the source video (The Old Corona, CC BY 3.0) plays end to end with a timeline under it. Once Muse Spark has
built the guide, the timeline fills with the guide's steps and the step under the playhead is named.
Right: the real screen recording of the app (record -> Meta AI builds -> draft -> publish -> feed -> step player),
sped up per phase. A caption above the video names each phase.

    uv run --with pillow python scripts/make_readme_hero.py
    -> docs/assets/hero.mp4 (and hero_poster.png)

Needs results/walkthrough/demo_raw_199s.mp4 and data/raw/narrated/yt_LPwPomA7BfM.mp4 (both kept out of git).
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SCREEN = ROOT / "results/walkthrough/demo_raw_199s.mp4"
SOURCE = ROOT / "data/raw/narrated/yt_LPwPomA7BfM.mp4"
GUIDE = ROOT / "results/app/guides/g_a311ab097def/guide.json"  # the guide built in that screen recording
OUT = ROOT / "docs/assets"

W, H, FPS = 1280, 720, 30
BG = (245, 245, 242)
INK = (27, 27, 31)
MUTE = (107, 107, 116)
ACCENT = (47, 91, 211)
BAR = (225, 225, 220)
STEP_COLORS = [(47, 91, 211), (86, 132, 235)]  # alternate so neighbouring steps read as separate blocks

# (start s, end s, speed-up, kicker, headline, sub, guide step on screen or None) in the screen recording.
# The step player phases skip the "Cutting the clip..." waits; the left video loops the same step clip at the same speed.
PLAYER = ("5 / 5  ·  TRAINEE", "Every step loops its own clip.",
          "Instruction, a done-when check, and the instructor's own words.")
PHASES = [
    (5.2, 65.0, 20, "1 / 5  ·  INSTRUCTOR", "Work and talk.", "The glasses record what you see and say.", None),
    (84.0, 172.8, 30, "2 / 5  ·  META AI", "Muse Spark builds the guide.",
     "Watches the video, listens to the narration, reads on-screen text.", None),
    (173.0, 178.0, 1.7, "3 / 5  ·  INSTRUCTOR", "Check the draft. Publish.",
     "Meta AI suggests the title, category and summary.", None),
    (178.0, 183.0, 1.7, "4 / 5  ·  TRAINEE", "Find it in the feed.", "Public guides show up for everyone.", None),
    (184.6, 187.8, 1.5, *PLAYER, 0),
    (190.0, 196.5, 2.0, *PLAYER, 1),
]

# layout
VX, VY, VW, VH = 64, 186, 768, 432          # source video
TX, TY, TW, TH = VX, VY + VH + 20, VW, 12   # timeline bar
PH = 640                                    # phone height
PW = round(1206 / 2622 * PH)
PX, PY = W - PW - 72, (H - PH) // 2

FONT = "/System/Library/Fonts/HelveticaNeue.ttc"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT, size, index=1 if bold else 0)


def png(path: Path, draw) -> Path:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw(ImageDraw.Draw(img), img)
    img.save(path)
    return path


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="hero_"))
    guide = json.loads(GUIDE.read_text())
    steps = [(s["start_s"], s["end_s"], s["title"]) for s in guide["steps"]]
    src_len = float(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(SOURCE)]))

    # output time of each phase
    bounds, t = [], 0.0
    for a, b, speed, *_ in PHASES:
        bounds.append((t, t + (b - a) / speed))
        t += (b - a) / speed
    total = t
    built_at = bounds[1][1]  # steps appear on the timeline when Meta AI is done

    def src_x(s: float) -> float:
        return TX + TW * s / src_len

    # static background: panel shadow, labels, attribution
    def background(d: ImageDraw.ImageDraw, img: Image.Image) -> None:
        d.rectangle([0, 0, W, H], fill=BG + (255,))
        d.rounded_rectangle([VX - 1, VY - 1, VX + VW, VY + VH], 14, fill=(0, 0, 0, 255))
        d.rounded_rectangle([PX - 10, PY - 10, PX + PW + 10, PY + PH + 10], 46, fill=(20, 20, 22, 255))
        d.text((VX, H - 26), "Footage: The Old Corona (YouTube), CC BY 3.0  ·  Right: real app run with Muse Spark, sped up",
               font=font(13), fill=MUTE + (255,))
    bg = png(tmp / "bg.png", background)

    # rounded mask for the source video and phone screen
    def mask(path: Path, w: int, h: int, r: int) -> Path:
        m = Image.new("L", (w, h), 0)
        ImageDraw.Draw(m).rounded_rectangle([0, 0, w - 1, h - 1], r, fill=255)
        m.save(path)
        return path
    vmask = mask(tmp / "vmask.png", VW, VH, 14)
    pmask = mask(tmp / "pmask.png", PW, PH, 38)

    # captions, one per phase
    captions = []
    for i, (_, _, _, kicker, head, sub, _) in enumerate(PHASES):
        def cap(d: ImageDraw.ImageDraw, img: Image.Image, kicker=kicker, head=head, sub=sub) -> None:
            d.text((VX, 56), kicker, font=font(15, True), fill=ACCENT + (255,))
            d.text((VX, 80), head, font=font(44, True), fill=INK + (255,))
            d.text((VX, 140), sub, font=font(21), fill=MUTE + (255,))
        captions.append(png(tmp / f"cap{i}.png", cap))

    # timeline before and after the guide exists
    def bar_empty(d: ImageDraw.ImageDraw, img: Image.Image) -> None:
        d.rounded_rectangle([TX, TY, TX + TW, TY + TH], 6, fill=BAR + (255,))
        d.text((TX, TY + 22), f"{src_len:.0f} s of first-person video with narration", font=font(18), fill=MUTE + (255,))
    def bar_steps(d: ImageDraw.ImageDraw, img: Image.Image) -> None:
        d.rounded_rectangle([TX, TY, TX + TW, TY + TH], 6, fill=BAR + (255,))
        for i, (a, b, _) in enumerate(steps):
            d.rounded_rectangle([src_x(a) + 1, TY, src_x(b) - 1, TY + TH], 4, fill=STEP_COLORS[i % 2] + (255,))
    empty = png(tmp / "bar_empty.png", bar_empty)
    full = png(tmp / "bar_steps.png", bar_steps)

    # name of the step under the playhead
    labels = []
    for i, (a, b, title) in enumerate(steps):
        def lab(d: ImageDraw.ImageDraw, img: Image.Image, i=i, title=title) -> None:
            kicker = f"Step {i + 1} of {len(steps)}"
            d.text((TX, TY + 22), kicker, font=font(18, True), fill=ACCENT + (255,))
            d.text((TX + font(18, True).getlength(kicker) + 10, TY + 22), title, font=font(18), fill=INK + (255,))
        labels.append(png(tmp / f"step{i}.png", lab))

    playhead = tmp / "playhead.png"
    Image.new("RGBA", (3, TH + 10), INK + (255,)).save(playhead)

    # phone: trim each phase, speed it up, join
    parts = []
    for i, (a, b, speed, *_) in enumerate(PHASES):
        parts.append(f"[1:v]trim={a}:{b},setpts=(PTS-STARTPTS)/{speed},fps={FPS},scale={PW}:{PH}[p{i}]")
    phone = ";".join(parts) + ";" + "".join(f"[p{i}]" for i in range(len(PHASES))) + \
        f"concat=n={len(PHASES)}:v=1:a=0[phone];[phone][4:v]alphamerge[phonem]"

    # source: end to end until the trainee opens the guide, then the same step clips the phone loops
    # (pieces of (src start, src end, speed, step index or None))
    t_open = next(bounds[i][0] for i, ph in enumerate(PHASES) if ph[6] is not None)
    pieces = [(0.0, src_len, src_len / t_open, None)]
    for (lo, hi), (*_, step_i) in zip(bounds, PHASES):
        if step_i is None:
            continue
        a, b, _ = steps[step_i]
        speed, o = PHASES[[p[6] for p in PHASES].index(step_i)][2], lo
        while o < hi - 1e-3:
            d = min((b - a) / speed, hi - o)
            pieces.append((a, a + d * speed, speed, step_i))
            o += d
    starts, o = [], 0.0
    for a, b, speed, _ in pieces:
        starts.append(o)
        o += (b - a) / speed
    src = f"[2:v]split={len(pieces)}" + "".join(f"[s{i}]" for i in range(len(pieces))) + ";" + ";".join(
        f"[s{i}]trim={a}:{b},setpts=(PTS-STARTPTS)/{speed},fps={FPS},scale={VW}:{VH}[l{i}]"
        for i, (a, b, speed, _) in enumerate(pieces)) + ";" + "".join(f"[l{i}]" for i in range(len(pieces))) + \
        f"concat=n={len(pieces)}:v=1:a=0[src];[src][3:v]alphamerge[srcm]"

    inputs = ["-loop", "1", "-t", f"{total}", "-i", str(bg),
              "-i", str(SCREEN), "-i", str(SOURCE), "-loop", "1", "-i", str(vmask), "-loop", "1", "-i", str(pmask)]
    over = [str(p) for p in captions] + [str(empty), str(full)] + [str(p) for p in labels] + [str(playhead)]
    for p in over:
        inputs += ["-loop", "1", "-i", p]
    k = 5  # first overlay input index

    chain = [phone, src, f"[0:v]fps={FPS}[base]",
             f"[base][srcm]overlay={VX}:{VY}[v0]", f"[v0][phonem]overlay={PX}:{PY}[v1]"]
    cur, n = "v1", 2
    def add(idx: int, enable: str, x="0", y="0") -> None:
        nonlocal cur, n
        chain.append(f"[{cur}][{idx}:v]overlay=x={x}:y={y}:enable='{enable}'[v{n}]")
        cur, n = f"v{n}", n + 1
    for i, (a, b) in enumerate(bounds):
        add(k + i, f"between(t,{a:.3f},{b:.3f})")
    k += len(captions)
    add(k, f"lt(t,{built_at:.3f})")
    add(k + 1, f"gte(t,{built_at:.3f})")
    k += 2
    # step name: while the source plays through (once the guide exists), then per looping clip
    rate = pieces[0][2]
    shown: dict[int, list[tuple[float, float]]] = {i: [] for i in range(len(steps))}
    for i, (a, b, _) in enumerate(steps):
        lo, hi = max(a / rate, built_at), min(b / rate, t_open)
        if lo < hi:
            shown[i].append((lo, hi))
    for (a, b, speed, step_i), o in zip(pieces[1:], starts[1:]):
        shown[step_i].append((o, o + (b - a) / speed))
    for i in range(len(steps)):
        if shown[i]:
            add(k + i, "+".join(f"between(t,{lo:.3f},{hi:.3f})" for lo, hi in shown[i]))
    k += len(steps)
    for (a, b, speed, _), o in zip(pieces, starts):
        hi = o + (b - a) / speed
        add(k, f"between(t,{o:.3f},{hi:.3f})", x=f"{TX}+{TW / src_len:.5f}*({a}+(t-{o:.3f})*{speed:.5f})-1", y=f"{TY - 5}")
    chain.append(f"[{cur}]format=yuv420p[out]")

    hero = OUT / "hero.mp4"
    run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(chain), "-map", "[out]",
         "-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "slow", "-crf", "24", "-movflags", "+faststart",
         "-an", str(hero)])
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{bounds[-1][0] + 1.5:.2f}", "-i", str(hero), "-frames:v", "1",
         str(OUT / "hero_poster.png")])
    print(f"{hero} ({total:.1f} s, {hero.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
