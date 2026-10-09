"""Animate the menu bar ticker for the README: docs/images/ticker.gif.

Input is the App's offline preview of the synthetic README snapshot
(ticker-light.png / ticker-dark.png, 2x). Each strip loops through a 300pt
window with the same edge fade as the App, inside a light and a dark menu
bar. Needs Pillow (`python3 -m pip install pillow`).
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

root = Path(__file__).resolve().parents[1]
rendered = Path(sys.argv[1]) if len(sys.argv) > 1 else root / ".runtime/readme-demo/rendered"
output = root / "docs/images/ticker.gif"

SCALE = 2
WINDOW = 300 * SCALE      # widest ticker setting (滚动宽度 300)
GAP = 18 * SCALE          # gap between copies, as in MarqueeView
FADE = 8 * SCALE
SPEED = 72 * SCALE        # px per second; 3x the App's 24pt/s to keep the loop short
FPS = 15
BAR_H = 24 * SCALE
LEFT, RIGHT = 16 * SCALE, 150 * SCALE


def font(size):
    for path in ("/System/Library/Fonts/Hiragino Sans GB.ttc", "/System/Library/Fonts/STHeiti Medium.ttc"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def strip(mode):
    img = Image.open(rendered / f"ticker-{mode}.png").convert("RGB")
    background = img.getpixel((2, 2))
    # The preview pads the strip by 8pt on each side.
    content = img.crop((8 * SCALE, 0, img.width - 8 * SCALE, img.height))
    return content, background


def bar_frame(content, background, offset, mode):
    width = LEFT + WINDOW + RIGHT
    frame = Image.new("RGB", (width, BAR_H), background)
    cycle = content.width + GAP
    window = Image.new("RGB", (WINDOW, content.height), background)
    x = -offset
    while x < WINDOW:
        window.paste(content, (int(x), 0))
        x += cycle
    # Edge fade into the bar colour, like the App's gradient mask.
    mask = Image.new("L", (WINDOW, content.height), 255)
    draw = ImageDraw.Draw(mask)
    for i in range(FADE):
        level = int(255 * i / FADE)
        draw.line([(i, 0), (i, content.height)], fill=level)
        draw.line([(WINDOW - 1 - i, 0), (WINDOW - 1 - i, content.height)], fill=level)
    frame.paste(Image.composite(window, Image.new("RGB", window.size, background), mask),
                (LEFT, (BAR_H - content.height) // 2))
    # Generic status items to the right: wifi arcs, battery, clock.
    ink = (40, 40, 44) if mode == "light" else (236, 236, 240)
    d = ImageDraw.Draw(frame)
    x0 = LEFT + WINDOW + 14 * SCALE
    cy = BAR_H // 2
    for r in (9, 6, 3):
        d.arc([x0 + 9 * SCALE - r * SCALE, cy - r * SCALE + 3 * SCALE, x0 + 9 * SCALE + r * SCALE, cy + r * SCALE + 3 * SCALE],
              225, 315, fill=ink, width=SCALE + 1)
    bx = x0 + 26 * SCALE
    d.rounded_rectangle([bx, cy - 5 * SCALE, bx + 22 * SCALE, cy + 5 * SCALE], radius=3 * SCALE, outline=ink, width=SCALE)
    d.rectangle([bx + 2 * SCALE, cy - 3 * SCALE, bx + 16 * SCALE, cy + 3 * SCALE], fill=ink)
    d.rectangle([bx + 23 * SCALE, cy - 2 * SCALE, bx + 24 * SCALE, cy + 2 * SCALE], fill=ink)
    d.text((bx + 34 * SCALE, cy), "周五 16:20", font=font(13 * SCALE), fill=ink, anchor="lm")
    return frame


def main():
    bars = [strip("light"), strip("dark")]
    cycle = max(content.width for content, _ in bars) + GAP
    count = round(cycle / SPEED * FPS)
    frames = []
    for n in range(count):
        offset = cycle * n / count
        rows = [bar_frame(c, bg, offset * (c.width + GAP) / cycle, mode)
                for (c, bg), mode in zip(bars, ("light", "dark"))]
        sheet = Image.new("RGB", (rows[0].width, BAR_H * 2), (0, 0, 0))
        sheet.paste(rows[0], (0, 0))
        sheet.paste(rows[1], (0, BAR_H))
        frames.append(sheet.quantize(colors=64, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE))
    frames[0].save(output, save_all=True, append_images=frames[1:], duration=round(1000 / FPS), loop=0,
                   optimize=True, disposal=1)
    print(output, len(frames), "frames")


main()
