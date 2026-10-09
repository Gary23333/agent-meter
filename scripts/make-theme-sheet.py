"""Join the four themed account previews into docs/images/themes-dark.png.

Needs Pillow (`python3 -m pip install pillow`); input comes from the App's
offline preview of the synthetic README snapshot.
"""
import sys
from pathlib import Path

from PIL import Image

root = Path(__file__).resolve().parents[1]
rendered = Path(sys.argv[1]) if len(sys.argv) > 1 else root / ".runtime/readme-demo/rendered"
output = root / "docs/images/themes-dark.png"
names = ["minimal-accounts-dark", "native-accounts-dark", "accounts-dark", "neon-accounts-dark"]
height = 1240  # header, cockpit, tabs and the first account card
gap = 24

panels = [Image.open(rendered / f"{n}.png").convert("RGB") for n in names]
panels = [p.crop((0, 0, p.width, min(height, p.height))) for p in panels]
sheet = Image.new("RGB", (sum(p.width for p in panels) + gap * (len(panels) - 1), height), (24, 24, 28))
x = 0
for p in panels:
    sheet.paste(p, (x, 0))
    x += p.width + gap
sheet = sheet.resize((sheet.width // 2, sheet.height // 2), Image.LANCZOS)
sheet.save(output, optimize=True)
print(output)
