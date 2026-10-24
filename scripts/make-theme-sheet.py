"""Join the seven themed previews into docs/images/themes-{dark,light}.png (accounts)
and docs/images/forecast-themes-{dark,light}.png (Tibo resetter card).

Needs Pillow (`python3 -m pip install pillow`); input comes from the App's
offline preview of the synthetic README snapshot.
"""
import sys
from pathlib import Path

from PIL import Image

root = Path(__file__).resolve().parents[1]
rendered = Path(sys.argv[1]) if len(sys.argv) > 1 else root / ".runtime/readme-demo/rendered"
gap = 24
# (tab, output prefix, crop): header, cockpit, tabs and the first card.
# Minimal's underline tabs are shorter, so its forecast card starts higher.
sheets = [("accounts", "themes", (0, 1240)), ("forecast", "forecast-themes", (440, 680))]
shift = {"forecast": {"minimal": -30}}

for (tab, prefix, (top, height)), (mode, backdrop) in ((s, m) for s in sheets
                                                        for m in (("dark", (24, 24, 28)), ("light", (232, 232, 236)))):
    names = [f"{theme}-{tab}-{mode}" for theme in ("minimal", "native", "porcelain")]
    names += [f"{tab}-{mode}"]  # Aurora keeps the original unprefixed filenames.
    names += [f"{theme}-{tab}-{mode}" for theme in ("titanium", "neon", "prism")]
    panels = [Image.open(rendered / f"{n}.png").convert("RGB") for n in names]
    tops = [top + shift.get(tab, {}).get(n.split("-")[0], 0) for n in names]
    panels = [p.crop((0, t, p.width, min(t + height, p.height))) for p, t in zip(panels, tops)]
    sheet = Image.new("RGB", (sum(p.width for p in panels) + gap * (len(panels) - 1), height), backdrop)
    x = 0
    for p in panels:
        sheet.paste(p, (x, 0))
        x += p.width + gap
    sheet = sheet.resize((sheet.width // 2, sheet.height // 2), Image.LANCZOS)
    output = root / f"docs/images/{prefix}-{mode}.png"
    sheet.save(output, optimize=True)
    print(output)
