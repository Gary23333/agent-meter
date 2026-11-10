#!/usr/bin/env python3
"""Pet pack tooling (stdlib only): validate, scaffold, install, pack, list.

    petpack.py validate pets/presets/gauge          # or a pack id, or several
    petpack.py new my-pet --from gauge --name 小宠   # fork a preset as a starting point
    petpack.py pack pets/presets/my-pet             # -> my-pet-0.1.0.agentpet (deterministic zip)
    petpack.py install pets/presets/my-pet          # -> ~/Library/Application Support/AgentMeter/pets/my-pet
    petpack.py install my-pet-0.1.0.agentpet
    petpack.py list

A pack is data only: pet.json, avatar.json / sprite PNGs, and docs. Scripts, SVG and symlinks are refused,
so installing a pack never runs code. The format is documented in pets/SPEC.md.
"""
import argparse
import json
import re
import shutil
import stat
import struct
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PETS = HERE.parent
PRESETS = PETS / "presets"
USER_DIR = Path.home() / "Library/Application Support/AgentMeter/pets"

FORMAT = "agentmeter-pet/1"
AVATAR_FORMAT = "agentmeter-avatar/1"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,30}$")
NODE_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,40}$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

# Canonical vocabulary: keep in sync with pets/runtime/js/constants.js (tests compare them).
BASE_STATES = ("offline", "exhausted", "alarm", "waiting", "busy", "working", "painting", "tired", "alert", "focus",
               "excited", "confused", "sleeping", "idle")
REACTIONS = ("celebrate", "eating", "startle", "wave", "painting")
INTERACTIONS = ("poke", "pet", "drag", "drop", "refresh", "photo")
ANIMATIONS = tuple(dict.fromkeys(BASE_STATES + REACTIONS + INTERACTIONS))
REQUIRED_STATES = ("idle", "working", "tired", "alarm", "sleeping", "celebrate", "offline", "waiting")
FALLBACKS = {
    "busy": ["working"], "painting": ["working"], "exhausted": ["tired"], "alarm": ["tired"], "alert": ["waiting"],
    "focus": ["working"], "excited": ["celebrate"], "confused": ["idle"], "eating": ["working"], "startle": ["alarm"],
    "wave": ["celebrate"], "poke": ["wave"], "pet": ["celebrate"], "drag": ["startle"], "drop": ["idle"],
    "refresh": ["working"], "photo": ["celebrate"], "tired": ["idle"], "waiting": ["idle"], "working": ["idle"],
    "celebrate": ["idle"], "sleeping": ["idle"], "offline": ["idle"]}
EXPRESSIONS = ("neutral", "happy", "excited", "determined", "worried", "sad", "sleepy", "surprised", "confused", "dizzy",
               "yawn", "love")
SLOTS = ("root", "body", "head", "armL", "armR", "legL", "legR", "tail", "earL", "earR", "antenna", "mouth", "gauge",
         "prop", "shadow")
NODE_TYPES = ("group", "sphere", "capsule", "box", "cylinder", "cone", "torus", "disc", "ring", "plane", "lathe", "tube",
              "extrude", "arc", "screen")
MATERIAL_KINDS = ("toon", "standard", "basic", "lambert")
PROPS = ("laptop", "brush", "sign", "plug", "headphones", "crystal", "fish", "resetter")
LIGHTS = ("soft", "studio", "neon")
OVERRIDE_KEYS = {"pose", "channels", "drop", "expression", "show", "fx", "fps", "dur", "look", "lock", "desaturate", "scale"}
FX_KINDS = ("zzz", "hearts", "sparkles", "confetti", "sweat", "question", "exclaim", "notes", "coins", "stars", "steam",
            "bolt", "paint", "dust", "flash")
CHANNEL_KINDS = ("sine", "abs", "saw", "pulse", "noise", "squash", "once")
THEME_TOKENS = ("accent1", "accent2", "ink", "ok", "low", "crit", "paper", "unknown")
ALLOWED_SUFFIXES = {".json", ".png", ".webp", ".jpg", ".jpeg", ".md", ".txt"}
ALLOWED_BARE = {"LICENSE", "README"}
MAX_NODES = 400
MAX_PACK_BYTES = 12 * 1024 * 1024
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_IMAGE_SIDE = 4096
MAX_FRAMES = 64


def resolve_animation(name, has):
    seen, queue = set(), [name]
    while queue:
        item = queue.pop(0)
        if item in seen:
            continue
        seen.add(item)
        if has(item):
            return item
        queue.extend(FALLBACKS.get(item, []))
    return "idle"


class Report:
    def __init__(self, path):
        self.path = Path(path)
        self.errors, self.warnings, self.notes = [], [], []

    def error(self, message):
        self.errors.append(message)

    def warn(self, message):
        self.warnings.append(message)

    def note(self, message):
        self.notes.append(message)

    @property
    def ok(self):
        return not self.errors

    def as_dict(self):
        return {"path": str(self.path), "ok": self.ok, "errors": self.errors, "warnings": self.warnings, "notes": self.notes}


def _num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _vec(value, n, lo, hi):
    return isinstance(value, list) and len(value) == n and all(_num(v) and lo <= v <= hi for v in value)


# -------------------------------------------------------------------------------------------- files

def check_files(root, report):
    total = 0
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if path.name == ".DS_Store" or "__pycache__" in rel.parts:
            continue
        if path.is_symlink():
            report.error("%s: symbolic links are not allowed" % rel)
            continue
        if path.is_dir():
            continue
        if any(part.startswith(".") for part in rel.parts):
            report.error("%s: hidden files are not allowed" % rel)
            continue
        if path.suffix.lower() not in ALLOWED_SUFFIXES and path.name not in ALLOWED_BARE:
            kind = "scripts and markup are" if path.suffix.lower() in (".js", ".mjs", ".html", ".svg", ".css", ".wasm") else "this file type is"
            report.error("%s: %s not allowed in a pack (data and images only)" % (rel, kind))
            continue
        size = path.stat().st_size
        total += size
        if size > MAX_FILE_BYTES:
            report.error("%s: %.1f MB exceeds the %d MB per-file limit" % (rel, size / 1048576, MAX_FILE_BYTES // 1048576))
    if total > MAX_PACK_BYTES:
        report.error("pack is %.1f MB, limit is %d MB" % (total / 1048576, MAX_PACK_BYTES // 1048576))
    report.note("%.0f KB on disk" % (total / 1024))


def read_json(path, report, label):
    try:
        data = json.loads(path.read_text())
    except OSError:
        report.error("%s is missing" % label)
        return None
    except ValueError as error:
        report.error("%s is not valid JSON: %s" % (label, error))
        return None
    if not isinstance(data, dict):
        report.error("%s must be a JSON object" % label)
        return None
    return data


# ---------------------------------------------------------------------------------------- manifest

def check_manifest(m, root, report):
    if m.get("format") != FORMAT:
        report.error('pet.json: "format" must be "%s"' % FORMAT)
    pid = m.get("id")
    if not isinstance(pid, str) or not ID_RE.match(pid):
        report.error('pet.json: "id" must match %s' % ID_RE.pattern)
    elif pid != root.name:
        report.error('pet.json: id "%s" must equal the folder name "%s"' % (pid, root.name))
    name = m.get("name")
    if not isinstance(name, str) or not 1 <= len(name) <= 24:
        report.error('pet.json: "name" must be 1-24 characters')
    if not isinstance(m.get("version"), str) or not SEMVER_RE.match(m["version"]):
        report.error('pet.json: "version" must look like 1.0.0')
    for key in ("author", "license"):
        if not isinstance(m.get(key), str) or not m[key]:
            report.error('pet.json: "%s" is required' % key)
    description = m.get("description", "")
    if not isinstance(description, str) or len(description) > 300:
        report.error('pet.json: "description" must be text of at most 300 characters')
    if m.get("renderer") not in ("three", "sprite"):
        report.error('pet.json: "renderer" must be "three" or "sprite"')
    stage = m.get("stage", {})
    if not isinstance(stage, dict) or not (stage.get("width", 240) in range(120, 481) and stage.get("height", 260) in range(120, 521)):
        report.error("pet.json: stage width must be 120-480 and height 120-520")
    elif "ground" in stage and not (_num(stage["ground"]) and 0 <= stage["ground"] <= 1):
        report.error("pet.json: stage.ground must be between 0 and 1")
    voice = m.get("voice", {})
    if not isinstance(voice, dict):
        report.error('pet.json: "voice" must be an object of state -> lines')
    else:
        for state, lines in voice.items():
            if state not in ANIMATIONS:
                report.warn('pet.json: voice for unknown state "%s" is never used' % state)
            if not isinstance(lines, list) or not lines or len(lines) > 8 or not all(isinstance(x, str) and 0 < len(x) <= 60 for x in lines):
                report.error('pet.json: voice["%s"] must be 1-8 lines of at most 60 characters' % state)
    return m.get("renderer")


# ------------------------------------------------------------------------------------------ avatar

def check_color(value, palette, where, report, depth=0):
    if value is None:
        return
    if not isinstance(value, str):
        report.error("%s: colour must be text" % where)
    elif value.startswith("#"):
        if not HEX_RE.match(value):
            report.error("%s: %r is not #rrggbb" % (where, value))
    elif value.startswith("$"):
        if value[1:] not in THEME_TOKENS:
            report.error("%s: unknown theme token %s (use %s)" % (where, value, ", ".join("$" + t for t in THEME_TOKENS)))
    elif value in palette:
        if depth > 6:
            report.error("%s: palette reference loops at %r" % (where, value))
        else:
            check_color(palette[value], palette, where, report, depth + 1)
    else:
        report.error("%s: %r is not a colour, theme token or palette name" % (where, value))


def check_node(n, index, ids, materials, report):
    where = "avatar node #%d" % index
    nid = n.get("id")
    if not isinstance(nid, str) or not NODE_ID_RE.match(nid):
        report.error("%s: id must match %s" % (where, NODE_ID_RE.pattern))
        return None
    where = "node %s" % nid
    if nid in ids:
        report.error("%s: duplicate id" % where)
    if n.get("type") not in NODE_TYPES:
        report.error("%s: unknown type %r" % (where, n.get("type")))
        return nid
    parent = n.get("parent")
    if parent is not None and parent not in ids:
        report.error("%s: parent %r must be defined earlier in the list" % (where, parent))
    if "position" in n and not _vec(n["position"], 3, -10, 10):
        report.error("%s: position must be three numbers within ±10" % where)
    if "rotation" in n and not _vec(n["rotation"], 3, -720, 720):
        report.error("%s: rotation is three angles in degrees" % where)
    scale = n.get("scale")
    if scale is not None and not (_num(scale) and 0 < abs(scale) <= 10 or (_vec(scale, 3, -10, 10) and all(s != 0 for s in scale))):
        report.error("%s: scale must be a non-zero number or three of them" % where)
    material = n.get("material")
    if material is not None and material not in materials:
        report.error("%s: unknown material %r" % (where, material))
    if n["type"] != "group" and material is None:
        report.warn("%s: no material (it will render magenta)" % where)
    for key in ("radius", "tube", "radiusTop", "radiusBottom", "height", "length", "outer", "inner", "size", "round", "depth", "bevel"):
        value = n.get(key)
        if value is None:
            continue
        if _num(value):
            if not (0 <= value <= 5):
                report.error("%s: %s must be between 0 and 5" % (where, key))
        elif not (isinstance(value, list) and 1 <= len(value) <= 3 and all(_num(v) and 0 < v <= 5 for v in value)):
            report.error("%s: %s must be a number or a list of up to three" % (where, key))
    segments = n.get("segments")
    if segments is not None and not (isinstance(segments, list) and 1 <= len(segments) <= 2 and all(isinstance(s, int) and 3 <= s <= 128 for s in segments)):
        report.error("%s: segments must be one or two integers from 3 to 128" % where)
    for key in ("points", "path"):
        if key in n and not (isinstance(n[key], list) and 2 <= len(n[key]) <= 64):
            report.error("%s: %s needs 2-64 points" % (where, key))
    if n["type"] == "extrude":
        shape = n.get("shape", "star")
        if not (shape in ("star", "heart", "drop", "bolt") or (isinstance(shape, dict) and shape.get("kind", "star") in ("star", "heart", "drop", "bolt")
                                                                or isinstance(shape, dict) and isinstance(shape.get("points"), list))):
            report.error("%s: shape must be star, heart, drop, bolt or {points: [[x, y], ...]}" % where)
    return nid


def check_avatar(path, m, report):
    a = read_json(path, report, "avatar file %s" % path.name)
    if a is None:
        return
    if a.get("format") != AVATAR_FORMAT:
        report.error('avatar: "format" must be "%s"' % AVATAR_FORMAT)
    palette = a.get("palette", {})
    if not isinstance(palette, dict):
        report.error("avatar: palette must be an object")
        palette = {}
    for key, value in palette.items():
        check_color(value, palette, "palette.%s" % key, report)
    materials = a.get("materials", {})
    if not isinstance(materials, dict) or not materials:
        report.error("avatar: materials must be a non-empty object")
        materials = {}
    for name, d in materials.items():
        if not isinstance(d, dict) or d.get("kind", "toon") not in MATERIAL_KINDS:
            report.error("material %s: kind must be one of %s" % (name, ", ".join(MATERIAL_KINDS)))
            continue
        check_color(d.get("color"), palette, "material %s.color" % name, report)
        check_color(d.get("emissive"), palette, "material %s.emissive" % name, report)
        if "opacity" in d and not (_num(d["opacity"]) and 0 <= d["opacity"] <= 1):
            report.error("material %s: opacity is 0..1" % name)
    nodes = a.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        report.error("avatar: nodes must be a non-empty list")
        return
    if len(nodes) > MAX_NODES:
        report.error("avatar: %d nodes exceeds the limit of %d" % (len(nodes), MAX_NODES))
    ids = {}
    for index, n in enumerate(nodes[:MAX_NODES]):
        if not isinstance(n, dict):
            report.error("avatar node #%d must be an object" % index)
            continue
        nid = check_node(n, index, ids, materials, report)
        if nid:
            ids[nid] = n
    outline = a.get("outline")
    if outline:
        check_color(outline.get("color"), palette, "outline.color", report)
    slots = a.get("slots", {})
    if not isinstance(slots, dict):
        report.error("avatar: slots must be an object")
        slots = {}
    for slot, node in slots.items():
        if slot not in SLOTS:
            report.error("slot %r is unknown (allowed: %s)" % (slot, ", ".join(SLOTS)))
        elif node not in ids:
            report.error("slot %s points at unknown node %r" % (slot, node))
    for needed in ("root", "head"):
        if needed not in slots:
            report.warn("slot %s is not mapped; motions aimed at it are ignored" % needed)
    if "body" not in slots:
        report.warn("slot body is not mapped; squash and breathing are ignored")
    face = a.get("face", {})
    expressions = face.get("expressions", {}) if isinstance(face, dict) else {}
    if "neutral" not in expressions:
        report.error('face.expressions needs at least "neutral"')
    for name, e in expressions.items():
        if name not in EXPRESSIONS:
            report.error("expression %r is unknown (allowed: %s)" % (name, ", ".join(EXPRESSIONS)))
        for ref in (e or {}).get("show", []):
            if ref not in ids:
                report.error("expression %s shows unknown node %r" % (name, ref))
    for ref in face.get("blink", []) + [l.get("node") for l in face.get("look", []) if isinstance(l, dict)] + face.get("managed", []):
        if ref not in ids:
            report.error("face refers to unknown node %r" % ref)
    missing = [e for e in EXPRESSIONS if e not in expressions]
    if missing:
        report.note("expressions falling back: %s" % ", ".join(missing))
    meter = a.get("meter")
    if meter:
        node = ids.get(meter.get("node"))
        if node is None or node.get("type") != "arc":
            report.error("meter.node must be an existing node of type arc")
    for name, p in (a.get("props") or {}).items():
        if name not in PROPS:
            report.error("prop %r is not built in (allowed: %s)" % (name, ", ".join(PROPS)))
        elif p.get("parent", "root") not in ids:
            report.error("prop %s: unknown parent %r" % (name, p.get("parent")))
    for name, an in (a.get("anchors") or {}).items():
        if an.get("node") not in ids:
            report.error("anchor %s: unknown node %r" % (name, an.get("node")))
    check_state_overrides(m.get("states", {}), slots, a.get("props", {}), report)


def check_state_overrides(states, slots, props, report):
    if not isinstance(states, dict):
        report.error('pet.json: "states" must be an object')
        return
    for state, o in states.items():
        if state not in ANIMATIONS:
            report.error("states.%s: unknown animation (allowed: %s)" % (state, ", ".join(ANIMATIONS)))
            continue
        if not isinstance(o, dict):
            report.error("states.%s must be an object" % state)
            continue
        for key in o:
            if key not in OVERRIDE_KEYS:
                report.warn("states.%s: unknown key %r is ignored" % (state, key))
        for slot in o.get("pose", {}):
            if slot not in SLOTS:
                report.error("states.%s.pose: unknown slot %r" % (state, slot))
        for ch in o.get("channels", []):
            if ch.get("t") not in SLOTS or ch.get("k", "sine") not in CHANNEL_KINDS:
                report.error("states.%s: bad channel %s" % (state, json.dumps(ch)))
        for prop in o.get("show", []):
            if prop not in props:
                report.warn("states.%s shows prop %r that the avatar does not define" % (state, prop))
        for fx in o.get("fx", []):
            if fx.get("kind") not in FX_KINDS:
                report.error("states.%s: unknown fx %r" % (state, fx.get("kind")))
        if "expression" in o and o["expression"] not in EXPRESSIONS:
            report.error("states.%s: unknown expression %r" % (state, o["expression"]))


# ------------------------------------------------------------------------------------------ sprite

def check_sprite(m, root, report):
    s = m.get("sprite")
    if not isinstance(s, dict):
        report.error('pet.json: a sprite pack needs a "sprite" object')
        return
    frame = s.get("frame", {})
    fw, fh = frame.get("width"), frame.get("height")
    if not (isinstance(fw, int) and isinstance(fh, int) and 8 <= fw <= 1024 and 8 <= fh <= 1024):
        report.error("sprite.frame width/height must be integers from 8 to 1024")
        return
    states = s.get("states", {})
    if not isinstance(states, dict):
        report.error("sprite.states must be an object")
        return
    for state, e in states.items():
        if state not in ANIMATIONS:
            report.error("sprite.states.%s: unknown animation" % state)
            continue
        image = e.get("image")
        if not isinstance(image, str) or image.startswith("/") or ".." in Path(image).parts:
            report.error("sprite.states.%s: image path must stay inside the pack" % state)
            continue
        frames, fps = e.get("frames", 1), e.get("fps", 8)
        if not (isinstance(frames, int) and 1 <= frames <= MAX_FRAMES):
            report.error("sprite.states.%s: frames must be 1-%d" % (state, MAX_FRAMES))
            continue
        if not (_num(fps) and 1 <= fps <= 30):
            report.error("sprite.states.%s: fps must be 1-30" % state)
        file = root / image
        if not file.is_file():
            report.error("sprite.states.%s: %s is missing" % (state, image))
            continue
        if file.suffix.lower() != ".png":
            report.warn("%s: dimensions of non-PNG images are not checked" % image)
            continue
        try:
            w, h = struct.unpack(">II", file.read_bytes()[16:24])
        except struct.error:
            report.error("%s is not a PNG" % image)
            continue
        if w > MAX_IMAGE_SIDE or h > MAX_IMAGE_SIDE:
            report.error("%s: %dx%d is larger than %d px" % (image, w, h, MAX_IMAGE_SIDE))
        cols = e.get("cols") or frames
        rows = -(-(e.get("start", 0) + frames) // cols)
        if w < cols * fw or h < (e.get("row", 0) + rows) * fh:
            report.error("%s: %dx%d is too small for %d frames of %dx%d in %d columns" % (image, w, h, frames, fw, fh, cols))
    return states


# ---------------------------------------------------------------------------------------- entry

def validate(path):
    root = Path(path)
    if not root.is_dir() and (PRESETS / str(path)).is_dir():
        root = PRESETS / str(path)
    report = Report(root)
    if not root.is_dir():
        report.error("%s is not a folder" % path)
        return report
    check_files(root, report)
    manifest = read_json(root / "pet.json", report, "pet.json")
    if manifest is None:
        return report
    renderer = check_manifest(manifest, root, report)
    implemented = None
    if renderer == "three":
        avatar = (manifest.get("three") or {}).get("avatar", "avatar.json")
        if not isinstance(avatar, str) or avatar.startswith("/") or ".." in Path(avatar).parts:
            report.error("three.avatar path must stay inside the pack")
        else:
            check_avatar(root / avatar, manifest, report)
        lights = (manifest.get("three") or {}).get("lights", "soft")
        if lights not in LIGHTS:
            report.error("three.lights must be one of %s" % ", ".join(LIGHTS))
        implemented = lambda n: not n.startswith("antic_")  # the recipe library covers every animation
        report.note("every animation is provided by the shared recipe library")
    elif renderer == "sprite":
        states = check_sprite(manifest, root, report) or {}
        implemented = lambda n: n in states
        missing = [n for n in REQUIRED_STATES if n not in states]
        if missing:
            report.error("sprite pack must implement the required states; missing: %s" % ", ".join(missing))
        fallback = {n: resolve_animation(n, implemented) for n in ANIMATIONS if n not in states}
        if fallback:
            report.note("fallbacks: " + ", ".join("%s->%s" % kv for kv in sorted(fallback.items())))
    return report


# ----------------------------------------------------------------------------------- scaffold, io

def find_pack(ref):
    path = Path(ref)
    if path.is_dir():
        return path
    for base in (PRESETS, USER_DIR):
        if (base / ref).is_dir():
            return base / ref
    raise SystemExit("no pack %r (looked in presets and %s)" % (ref, USER_DIR))


def new_pack(pack_id, source, dest, name=None):
    if not ID_RE.match(pack_id):
        raise SystemExit("id must match %s" % ID_RE.pattern)
    src = find_pack(source)
    target = Path(dest) if dest else PRESETS / pack_id
    if target.exists():
        raise SystemExit("%s already exists; pick another id or --dest" % target)
    shutil.copytree(src, target, ignore=shutil.ignore_patterns(".DS_Store", "__pycache__"))
    manifest = json.loads((target / "pet.json").read_text())
    manifest.update(id=pack_id, name=name or pack_id, name_en=pack_id, version="0.1.0", author="you", license="CC0-1.0",
                    description="基于 %s 的新形象，请改写描述。" % source)
    (target / "pet.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n")
    return target


def pack_zip(root, out=None):
    report = validate(root)
    if not report.ok:
        raise SystemExit("refusing to pack an invalid pack:\n  " + "\n  ".join(report.errors))
    manifest = json.loads((root / "pet.json").read_text())
    out = Path(out) if out else Path.cwd() / ("%s-%s.agentpet" % (manifest["id"], manifest["version"]))
    files = sorted(p for p in root.rglob("*") if p.is_file() and p.name != ".DS_Store" and "__pycache__" not in p.parts)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            info = zipfile.ZipInfo("%s/%s" % (manifest["id"], f.relative_to(root).as_posix()), date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, f.read_bytes())
    return out


def safe_extract(archive, dest):
    """Extracts a .agentpet into dest, refusing absolute paths, '..', symlinks and oversized content."""
    total = 0
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            parts = Path(info.filename).parts
            mode = info.external_attr >> 16
            if info.filename.startswith("/") or ".." in parts or stat.S_ISLNK(mode):
                raise SystemExit("unsafe entry in archive: %s" % info.filename)
            total += info.file_size
            if total > MAX_PACK_BYTES * 2 or info.file_size > MAX_FILE_BYTES * 2:
                raise SystemExit("archive is too large")
        z.extractall(dest)
    folders = [p for p in Path(dest).iterdir() if p.is_dir()]
    if len(folders) != 1:
        raise SystemExit("an .agentpet must contain exactly one pack folder")
    return folders[0]


def install(source, dest=None, force=False):
    dest = Path(dest) if dest else USER_DIR
    source = Path(source)
    with tempfile.TemporaryDirectory() as tmp:
        root = safe_extract(source, tmp) if source.is_file() and source.suffix == ".agentpet" else find_pack(str(source))
        report = validate(root)
        if not report.ok:
            raise SystemExit("not installing an invalid pack:\n  " + "\n  ".join(report.errors))
        target = dest / root.name
        if target.exists() and not force:
            raise SystemExit("%s exists; pass --force to replace it" % target)
        dest.mkdir(parents=True, exist_ok=True)
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(root, target, ignore=shutil.ignore_patterns(".DS_Store", "__pycache__"))
    return target


def listing():
    rows = []
    for label, base in (("preset", PRESETS), ("user", USER_DIR)):
        if base.is_dir():
            for path in sorted(p for p in base.iterdir() if (p / "pet.json").is_file()):
                report = validate(path)
                manifest = json.loads((path / "pet.json").read_text())
                rows.append((label, manifest.get("id"), manifest.get("name"), manifest.get("renderer"), "ok" if report.ok else "INVALID"))
    return rows


# ------------------------------------------------------------------------------------------- CLI

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate"); v.add_argument("packs", nargs="+"); v.add_argument("--json", action="store_true")
    v.add_argument("--strict", action="store_true", help="treat warnings as errors")
    n = sub.add_parser("new"); n.add_argument("id"); n.add_argument("--from", dest="source", default="gauge")
    n.add_argument("--name"); n.add_argument("--dest")
    k = sub.add_parser("pack"); k.add_argument("pack"); k.add_argument("-o", "--out")
    i = sub.add_parser("install"); i.add_argument("source"); i.add_argument("--dest"); i.add_argument("--force", action="store_true")
    sub.add_parser("list")
    args = p.parse_args(argv)

    if args.cmd == "validate":
        reports = [validate(x) for x in args.packs]
        if args.json:
            print(json.dumps([r.as_dict() for r in reports], ensure_ascii=False, indent=1))
        else:
            for r in reports:
                print("%s  %s" % ("OK  " if r.ok else "FAIL", r.path))
                for line in r.errors:
                    print("  error: " + line)
                for line in r.warnings:
                    print("  warn:  " + line)
                for line in r.notes:
                    print("  note:  " + line)
        return 0 if all(r.ok and not (args.strict and r.warnings) for r in reports) else 1
    if args.cmd == "new":
        target = new_pack(args.id, args.source, args.dest, args.name)
        print("created %s (forked from %s); edit it, then: petpack.py validate %s" % (target, args.source, target))
    elif args.cmd == "pack":
        print(pack_zip(find_pack(args.pack), args.out))
    elif args.cmd == "install":
        print("installed ->", install(args.source, args.dest, args.force))
    elif args.cmd == "list":
        for row in listing():
            print("%-7s %-12s %-10s %-7s %s" % (row[0], row[1], row[2], row[3], row[4]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
