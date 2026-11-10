#!/usr/bin/env python3
"""Sprite post-processing for image-model avatars (stdlib only; Pillow/sips are used only to read non-PNG input).

Typical pipeline (see .claude/skills/agentmeter-pet-imagegen):

    spritekit.py key    raw/idle.png work/idle.png                 # flat key colour -> transparency
    spritekit.py slice  work/idle.png --frames 4 --out work/idle/  # one PNG per frame (grid or auto-detected gaps)
    spritekit.py build  work/strips/ --id my-pet --name 小宠 --frame 256 --out pets/presets/my-pet
    spritekit.py sheet  pets/presets/my-pet --out preview.png      # contact sheet without a browser

All image maths is done on RGBA bytearrays; it is slow on huge images, so keep sources at or below ~2048 px.
"""
import argparse
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_PIXELS = 4096 * 4096
DEFAULT_FPS = {"idle": 4, "working": 8, "busy": 10, "waiting": 4, "tired": 3, "alarm": 8, "exhausted": 2, "sleeping": 2,
               "celebrate": 8, "offline": 2, "painting": 6, "alert": 5, "focus": 4, "excited": 8, "confused": 3,
               "eating": 8, "startle": 8, "wave": 6, "poke": 10, "pet": 6, "drag": 6, "drop": 10, "refresh": 12, "photo": 4}
ONCE = {"drop", "poke", "startle", "photo", "refresh"}


class SpriteError(Exception):
    pass


class Image:
    """RGBA, 8 bits per channel, row-major."""

    def __init__(self, width, height, pixels=None):
        if width <= 0 or height <= 0 or width * height > MAX_PIXELS:
            raise SpriteError("unsupported image size %dx%d" % (width, height))
        self.width, self.height = width, height
        self.pixels = pixels if pixels is not None else bytearray(width * height * 4)
        if len(self.pixels) != width * height * 4:
            raise SpriteError("pixel buffer does not match %dx%d" % (width, height))

    def get(self, x, y):
        i = (y * self.width + x) * 4
        return tuple(self.pixels[i:i + 4])

    def set(self, x, y, rgba):
        if 0 <= x < self.width and 0 <= y < self.height:
            i = (y * self.width + x) * 4
            self.pixels[i:i + 4] = bytes(rgba)

    def copy(self):
        return Image(self.width, self.height, bytearray(self.pixels))


def new_image(width, height, rgba=(0, 0, 0, 0)):
    img = Image(width, height)
    if any(rgba):
        img.pixels[:] = bytes(rgba) * (width * height)
    return img


def parse_color(text):
    text = text.strip().lstrip("#")
    if len(text) != 6:
        raise SpriteError("colour must be #rrggbb, got %r" % text)
    return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))


# ----------------------------------------------------------------------------------------------- PNG

def _unfilter(data, width, height, bpp):
    stride = width * bpp
    out = bytearray(height * stride)
    pos = 0
    prev = bytearray(stride)
    for y in range(height):
        ft = data[pos]
        line = bytearray(data[pos + 1:pos + 1 + stride])
        pos += 1 + stride
        if len(line) != stride:
            raise SpriteError("truncated PNG data")
        if ft == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 255
        elif ft == 2:
            line = bytearray((a + b) & 255 for a, b in zip(line, prev))
        elif ft == 3:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 255
        elif ft == 4:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        elif ft != 0:
            raise SpriteError("bad PNG filter %d" % ft)
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return out


def png_size(data):
    """(width, height) from a PNG header without decoding; raises SpriteError for anything else."""
    if data[:8] != PNG_SIGNATURE or data[12:16] != b"IHDR":
        raise SpriteError("not a PNG file")
    return struct.unpack(">II", data[16:24])


def decode_png(data):
    if data[:8] != PNG_SIGNATURE:
        raise SpriteError("not a PNG file")
    pos, chunks = 8, []
    while pos + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        chunks.append((kind, data[pos + 8:pos + 8 + length]))
        pos += 12 + length
    header = next((c for k, c in chunks if k == b"IHDR"), None)
    if header is None:
        raise SpriteError("PNG has no header")
    width, height, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", header)
    if interlace:
        raise SpriteError("interlaced PNG is not supported; re-save it without interlacing")
    if depth not in (1, 2, 4, 8, 16) or ctype not in (0, 2, 3, 4, 6):
        raise SpriteError("unsupported PNG variant (depth %d, colour type %d)" % (depth, ctype))
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    bpp = max(1, channels * depth // 8)
    raw = zlib.decompress(b"".join(c for k, c in chunks if k == b"IDAT"))
    if depth < 8:
        stride = (width * depth + 7) // 8
        rows = _unfilter(raw, stride, height, 1)
        samples = bytearray()
        mask = (1 << depth) - 1
        for y in range(height):
            row = rows[y * stride:(y + 1) * stride]
            vals = []
            for byte in row:
                for shift in range(8 - depth, -1, -depth):
                    vals.append((byte >> shift) & mask)
            samples += bytes(vals[:width])
        scale = 255 // mask if ctype == 0 else 1
        samples = bytearray(v * scale for v in samples) if scale > 1 else samples
        data8, channels, bpp = samples, 1, 1
    else:
        data8 = _unfilter(raw, width, height, bpp)
        if depth == 16:
            data8 = bytearray(data8[0::2])
            bpp = channels
    palette = next((c for k, c in chunks if k == b"PLTE"), b"")
    trns = next((c for k, c in chunks if k == b"tRNS"), b"")
    img = Image(width, height)
    px = img.pixels
    n = width * height
    if ctype == 6:
        px[:] = data8[:n * 4]
    elif ctype == 2:
        for i in range(n):
            px[i * 4:i * 4 + 3] = data8[i * 3:i * 3 + 3]
            px[i * 4 + 3] = 255
        if len(trns) == 6 and depth == 8:
            key = (trns[1], trns[3], trns[5])
            for i in range(n):
                if tuple(px[i * 4:i * 4 + 3]) == key:
                    px[i * 4 + 3] = 0
    elif ctype == 0:
        for i in range(n):
            v = data8[i]
            px[i * 4:i * 4 + 4] = bytes((v, v, v, 255))
    elif ctype == 4:
        for i in range(n):
            v = data8[i * 2]
            px[i * 4:i * 4 + 4] = bytes((v, v, v, data8[i * 2 + 1]))
    else:
        for i in range(n):
            idx = data8[i]
            r, g, b = palette[idx * 3:idx * 3 + 3] or b"\0\0\0"
            px[i * 4:i * 4 + 4] = bytes((r, g, b, trns[idx] if idx < len(trns) else 255))
    return img


def encode_png(img):
    stride = img.width * 4
    raw = b"".join(b"\x00" + bytes(img.pixels[y * stride:(y + 1) * stride]) for y in range(img.height))

    def chunk(kind, payload):
        body = kind + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    return (PNG_SIGNATURE + chunk(b"IHDR", struct.pack(">IIBBBBB", img.width, img.height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def write_png(img, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encode_png(img))


def load(path):
    """PNG natively; other formats through Pillow when installed, else macOS sips."""
    data = Path(path).read_bytes()
    if data[:8] == PNG_SIGNATURE:
        return decode_png(data)
    try:
        from PIL import Image as PILImage
        with PILImage.open(path) as source:
            rgba = source.convert("RGBA")
            return Image(rgba.width, rgba.height, bytearray(rgba.tobytes()))
    except ImportError:
        pass
    if shutil.which("sips"):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "converted.png"
            subprocess.run(["sips", "-s", "format", "png", str(path), "--out", str(out)], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return decode_png(out.read_bytes())
    raise SpriteError("cannot read %s: install Pillow or convert it to PNG first" % path)


# ----------------------------------------------------------------------------------------- operations

def auto_key_color(img):
    """The most common colour among the four corner regions (image models paint the key colour there)."""
    counts = {}
    for cx, cy in ((0, 0), (img.width - 4, 0), (0, img.height - 4), (img.width - 4, img.height - 4)):
        for dy in range(4):
            for dx in range(4):
                r, g, b, a = img.get(max(0, cx + dx), max(0, cy + dy))
                if a > 200:
                    counts[(r // 8 * 8, g // 8 * 8, b // 8 * 8)] = counts.get((r // 8 * 8, g // 8 * 8, b // 8 * 8), 0) + 1
    if not counts:
        raise SpriteError("corners are already transparent; nothing to key")
    r, g, b = max(counts, key=counts.get)
    return (r + 4, g + 4, b + 4)


def chroma_key(img, key=None, tolerance=70, feather=50, despill=True):
    """Makes the key colour transparent. Pixels within `tolerance` go fully clear, then alpha ramps up over `feather`."""
    key = key or auto_key_color(img)
    kr, kg, kb = key
    out = img.copy()
    px = out.pixels
    tol2 = tolerance * tolerance
    far = (tolerance + feather) ** 2
    for i in range(0, len(px), 4):
        r, g, b = px[i], px[i + 1], px[i + 2]
        d2 = (r - kr) ** 2 + (g - kg) ** 2 + (b - kb) ** 2
        if d2 <= tol2:
            px[i + 3] = 0
        elif d2 < far:
            k = (d2 ** 0.5 - tolerance) / feather
            px[i + 3] = int(px[i + 3] * k)
            if despill:
                if kg > kr and kg > kb and g > (r + b) // 2:
                    px[i + 1] = (r + b) // 2
                elif kb > kr and kb > kg and b > (r + g) // 2:
                    px[i + 2] = (r + g) // 2
    return out


def bbox(img, threshold=8):
    """(x0, y0, x1, y1) of pixels with alpha above threshold, or None when the image is empty."""
    w, h, px = img.width, img.height, img.pixels
    x0, y0, x1, y1 = w, h, -1, -1
    for y in range(h):
        row = px[y * w * 4 + 3:(y + 1) * w * 4:4]
        if max(row) > threshold:
            if y < y0:
                y0 = y
            y1 = y
            xs = [i for i, a in enumerate(row) if a > threshold]
            x0, x1 = min(x0, xs[0]), max(x1, xs[-1])
    return None if x1 < 0 else (x0, y0, x1 + 1, y1 + 1)


def crop(img, x0, y0, x1, y1):
    out = Image(x1 - x0, y1 - y0)
    for y in range(y0, y1):
        src = (y * img.width + x0) * 4
        dst = (y - y0) * out.width * 4
        out.pixels[dst:dst + out.width * 4] = img.pixels[src:src + out.width * 4]
    return out


def trim(img, threshold=8):
    box = bbox(img, threshold)
    if box is None:
        raise SpriteError("frame is empty after keying; lower the tolerance or check the key colour")
    return crop(img, *box)


def paste(dst, src, x, y):
    """Alpha-composites src onto dst at (x, y)."""
    for sy in range(src.height):
        dy = y + sy
        if not 0 <= dy < dst.height:
            continue
        for sx in range(src.width):
            dx = x + sx
            if not 0 <= dx < dst.width:
                continue
            si, di = (sy * src.width + sx) * 4, (dy * dst.width + dx) * 4
            a = src.pixels[si + 3]
            if a == 0:
                continue
            if a == 255 or dst.pixels[di + 3] == 0:
                dst.pixels[di:di + 4] = src.pixels[si:si + 4]
                continue
            da = dst.pixels[di + 3]
            oa = a + da * (255 - a) // 255
            for c in range(3):
                dst.pixels[di + c] = (src.pixels[si + c] * a + dst.pixels[di + c] * da * (255 - a) // 255) // max(oa, 1)
            dst.pixels[di + 3] = oa


def resize(img, width, height, smooth=True):
    """Nearest (pixel art) or bilinear with premultiplied alpha (illustrations)."""
    width, height = max(1, int(round(width))), max(1, int(round(height)))
    if (width, height) == (img.width, img.height):
        return img.copy()
    out = Image(width, height)
    sx, sy = img.width / width, img.height / height
    for y in range(height):
        fy = (y + 0.5) * sy - 0.5
        y0 = max(0, min(img.height - 1, int(fy // 1)))
        y1 = min(img.height - 1, y0 + 1)
        ty = fy - y0 if smooth else 0
        for x in range(width):
            fx = (x + 0.5) * sx - 0.5
            x0 = max(0, min(img.width - 1, int(fx // 1)))
            if not smooth:
                i = (min(img.height - 1, int((y + 0.5) * sy)) * img.width + min(img.width - 1, int((x + 0.5) * sx))) * 4
                out.pixels[(y * width + x) * 4:(y * width + x) * 4 + 4] = img.pixels[i:i + 4]
                continue
            x1 = min(img.width - 1, x0 + 1)
            tx = min(1.0, max(0.0, fx - x0))
            ty2 = min(1.0, max(0.0, ty))
            acc = [0.0, 0.0, 0.0, 0.0]
            for (xx, yy, wgt) in ((x0, y0, (1 - tx) * (1 - ty2)), (x1, y0, tx * (1 - ty2)), (x0, y1, (1 - tx) * ty2), (x1, y1, tx * ty2)):
                i = (yy * img.width + xx) * 4
                a = img.pixels[i + 3] * wgt
                acc[0] += img.pixels[i] * a
                acc[1] += img.pixels[i + 1] * a
                acc[2] += img.pixels[i + 2] * a
                acc[3] += a
            o = (y * width + x) * 4
            if acc[3] > 0:
                out.pixels[o:o + 3] = bytes(min(255, int(c / acc[3])) for c in acc[:3])
                out.pixels[o + 3] = min(255, int(acc[3]))
    return out


def slice_grid(img, cols, rows=1):
    cw, ch = img.width // cols, img.height // rows
    if cw < 1 or ch < 1:
        raise SpriteError("image is too small for a %dx%d grid" % (cols, rows))
    return [crop(img, c * cw, r * ch, (c + 1) * cw, (r + 1) * ch) for r in range(rows) for c in range(cols)]


def slice_auto(img, expected=None, threshold=8, min_gap=3):
    """Splits a strip on empty columns. With `expected`, widens the gap until exactly that many frames remain."""
    w, h, px = img.width, img.height, img.pixels
    filled = [max(px[y * w * 4 + x * 4 + 3] for y in range(h)) > threshold for x in range(w)]

    def runs(gap):
        out, start, empty = [], None, 0
        for x, on in enumerate(filled + [False] * (gap + 1)):
            if on:
                if start is None:
                    start = x
                empty = 0
            elif start is not None:
                empty += 1
                if empty >= gap:
                    out.append((start, x - empty + 1))
                    start, empty = None, 0
        return out

    found = runs(min_gap)
    if expected:
        gap = min_gap
        while len(found) > expected and gap < w // 2:
            gap += 1
            found = runs(gap)
        if len(found) != expected:
            raise SpriteError("found %d frames, expected %d; try --grid or check the strip spacing" % (len(found), expected))
    if not found:
        raise SpriteError("no frames found in strip")
    return [crop(img, x0, 0, x1, h) for x0, x1 in found]


def align(frames_by_state, cell, margin=None, smooth=True):
    """Trims every frame, scales them all by ONE factor (the same character size everywhere) and stands them on a common baseline."""
    margin = max(2, cell // 40) if margin is None else margin
    trimmed = {s: [trim(f) for f in fs] for s, fs in frames_by_state.items()}
    tallest = max(f.height for fs in trimmed.values() for f in fs)
    widest = max(f.width for fs in trimmed.values() for f in fs)
    k = min((cell - 2 * margin) / tallest, (cell - 2 * margin) / widest)
    out = {}
    for state, fs in trimmed.items():
        cells = []
        for f in fs:
            g = resize(f, f.width * k, f.height * k, smooth)
            tile = Image(cell, cell)
            paste(tile, g, (cell - g.width) // 2, cell - margin - g.height)
            cells.append(tile)
        out[state] = cells
    return out, k


def make_strip(frames, cols=None):
    cols = cols or len(frames)
    rows = (len(frames) + cols - 1) // cols
    w, h = frames[0].width, frames[0].height
    sheet = Image(w * cols, h * rows)
    for i, f in enumerate(frames):
        paste(sheet, f, (i % cols) * w, (i // cols) * h)
    return sheet


def montage(rows, cell=96, pad=6, background=(244, 244, 248, 255)):
    """rows: list of lists of frames -> one image (a pure-Python contact sheet)."""
    cols = max(len(r) for r in rows)
    sheet = new_image(cols * (cell + pad) + pad, len(rows) * (cell + pad) + pad, background)
    for ry, frames in enumerate(rows):
        for cx, f in enumerate(frames):
            small = resize(f, cell, cell * f.height / f.width, smooth=f.width > cell) if f.width != cell else f
            tile = new_image(cell, cell, (255, 255, 255, 255))
            paste(tile, small, 0, cell - small.height)
            paste(sheet, tile, pad + cx * (cell + pad), pad + ry * (cell + pad))
    return sheet


# --------------------------------------------------------------------------------------------- packs

def sprite_manifest(id, name, frame, states, pixelated=False, name_en=None, description="", voice=None, anchors=None):
    return {
        "format": "agentmeter-pet/1", "id": id, "name": name, "name_en": name_en or id, "version": "1.0.0",
        "author": "you", "license": "CC0-1.0", "description": description or name, "renderer": "sprite",
        "stage": {"width": 240, "height": 260, "ground": 0.93},
        "sprite": {"frame": {"width": frame, "height": frame}, "pivot": {"x": 0.5, "y": 1.0}, "pixelated": pixelated, "motion": True,
                   "anchors": anchors or {"head": {"x": 0.5, "y": 0.22}, "body": {"x": 0.5, "y": 0.6}, "prop": {"x": 0.82, "y": 0.62}},
                   "states": states},
        "voice": voice or {},
    }


def write_pack(out_dir, id, name, strips, frame, pixelated=False, **kw):
    """strips: {state: [Image, ...]} already at frame x frame. Writes sprites/<state>.png and pet.json."""
    out = Path(out_dir)
    states = {}
    for state, frames in strips.items():
        if any((f.width, f.height) != (frame, frame) for f in frames):
            raise SpriteError("%s: every frame must be %dx%d" % (state, frame, frame))
        write_png(make_strip(frames), out / "sprites" / ("%s.png" % state))
        entry = {"image": "sprites/%s.png" % state, "frames": len(frames), "fps": DEFAULT_FPS.get(state, 6)}
        if state in ONCE:
            entry["loop"] = False
        states[state] = entry
    manifest = sprite_manifest(id, name, frame, states, pixelated, **kw)
    (out / "pet.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n")
    return manifest


def read_pack_frames(pack_dir):
    pack = Path(pack_dir)
    manifest = json.loads((pack / "pet.json").read_text())
    f = manifest["sprite"]["frame"]
    rows = []
    for state, entry in manifest["sprite"]["states"].items():
        sheet = load(pack / entry["image"])
        cols = entry.get("cols") or entry["frames"]
        rows.append((state, [crop(sheet, (i % cols) * f["width"], (i // cols) * f["height"], (i % cols + 1) * f["width"],
                                  (i // cols + 1) * f["height"]) for i in range(entry["frames"])]))
    return manifest, rows


# -------------------------------------------------------------------------------------------------- CLI

def cmd_key(args):
    img = load(args.input)
    key = parse_color(args.color) if args.color != "auto" else None
    out = chroma_key(img, key, args.tolerance, args.feather, not args.no_despill)
    write_png(out, args.output)
    print("keyed %s with %s -> %s" % (args.input, "auto" if key is None else args.color, args.output))


def cmd_slice(args):
    img = load(args.input)
    frames = slice_grid(img, args.cols, args.rows) if args.cols else slice_auto(img, args.frames, min_gap=args.min_gap)
    for i, f in enumerate(frames):
        write_png(f, Path(args.out) / ("%02d.png" % i))
    print("%d frames -> %s" % (len(frames), args.out))


def cmd_build(args):
    src = Path(args.strips)
    by_state = {}
    for item in sorted(src.iterdir()):
        if item.is_dir():
            by_state[item.name] = [load(p) for p in sorted(item.glob("*.png"))]
        elif item.suffix == ".png":
            by_state[item.stem] = slice_auto(load(item))
    if not by_state:
        raise SpriteError("no strips or frame folders in %s" % src)
    aligned, k = align(by_state, args.frame, smooth=not args.pixelated)
    manifest = write_pack(args.out, args.id, args.name, aligned, args.frame, args.pixelated)
    print("built %s: %d states, scale %.3f -> %s" % (args.id, len(manifest["sprite"]["states"]), k, args.out))


def cmd_sheet(args):
    manifest, rows = read_pack_frames(args.pack)
    write_png(montage([f for _, f in rows], args.cell), args.out)
    print("%d states -> %s  (%s)" % (len(rows), args.out, ", ".join(s for s, _ in rows)))


def cmd_info(args):
    img = load(args.input)
    box = bbox(img)
    print("%dx%d  opaque bbox %s  corner colour %s" % (img.width, img.height, box, img.get(0, 0)))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("key", help="remove a flat background colour")
    k.add_argument("input"); k.add_argument("output")
    k.add_argument("--color", default="auto", help="#rrggbb or auto (corner colour)")
    k.add_argument("--tolerance", type=int, default=70); k.add_argument("--feather", type=int, default=50)
    k.add_argument("--no-despill", action="store_true")
    k.set_defaults(run=cmd_key)
    s = sub.add_parser("slice", help="cut a strip into frames")
    s.add_argument("input"); s.add_argument("--out", required=True)
    s.add_argument("--frames", type=int, help="expected frame count (auto-detect gaps)")
    s.add_argument("--cols", type=int, help="regular grid columns instead of gap detection"); s.add_argument("--rows", type=int, default=1)
    s.add_argument("--min-gap", type=int, default=3)
    s.set_defaults(run=cmd_slice)
    b = sub.add_parser("build", help="align strips/frame folders and write a sprite pack")
    b.add_argument("strips", help="folder with <state>.png strips or <state>/ frame folders")
    b.add_argument("--id", required=True); b.add_argument("--name", required=True)
    b.add_argument("--frame", type=int, default=256); b.add_argument("--out", required=True)
    b.add_argument("--pixelated", action="store_true")
    b.set_defaults(run=cmd_build)
    c = sub.add_parser("sheet", help="contact sheet PNG of a sprite pack")
    c.add_argument("pack"); c.add_argument("--out", default="sheet.png"); c.add_argument("--cell", type=int, default=96)
    c.set_defaults(run=cmd_sheet)
    i = sub.add_parser("info", help="size, opaque bounds and corner colour of an image")
    i.add_argument("input")
    i.set_defaults(run=cmd_info)
    args = p.parse_args(argv)
    try:
        args.run(args)
    except SpriteError as error:
        raise SystemExit("error: %s" % error)


if __name__ == "__main__":
    main()
