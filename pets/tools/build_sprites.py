#!/usr/bin/env python3
"""Draws the pixel-art preset `bit` (pets/presets/bit) with spritekit. Every frame is code, so the art is
reproducible and diff-able:  python3 pets/tools/build_sprites.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spritekit as sk  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "presets" / "bit"
N = 32
C = {"O": (31, 42, 68, 255), "B": (127, 209, 255, 255), "S": (74, 163, 224, 255), "L": (217, 243, 255, 255),
     "K": (255, 159, 184, 255), "W": (255, 255, 255, 255), "Y": (255, 208, 74, 255), "R": (255, 92, 108, 255),
     "G": (154, 163, 181, 255), "D": (59, 66, 86, 255), "Z": (169, 184, 255, 255), "T": (127, 214, 255, 255),
     "P": (255, 92, 138, 255), "M": (94, 234, 212, 255)}
GREY = {"B": (176, 180, 190, 255), "S": (130, 135, 148, 255), "L": (222, 224, 230, 255), "K": (190, 175, 180, 255)}


class Canvas:
    def __init__(self, grey=False):
        self.img = sk.new_image(N, N)
        self.pal = dict(C, **(GREY if grey else {}))

    def px(self, x, y, key):
        self.img.set(int(x), int(y), self.pal[key])

    def rect(self, x0, y0, x1, y1, key):
        for y in range(y0, y1):
            for x in range(x0, x1):
                self.px(x, y, key)

    def ellipse(self, cx, cy, rx, ry, key):
        for y in range(int(cy - ry) - 1, int(cy + ry) + 2):
            for x in range(int(cx - rx) - 1, int(cx + rx) + 2):
                if ((x + 0.5 - cx) / rx) ** 2 + ((y + 0.5 - cy) / ry) ** 2 <= 1:
                    self.px(x, y, key)

    def blob(self, cx, cy, rx, ry, fill):
        self.ellipse(cx, cy, rx + 1, ry + 1, "O")
        self.ellipse(cx, cy, rx, ry, fill)


def eyes(c, x_left, y, kind):
    for x in (x_left, x_left + 7):
        if kind == "open":
            c.rect(x, y, x + 2, y + 3, "O"); c.px(x, y, "W")
        elif kind == "big":
            c.rect(x, y - 1, x + 3, y + 3, "O"); c.px(x, y - 1, "W")
        elif kind == "happy":
            c.px(x, y + 1, "O"); c.px(x + 1, y, "O"); c.px(x + 2, y + 1, "O")
        elif kind == "closed":
            c.rect(x, y + 1, x + 3, y + 2, "O")
        elif kind == "x":
            for d in range(3):
                c.px(x + d, y + d, "O"); c.px(x + 2 - d, y + d, "O")
        elif kind == "down":
            c.rect(x, y + 1, x + 2, y + 3, "O")


def mouth(c, kind, x=16, y=21):
    if kind == "smile":
        c.px(x - 1, y, "O"); c.px(x, y + 1, "O"); c.px(x + 1, y, "O")
    elif kind == "open":
        c.rect(x - 1, y, x + 2, y + 2, "O"); c.px(x, y + 1, "R")
    elif kind == "flat":
        c.rect(x - 1, y + 1, x + 2, y + 2, "O")
    elif kind == "frown":
        c.px(x - 1, y + 1, "O"); c.px(x, y, "O"); c.px(x + 1, y + 1, "O")
    elif kind == "o":
        c.rect(x, y, x + 2, y + 2, "O")


def bit(bob=0, arms=("down", "down"), eye="open", mouth_kind="smile", grey=False, squash=0, dx=0, laptop=False, blush=True, antenna=0):
    c = Canvas(grey)
    cy = 19 + bob
    # feet, then body, so the body overlaps their tops
    for fx in (11, 18):
        c.rect(fx + dx, 26, fx + 4 + dx, 28, "O"); c.rect(fx + 1 + dx, 26, fx + 3 + dx, 27, "S")
    # arms
    for side, pose in zip((0, 1), arms):
        ax = 5 if side == 0 else 25
        ax += dx
        if pose == "down":
            c.rect(ax - 1, cy - 1, ax + 3, cy + 4, "O"); c.rect(ax, cy, ax + 2, cy + 3, "B")
        elif pose == "up":
            c.rect(ax - 1, cy - 8, ax + 3, cy - 2, "O"); c.rect(ax, cy - 7, ax + 2, cy - 3, "B")
        elif pose == "front":
            c.rect(ax - 1 + (2 if side == 0 else -2), cy + 3, ax + 3 + (2 if side == 0 else -2), cy + 7, "O")
            c.rect(ax + (2 if side == 0 else -2), cy + 4, ax + 2 + (2 if side == 0 else -2), cy + 6, "B")
        elif pose == "wave":
            c.rect(ax - 2, cy - 6, ax + 2, cy, "O"); c.rect(ax - 1, cy - 5, ax + 1, cy - 1, "B")
    c.blob(16 + dx, cy, 9.5, 8.5 - squash, "B")
    for y in range(N):
        for x in range(N):
            if c.img.get(x, y) == C["B"] and (x - 16 - dx) + (y - cy) > 9:
                c.px(x, y, "S")
    c.ellipse(16 + dx, cy + 3, 5, 3.5, "L")
    # antenna
    c.rect(16 + dx + antenna, cy - 12, 17 + dx + antenna, cy - 9, "O")
    c.rect(15 + dx + antenna, cy - 15, 18 + dx + antenna, cy - 12, "O"); c.rect(16 + dx + antenna, cy - 14, 17 + dx + antenna, cy - 13, "Y")
    eyes(c, 12 + dx, cy - 3, eye)
    mouth(c, mouth_kind, 16 + dx, cy + 1)
    if blush:
        c.rect(9 + dx, cy + 1, 11 + dx, cy + 2, "K"); c.rect(21 + dx, cy + 1, 23 + dx, cy + 2, "K")
    if laptop:
        c.rect(9, 23, 23, 29, "O"); c.rect(10, 24, 22, 28, "G"); c.rect(11, 24, 21, 27, "D")
        for i, x in enumerate((12, 14, 17, 19)):
            c.px(x, 25, "M" if i % 2 else "Y")
    return c


def fx(c, kind, t=0):
    if kind == "sweat":
        c.rect(24, 11 + t, 26, 14 + t, "T"); c.px(25, 10 + t, "T")
    elif kind == "exclaim":
        c.rect(26, 4, 28, 10, "R"); c.rect(26, 12, 28, 14, "R")
    elif kind == "zzz":
        for i, (x, y) in enumerate(((24, 8), (27, 4))[: 1 + t]):
            c.rect(x, y, x + 3, y + 1, "Z"); c.px(x + 2, y + 1, "Z"); c.px(x + 1, y + 2, "Z"); c.rect(x, y + 3, x + 3, y + 4, "Z")
    elif kind == "confetti":
        spots = [((4, 3), "Y"), ((27, 6), "P"), ((9, 9), "M"), ((23, 2), "Y"), ((3, 14), "P"), ((28, 12), "M"), ((14, 1), "P")]
        for i, ((x, y), k) in enumerate(spots):
            c.px(x, (y + t * 3 + i) % 18, k)
    elif kind == "question":
        c.rect(25, 5, 28, 6, "Z"); c.px(28, 6, "Z"); c.px(27, 7, "Z"); c.px(26, 8, "Z"); c.px(26, 10, "Z")
    return c


def frames():
    out = {}
    out["idle"] = [bit(0).img, bit(1, squash=0.5).img]
    out["working"] = [bit(0, ("front", "front"), "down", "flat", laptop=True).img,
                      bit(1, ("front", "front"), "down", "flat", laptop=True, antenna=1).img,
                      bit(0, ("front", "front"), "down", "flat", laptop=True).img,
                      bit(1, ("front", "front"), "down", "flat", laptop=True, antenna=-1).img]
    out["tired"] = [fx(bit(2, eye="down", mouth_kind="frown", squash=1), "sweat", 0).img, fx(bit(2, eye="down", mouth_kind="frown", squash=1.5), "sweat", 2).img]
    out["alarm"] = [fx(bit(0, ("up", "up"), "big", "o", dx=-1), "exclaim").img, fx(bit(0, ("up", "up"), "big", "o", dx=1), "exclaim").img]
    out["sleeping"] = [fx(bit(3, eye="closed", mouth_kind="flat", squash=1), "zzz", 0).img, fx(bit(4, eye="closed", mouth_kind="flat", squash=1.5), "zzz", 1).img]
    out["celebrate"] = [fx(bit(b, ("up", "up"), "happy", "open"), "confetti", t).img for t, b in enumerate((0, -4, -7, -3))]
    out["offline"] = [fx(bit(1, eye="x", mouth_kind="frown", grey=True, blush=False), "question").img, fx(bit(2, eye="x", mouth_kind="frown", grey=True, blush=False, squash=0.5), "question").img]
    out["waiting"] = [fx(bit(0, ("down", "wave"), "open", "smile"), "exclaim").img, bit(0, ("down", "up"), "open", "open").img]
    return out


def main():
    strips = frames()
    manifest = sk.write_pack(
        OUT, "bit", "比特", strips, N, pixelated=True, name_en="Bit",
        description="16 色像素宠物：手绘感的 32×32 精灵图，演示精灵图渲染器与生图流水线产物的形态（本包的帧由脚本绘制，不是模型生成）。",
        voice={"idle": ["滴滴～", "像素也有心事。", "戳我一下？"], "working": ["敲代码中，像素飞舞。"], "tired": ["像素……变暗了……"],
               "alarm": ["红色警报！！"], "celebrate": ["撒像素！", "满血复活！"], "sleeping": ["Zzz……"], "offline": ["信号丢失……"]},
        anchors={"head": {"x": 0.5, "y": 0.3}, "body": {"x": 0.5, "y": 0.62}, "prop": {"x": 0.7, "y": 0.8}})
    print("bit: %d states, frame %dpx -> %s" % (len(manifest["sprite"]["states"]), N, OUT))


if __name__ == "__main__":
    main()
