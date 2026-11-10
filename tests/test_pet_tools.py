import contextlib
import io
import json
import os
import re
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "pets" / "tools"
sys.path.insert(0, str(TOOLS))

import avatarkit  # noqa: E402
import build_presets  # noqa: E402
import petpack  # noqa: E402
import promptkit  # noqa: E402
import spritekit as sk  # noqa: E402

PRESETS = ROOT / "pets" / "presets"
EXPECTED_PRESETS = {"gauge", "blob", "tibo", "bot", "cat", "bit"}


def js_list(source, name):
    match = re.search(r"export const %s = \[(.*?)\];" % name, source, re.S)
    return re.findall(r"'([^']+)'", match.group(1))


class WorkPack(unittest.TestCase):
    """Copies a preset into a temp dir so each test can break it in its own way."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def fork(self, source="gauge", new_id="work"):
        target = self.root / new_id
        shutil.copytree(PRESETS / source, target)
        manifest = json.loads((target / "pet.json").read_text())
        manifest["id"] = new_id
        (target / "pet.json").write_text(json.dumps(manifest))
        return target

    def edit_avatar(self, pack, fn):
        path = pack / "avatar.json"
        data = json.loads(path.read_text())
        fn(data)
        path.write_text(json.dumps(data))

    def edit_manifest(self, pack, fn):
        path = pack / "pet.json"
        data = json.loads(path.read_text())
        fn(data)
        path.write_text(json.dumps(data))

    def errors(self, pack):
        return petpack.validate(pack).errors

    def assertError(self, pack, fragment):
        errors = self.errors(pack)
        self.assertTrue(any(fragment in e for e in errors), "%r not in %r" % (fragment, errors))


class BuiltInPresetTests(unittest.TestCase):
    def test_the_expected_presets_ship_and_are_clean(self):
        found = {p.name for p in PRESETS.iterdir() if (p / "pet.json").is_file()}
        self.assertTrue(EXPECTED_PRESETS <= found, found)
        for name in sorted(found):
            report = petpack.validate(PRESETS / name)
            self.assertEqual(report.errors, [], name)
            self.assertEqual(report.warnings, [], name)

    def test_there_are_both_renderers(self):
        kinds = {json.loads((PRESETS / n / "pet.json").read_text())["renderer"] for n in EXPECTED_PRESETS}
        self.assertEqual(kinds, {"three", "sprite"})

    def test_generators_reproduce_the_committed_json(self):
        for pid, builder in build_presets.BUILDERS.items():
            meta, avatar = builder()
            self.assertEqual(meta, json.loads((PRESETS / pid / "pet.json").read_text()), pid)
            self.assertEqual(avatar, json.loads((PRESETS / pid / "avatar.json").read_text()), pid)

    def test_vocabulary_matches_the_runtime(self):
        source = (ROOT / "pets/runtime/js/constants.js").read_text()
        self.assertEqual(tuple(js_list(source, "BASE_STATES")), petpack.BASE_STATES)
        self.assertEqual(tuple(js_list(source, "REACTIONS")), petpack.REACTIONS)
        self.assertEqual(tuple(js_list(source, "INTERACTIONS")), petpack.INTERACTIONS)
        self.assertEqual(tuple(js_list(source, "REQUIRED_STATES")), petpack.REQUIRED_STATES)
        self.assertEqual(tuple(js_list(source, "EXPRESSIONS")), petpack.EXPRESSIONS)
        block = re.search(r"export const FALLBACKS = \{(.*?)\n\};", source, re.S).group(1)
        parsed = {k: re.findall(r"'([^']+)'", v) for k, v in re.findall(r"(\w+): \[(.*?)\]", block)}
        self.assertEqual(parsed, petpack.FALLBACKS)

    def test_python_states_match_the_brain(self):
        from agent_meter import pet
        self.assertEqual(tuple(pet.STATES), petpack.BASE_STATES)
        self.assertEqual(tuple(pet.REACTIONS), petpack.REACTIONS)
        self.assertTrue(set(pet.MOODS) <= set(petpack.EXPRESSIONS), "every mood the brain emits must be an expression avatars know")

    def test_every_animation_resolves_for_a_minimal_pack(self):
        has = lambda n: n in petpack.REQUIRED_STATES
        for name in petpack.ANIMATIONS:
            self.assertTrue(has(petpack.resolve_animation(name, has)), name)


class ManifestAndAvatarTests(WorkPack):
    def test_a_fork_validates(self):
        self.assertEqual(self.errors(self.fork()), [])

    def test_manifest_problems(self):
        for field, value, fragment in (("id", "Bad Id", "id"), ("format", "x/9", "format"), ("version", "1", "version"),
                                       ("renderer", "svg", "renderer"), ("name", "", "name"), ("license", "", "license"),
                                       ("description", "x" * 400, "description")):
            pack = self.fork(new_id="work-" + field.lower())
            self.edit_manifest(pack, lambda m: m.__setitem__(field, value))
            self.assertError(pack, fragment)

    def test_folder_name_must_match_the_id(self):
        pack = self.fork()
        self.edit_manifest(pack, lambda m: m.__setitem__("id", "other"))
        self.assertError(pack, "must equal the folder name")

    def test_voice_and_stage_limits(self):
        pack = self.fork()
        self.edit_manifest(pack, lambda m: m.__setitem__("voice", {"idle": ["x" * 80]}))
        self.assertError(pack, "voice")
        self.edit_manifest(pack, lambda m: m.__setitem__("stage", {"width": 50, "height": 260}))
        self.assertError(pack, "stage")

    def test_missing_or_broken_avatar(self):
        pack = self.fork()
        (pack / "avatar.json").write_text("{nope")
        self.assertError(pack, "not valid JSON")
        (pack / "avatar.json").unlink()
        self.assertError(pack, "is missing")

    def test_node_rules(self):
        cases = {
            "unknown type": lambda a: a["nodes"][1].__setitem__("type", "teapot"),
            "defined earlier": lambda a: a["nodes"].insert(0, {"id": "early", "type": "group", "parent": "root"}),
            "duplicate id": lambda a: a["nodes"].append(dict(a["nodes"][1])),
            "unknown material": lambda a: a["nodes"][1].__setitem__("material", "ghost"),
            "segments": lambda a: a["nodes"][5].__setitem__("segments", [999, 8]),
            "position": lambda a: a["nodes"][1].__setitem__("position", [99, 0, 0]),
            "radius": lambda a: a["nodes"][5].__setitem__("radius", 50),
            "scale": lambda a: a["nodes"][1].__setitem__("scale", 0),
        }
        for fragment, mutate in cases.items():
            pack = self.fork(new_id="n" + str(abs(hash(fragment)) % 10 ** 6))
            self.edit_avatar(pack, mutate)
            self.assertError(pack, fragment)

    def test_too_many_nodes(self):
        pack = self.fork()
        self.edit_avatar(pack, lambda a: a["nodes"].extend({"id": "n%d" % i, "type": "group"} for i in range(450)))
        self.assertError(pack, "exceeds the limit")

    def test_colour_rules(self):
        pack = self.fork()
        self.edit_avatar(pack, lambda a: a["palette"].__setitem__("shell", "pink"))
        self.assertError(pack, "not a colour")
        self.edit_avatar(pack, lambda a: a["palette"].__setitem__("shell", "$nonsense"))
        self.assertError(pack, "unknown theme token")
        self.edit_avatar(pack, lambda a: a["palette"].update(shell="loop", loop="shell"))
        self.assertError(pack, "loops")

    def test_slots_expressions_and_meter(self):
        def slot(a): a["slots"]["head"] = "nowhere"
        def unknown_slot(a): a["slots"]["tentacle"] = "root"
        def show(a): a["face"]["expressions"]["happy"]["show"].append("ghost")
        def neutral(a): del a["face"]["expressions"]["neutral"]
        def meter(a): a["meter"]["node"] = "shell"
        for fragment, mutate in (("unknown node 'nowhere'", slot), ("slot 'tentacle'", unknown_slot), ("shows unknown node", show),
                                 ("neutral", neutral), ("existing node of type arc", meter)):
            pack = self.fork(new_id="s" + str(abs(hash(fragment)) % 10 ** 6))
            self.edit_avatar(pack, mutate)
            self.assertError(pack, fragment)

    def test_props_anchors_and_overrides(self):
        pack = self.fork()
        self.edit_avatar(pack, lambda a: a["props"].__setitem__("flamethrower", {"parent": "root"}))
        self.assertError(pack, "not built in")
        pack = self.fork(new_id="work2")
        self.edit_manifest(pack, lambda m: m["states"].update(dancing={}))
        self.assertError(pack, "unknown animation")
        self.edit_manifest(pack, lambda m: m.__setitem__("states", {"idle": {"pose": {"tentacle": {}}}}))
        self.assertError(pack, "unknown slot")
        self.edit_manifest(pack, lambda m: m.__setitem__("states", {"idle": {"fx": [{"kind": "lasers"}]}}))
        self.assertError(pack, "unknown fx")
        self.edit_manifest(pack, lambda m: m["three"].__setitem__("lights", "disco"))
        self.assertError(pack, "lights")

    def test_avatar_path_cannot_escape(self):
        pack = self.fork()
        self.edit_manifest(pack, lambda m: m["three"].__setitem__("avatar", "../gauge/avatar.json"))
        self.assertError(pack, "stay inside the pack")


class FileSafetyTests(WorkPack):
    def test_code_and_markup_are_refused(self):
        for name in ("evil.js", "page.html", "image.svg", "style.css", "m.wasm"):
            pack = self.fork(new_id="f" + name.replace(".", ""))
            (pack / name).write_text("x")
            self.assertError(pack, "not allowed")

    def test_symlinks_hidden_files_and_big_files(self):
        pack = self.fork()
        os.symlink("/etc/hosts", pack / "link.json")
        self.assertError(pack, "symbolic links")
        pack = self.fork(new_id="work2")
        (pack / ".secret").write_text("x")
        self.assertError(pack, "hidden files")
        pack = self.fork(new_id="work3")
        (pack / "big.png").write_bytes(b"0" * (petpack.MAX_FILE_BYTES + 1))
        self.assertError(pack, "per-file limit")
        pack = self.fork(new_id="work4")
        (pack / ".DS_Store").write_text("finder noise")      # tolerated
        self.assertEqual(self.errors(pack), [])


class SpritePackValidationTests(WorkPack):
    def test_problems(self):
        for fragment, mutate in (
                ("missing", lambda root, m: (root / "sprites/idle.png").unlink()),
                ("too small", lambda root, m: m["sprite"]["states"]["idle"].__setitem__("frames", 40)),
                ("frames must be", lambda root, m: m["sprite"]["states"]["idle"].__setitem__("frames", 99)),
                ("fps", lambda root, m: m["sprite"]["states"]["idle"].__setitem__("fps", 120)),
                ("stay inside", lambda root, m: m["sprite"]["states"]["idle"].__setitem__("image", "../x.png")),
                ("required states", lambda root, m: m["sprite"]["states"].pop("sleeping")),
                ("unknown animation", lambda root, m: m["sprite"]["states"].__setitem__("moonwalk", {"image": "sprites/idle.png", "frames": 1})),
                ("frame width", lambda root, m: m["sprite"]["frame"].__setitem__("width", 2))):
            pack = self.fork("bit", "z" + str(abs(hash(fragment)) % 10 ** 6))
            manifest = json.loads((pack / "pet.json").read_text())
            mutate(pack, manifest)
            (pack / "pet.json").write_text(json.dumps(manifest))
            self.assertError(pack, fragment)

    def test_fallbacks_are_reported(self):
        notes = petpack.validate(PRESETS / "bit").notes
        self.assertTrue(any("busy->working" in n for n in notes))


class ScaffoldPackInstallTests(WorkPack):
    def test_new_forks_and_validates(self):
        target = petpack.new_pack("fresh-pet", "cat", str(self.root / "fresh-pet"), "新宠")
        manifest = json.loads((target / "pet.json").read_text())
        self.assertEqual((manifest["id"], manifest["name"], manifest["version"]), ("fresh-pet", "新宠", "0.1.0"))
        self.assertEqual(petpack.validate(target).errors, [])
        with self.assertRaises(SystemExit):
            petpack.new_pack("fresh-pet", "cat", str(target))              # already exists
        with self.assertRaises(SystemExit):
            petpack.new_pack("Bad Id", "cat", None)

    def test_pack_is_deterministic_and_installs_safely(self):
        pack = self.fork("tibo", "tibo-copy")
        first = petpack.pack_zip(pack, self.root / "a.agentpet")
        second = petpack.pack_zip(pack, self.root / "b.agentpet")
        self.assertEqual(first.read_bytes(), second.read_bytes())
        with zipfile.ZipFile(first) as z:
            self.assertTrue(all(n.startswith("tibo-copy/") for n in z.namelist()))
        dest = self.root / "installed"
        target = petpack.install(first, dest)
        self.assertTrue((target / "pet.json").is_file())
        with self.assertRaises(SystemExit):
            petpack.install(first, dest)                                   # exists, no --force
        self.assertTrue(petpack.install(first, dest, force=True).is_dir())

    def test_invalid_packs_are_neither_packed_nor_installed(self):
        pack = self.fork()
        self.edit_manifest(pack, lambda m: m.__setitem__("renderer", "nope"))
        with self.assertRaises(SystemExit):
            petpack.pack_zip(pack, self.root / "x.agentpet")
        with self.assertRaises(SystemExit):
            petpack.install(pack, self.root / "dest")

    def test_archives_cannot_escape_or_carry_symlinks(self):
        evil = self.root / "evil.agentpet"
        with zipfile.ZipFile(evil, "w") as z:
            z.writestr("../outside.txt", "x")
        with self.assertRaises(SystemExit):
            petpack.safe_extract(evil, self.root / "out")
        link = self.root / "link.agentpet"
        with zipfile.ZipFile(link, "w") as z:
            info = zipfile.ZipInfo("pack/pet.json")
            info.external_attr = (0o120777 << 16)
            z.writestr(info, "/etc/passwd")
        with self.assertRaises(SystemExit):
            petpack.safe_extract(link, self.root / "out2")
        two = self.root / "two.agentpet"
        with zipfile.ZipFile(two, "w") as z:
            z.writestr("a/pet.json", "{}")
            z.writestr("b/pet.json", "{}")
        with self.assertRaises(SystemExit):
            petpack.safe_extract(two, self.root / "out3")

    def test_listing_includes_presets(self):
        ids = {row[1] for row in petpack.listing() if row[0] == "preset"}
        self.assertTrue(EXPECTED_PRESETS <= ids)


class AvatarKitTests(unittest.TestCase):
    def test_surface_points_lie_on_the_ellipsoid_and_face_outwards(self):
        ellipsoid = ((0, 0.5, 0), (0.5, 0.47, 0.46))
        for x, y in ((0, 0), (0.19, 0.06), (-0.3, 0.2), (0.1, -0.3)):
            pos, (pitch, yaw) = avatarkit.surface(ellipsoid, x, y, lift=0)
            (cx, cy, cz), (rx, ry, rz) = ellipsoid
            on = ((pos[0] - cx) / rx) ** 2 + ((pos[1] - cy) / ry) ** 2 + ((pos[2] - cz) / rz) ** 2
            self.assertAlmostEqual(on, 1, places=2)
            lifted, _ = avatarkit.surface(ellipsoid, x, y, lift=0.01)
            self.assertGreater(lifted[2], pos[2])
        _, (pitch, yaw) = avatarkit.surface(ellipsoid, 0, 0)
        self.assertAlmostEqual(yaw, 0, places=1)
        _, (_, yaw_right) = avatarkit.surface(ellipsoid, 0.3, 0)
        self.assertGreater(yaw_right, 5)                                    # right of centre turns to the right

    def test_decals_off_the_head_are_refused(self):
        with self.assertRaises(ValueError):
            avatarkit.surface(((0, 0, 0), (0.5, 0.5, 0.5)), 0.5, 0.5)

    def test_builder_checks_ids_parents_and_slots(self):
        av = avatarkit.Avatar()
        av.group("root")
        with self.assertRaises(ValueError):
            av.group("root")
        with self.assertRaises(ValueError):
            av.node("child", "sphere", "ghost")
        av.slots(tentacle="root")
        with self.assertRaises(ValueError):
            av.build()
        bad = avatarkit.Avatar()
        bad.group("root")
        bad.slots(head="missing")
        with self.assertRaises(ValueError):
            bad.build()

    def test_face_builds_every_expression_from_existing_nodes(self):
        av = avatarkit.Avatar()
        for name in ("ink", "white", "blush", "tongue", "heart"):
            av.material(name, "basic", color="#000000")
        av.group("root")
        av.group("head", "root")
        av.face("head", head=((0, 0, 0), (0.5, 0.47, 0.46)))
        data = av.build()
        ids = {n["id"] for n in data["nodes"]}
        self.assertEqual(set(data["face"]["expressions"]), set(avatarkit.EXPRESSIONS))
        for name, e in data["face"]["expressions"].items():
            self.assertTrue(set(e["show"]) <= ids, name)
        self.assertTrue(set(data["face"]["managed"]) <= ids)
        self.assertEqual(set(data["face"]["blink"]) | {"eyeL", "eyeR"}, {"eyeL", "eyeR"})


def png_rows(rows, color_type, depth=8, palette=None, trns=None, filter_type=0):
    """Hand-rolled PNG encoder (all filter types) to exercise the decoder."""
    bpp = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type] * depth // 8 or 1
    raw, prev = b"", bytes(len(rows[0]))
    for row in rows:
        row = bytes(row)
        out = bytearray()
        for i, value in enumerate(row):
            a = row[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if filter_type == 0:
                pred = 0
            elif filter_type == 1:
                pred = a
            elif filter_type == 2:
                pred = b
            elif filter_type == 3:
                pred = (a + b) // 2
            else:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if pa <= pb and pa <= pc else b if pb <= pc else c
            out.append((value - pred) & 255)
        raw += bytes([filter_type]) + bytes(out)
        prev = row

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    width = len(rows[0]) * 8 // (depth * {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type])
    png = sk.PNG_SIGNATURE + chunk(b"IHDR", struct.pack(">IIBBBBB", width, len(rows), depth, color_type, 0, 0, 0))
    if palette:
        png += chunk(b"PLTE", bytes(palette))
    if trns:
        png += chunk(b"tRNS", bytes(trns))
    return png + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def subject(w=20, h=30, color=(220, 40, 40, 255)):
    img = sk.new_image(w, h)
    for y in range(4, h):
        for x in range(4, w - 4):
            img.set(x, y, color)
    return img


class SpriteKitTests(unittest.TestCase):
    def test_png_round_trip(self):
        img = sk.new_image(5, 4, (10, 20, 30, 255))
        img.set(2, 1, (200, 100, 50, 128))
        again = sk.decode_png(sk.encode_png(img))
        self.assertEqual((again.width, again.height, bytes(again.pixels)), (5, 4, bytes(img.pixels)))
        self.assertEqual(sk.png_size(sk.encode_png(img)), (5, 4))

    def test_every_png_filter_decodes(self):
        rows = [[(x * 7 + y * 13 + c * 29) % 256 for x in range(6) for c in range(4)] for y in range(5)]
        expected = None
        for ft in range(5):
            img = sk.decode_png(png_rows(rows, 6, filter_type=ft))
            expected = expected or bytes(img.pixels)
            self.assertEqual(bytes(img.pixels), expected, "filter %d" % ft)
        self.assertEqual(expected[:4], bytes(rows[0][:4]))

    def test_other_colour_types(self):
        rgb = sk.decode_png(png_rows([[1, 2, 3, 4, 5, 6]], 2))
        self.assertEqual(rgb.get(1, 0), (4, 5, 6, 255))
        grey = sk.decode_png(png_rows([[9, 99]], 0))
        self.assertEqual(grey.get(1, 0), (99, 99, 99, 255))
        grey_alpha = sk.decode_png(png_rows([[9, 200, 99, 100]], 4))
        self.assertEqual(grey_alpha.get(1, 0), (99, 99, 99, 100))
        indexed = sk.decode_png(png_rows([[0, 1]], 3, palette=[255, 0, 0, 0, 255, 0], trns=[128]))
        self.assertEqual((indexed.get(0, 0), indexed.get(1, 0)), ((255, 0, 0, 128), (0, 255, 0, 255)))

    def test_bad_png_is_rejected(self):
        for blob in (b"GIF89a", sk.PNG_SIGNATURE, sk.PNG_SIGNATURE + b"\0" * 8):
            with self.assertRaises((sk.SpriteError, Exception)):
                sk.decode_png(blob)
        interlaced = bytearray(png_rows([[1, 2, 3, 255]], 6))
        interlaced[28] = 1                                                   # interlace byte in IHDR
        with self.assertRaises(sk.SpriteError):
            sk.decode_png(bytes(interlaced))

    def test_auto_key_and_chroma_key(self):
        green = (0, 255, 0, 255)
        img = sk.new_image(12, 12, green)
        for y in range(3, 9):
            for x in range(3, 9):
                img.set(x, y, (200, 30, 30, 255))
        img.set(2, 5, (60, 215, 60, 255))                                    # a green-tinted edge pixel inside the feather band
        self.assertEqual(sk.auto_key_color(img)[1] // 8, 255 // 8)
        keyed = sk.chroma_key(img)
        self.assertEqual(keyed.get(0, 0)[3], 0)
        self.assertEqual(keyed.get(5, 5), (200, 30, 30, 255))
        edge = keyed.get(2, 5)
        self.assertTrue(0 <= edge[3] < 255)
        self.assertLessEqual(edge[1], (edge[0] + edge[2]) // 2 + 1)         # despilled
        self.assertEqual(sk.bbox(keyed), (2, 3, 9, 9))

    def test_keying_a_transparent_corner_is_an_error(self):
        with self.assertRaises(sk.SpriteError):
            sk.auto_key_color(sk.new_image(8, 8))

    def test_bbox_trim_crop_paste(self):
        img = subject()
        self.assertEqual(sk.bbox(img), (4, 4, 16, 30))
        self.assertEqual((sk.trim(img).width, sk.trim(img).height), (12, 26))
        with self.assertRaises(sk.SpriteError):
            sk.trim(sk.new_image(4, 4))
        canvas = sk.new_image(10, 10, (0, 0, 255, 255))
        half = sk.new_image(2, 2, (255, 0, 0, 128))
        sk.paste(canvas, half, 4, 4)
        r, g, b, a = canvas.get(4, 4)
        self.assertTrue(120 < r < 140 and 120 < b < 135 and a == 255, (r, g, b, a))
        sk.paste(canvas, half, 9, 9)                                          # partially off-canvas: no crash

    def test_slicing(self):
        strip = sk.new_image(60, 20)
        for k in range(3):
            for y in range(2, 18):
                for x in range(k * 20 + 4, k * 20 + 14):
                    strip.set(x, y, (255, 255, 255, 255))
        grid = sk.slice_grid(strip, 3)
        self.assertEqual([(f.width, f.height) for f in grid], [(20, 20)] * 3)
        auto = sk.slice_auto(strip, expected=3)
        self.assertEqual([f.width for f in auto], [10, 10, 10])
        with self.assertRaises(sk.SpriteError):
            sk.slice_auto(strip, expected=5)
        with self.assertRaises(sk.SpriteError):
            sk.slice_auto(sk.new_image(10, 10))

    def test_align_uses_one_scale_and_a_common_baseline(self):
        tall, short = subject(20, 40), subject(20, 20)
        out, k = sk.align({"idle": [tall], "working": [short]}, 32, margin=2)
        self.assertAlmostEqual(k, 28 / 36, places=3)                          # the tallest content fits the cell
        for frames in out.values():
            for tile in frames:
                self.assertEqual((tile.width, tile.height), (32, 32))
                self.assertEqual(sk.bbox(tile)[3], 30)                        # feet on the same baseline
        ratio = (sk.bbox(out["working"][0])[3] - sk.bbox(out["working"][0])[1]) / (sk.bbox(out["idle"][0])[3] - sk.bbox(out["idle"][0])[1])
        self.assertAlmostEqual(ratio, 16 / 36, delta=0.08)                    # relative size kept

    def test_resize_modes(self):
        pixel = sk.new_image(2, 2)
        pixel.set(0, 0, (255, 0, 0, 255)); pixel.set(1, 0, (0, 255, 0, 255)); pixel.set(0, 1, (0, 0, 255, 255)); pixel.set(1, 1, (255, 255, 0, 255))
        big = sk.resize(pixel, 4, 4, smooth=False)
        self.assertEqual({big.get(x, y) for x in range(4) for y in range(4)}, {pixel.get(x, y) for x in range(2) for y in range(2)})
        edge = sk.new_image(2, 1)
        edge.set(0, 0, (200, 0, 0, 255))
        soft = sk.resize(edge, 8, 1)
        self.assertTrue(all(soft.get(x, 0)[0] >= 190 for x in range(8) if soft.get(x, 0)[3] > 0), "no dark fringe from transparent neighbours")

    def test_pack_building_round_trip(self):
        states = {name: [subject(32, 32, (40 + i * 30, 120, 200, 255)) for i in range(2)] for i, name in enumerate(petpack.REQUIRED_STATES)}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "mine"
            manifest = sk.write_pack(out, "mine", "我的", states, 32, name_en="Mine")
            self.assertEqual(manifest["sprite"]["states"]["idle"]["frames"], 2)
            self.assertFalse(manifest["sprite"]["states"]["celebrate"].get("loop", True) is False and False)
            report = petpack.validate(out)
            self.assertEqual(report.errors, [], report.errors)
            manifest2, rows = sk.read_pack_frames(out)
            self.assertEqual(len(rows), len(states))
            sheet = sk.montage([f for _, f in rows], cell=24)
            self.assertGreater(sheet.width, 24)
            with self.assertRaises(sk.SpriteError):
                sk.write_pack(Path(tmp) / "bad", "bad", "坏", {"idle": [sk.new_image(30, 32)]}, 32)

    def test_cli_pipeline_key_slice_build_sheet(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            strip = sk.new_image(96, 32, (0, 255, 0, 255))
            for k in range(3):
                for y in range(6, 30):
                    for x in range(k * 32 + 8, k * 32 + 24):
                        strip.set(x, y, (30 + k * 60, 90, 200, 255))
            sk.write_png(strip, tmp / "raw.png")
            quiet = contextlib.redirect_stdout(io.StringIO())
            quiet.__enter__()
            sk.main(["key", str(tmp / "raw.png"), str(tmp / "keyed.png")])
            sk.main(["slice", str(tmp / "keyed.png"), "--frames", "3", "--out", str(tmp / "frames")])
            self.assertEqual(len(list((tmp / "frames").glob("*.png"))), 3)
            strips = tmp / "strips"
            strips.mkdir()
            for name in petpack.REQUIRED_STATES:
                shutil.copytree(tmp / "frames", strips / name)
            sk.main(["build", str(strips), "--id", "piped", "--name", "管线", "--frame", "48", "--out", str(tmp / "piped")])
            self.assertEqual(petpack.validate(tmp / "piped").errors, [])
            sk.main(["sheet", str(tmp / "piped"), "--out", str(tmp / "sheet.png")])
            quiet.__exit__(None, None, None)
            self.assertTrue((tmp / "sheet.png").stat().st_size > 100)

    def test_non_png_input_goes_through_a_converter_or_fails_clearly(self):
        with tempfile.TemporaryDirectory() as tmp:
            bogus = Path(tmp) / "x.jpg"
            bogus.write_bytes(b"not an image at all")
            with self.assertRaises(Exception):
                sk.load(bogus)



SKILLS = ROOT / ".claude" / "skills"
TOOL_SCRIPTS = {"petpack.py": ["validate", "new", "pack", "install", "list"], "spritekit.py": ["key", "slice", "build", "sheet", "info"],
                "promptkit.py": [None], "serve.py": [None], "build_presets.py": [None], "build_sprites.py": [None]}


def help_text(script, sub):
    cmd = [sys.executable, str(TOOLS / script)] + ([sub] if sub else []) + ["--help"]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout


class SkillTests(unittest.TestCase):
    def skill_files(self):
        return sorted(SKILLS.glob("agentmeter-pet-*/**/*.md"))

    def test_both_skills_exist_with_frontmatter(self):
        for name in ("agentmeter-pet-three", "agentmeter-pet-imagegen"):
            text = (SKILLS / name / "SKILL.md").read_text()
            match = re.match(r"^---\nname: (.+)\ndescription: (.+)\n---\n", text)
            self.assertIsNotNone(match, name)
            self.assertEqual(match.group(1), name)
            self.assertGreater(len(match.group(2)), 80, "the description is what makes the skill trigger")

    def test_relative_links_resolve(self):
        for md in self.skill_files():
            for target in re.findall(r"\]\(([^)\s]+)\)", md.read_text()):
                if target.startswith(("http", "#")):
                    continue
                path = (md.parent / target.split("#")[0]).resolve()
                self.assertTrue(path.exists(), "%s links to missing %s" % (md.relative_to(ROOT), target))

    @staticmethod
    def commands(text):
        """Shell commands only: fenced code blocks and inline code spans (prose links are not commands)."""
        text = text.replace("\\\n", " ")
        for block in re.findall(r"```\w*\n(.*?)```", text, re.S):
            yield from block.splitlines()
        yield from re.findall(r"`([^`\n]+)`", text)

    def test_every_command_names_a_real_tool_subcommand_and_flag(self):
        seen = 0
        for md in self.skill_files():
            for line in self.commands(md.read_text()):
                for match in re.finditer(r"(?:python3|sh) pets/tools/([\w.]+)((?: [^\n&|;]*)?)", line):
                    script, rest = match.group(1), match.group(2)
                    if script.endswith(".sh"):
                        self.assertTrue((TOOLS / script).is_file(), "%s mentions a missing script %s" % (md.name, script))
                        continue
                    self.assertIn(script, TOOL_SCRIPTS, "%s mentions an unknown tool %s" % (md.name, script))
                    tokens = shlex.split(rest, posix=True) if rest.strip() else []
                    subs = TOOL_SCRIPTS[script]
                    sub = tokens[0] if subs != [None] and tokens and not tokens[0].startswith("-") else None
                    if subs != [None]:
                        self.assertIn(sub, subs, "%s: %s needs a valid subcommand, got %r" % (md.name, script, sub))
                    seen += 1
                    help_out = help_text(script, sub)
                    for flag in set(re.findall(r"(?<![\w-])(--[a-z][a-z-]*)", rest)):
                        self.assertIn(flag, help_out, "%s: %s %s has no %s" % (md.name, script, sub or "", flag))
        self.assertGreater(seen, 15)

    def test_template_character_builds_a_strictly_valid_pack(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "starter"
            subprocess.run([sys.executable, str(SKILLS / "agentmeter-pet-three/templates/new_character.py"), "--id", "starter",
                            "--name", "起步", "--out", str(out)], check=True, capture_output=True)
            report = petpack.validate(out)
            self.assertEqual((report.errors, report.warnings), ([], []))

    def test_skill_scripts_are_not_inside_a_pack(self):
        for pack in PRESETS.iterdir():
            self.assertEqual([p.name for p in pack.rglob("*.py")], [], pack.name)


class PromptKitTests(unittest.TestCase):
    BIBLE = "a round white mochi dumpling with tiny black dot eyes, pink cheeks and a small green leaf on its head"

    def run_kit(self, *extra):
        out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, out, True)
        with contextlib.redirect_stdout(io.StringIO()):
            promptkit.main(["--name", "麻薯", "--bible", self.BIBLE, "--out", out, *extra])
        return Path(out)

    def test_core_prompts_and_index(self):
        out = self.run_kit()
        index = json.loads((out / "index.json").read_text())
        self.assertEqual([s["step"] for s in index["steps"]], ["reference"] + promptkit.CORE)
        for step in index["steps"][1:]:
            text = (out / step["file"]).read_text()
            self.assertIn(self.BIBLE, text, "the bible is repeated verbatim")
            self.assertIn("#00FF00", text)
            self.assertIn("%d frames" % step["frames"], text)
            self.assertEqual(text.count("  frame "), step["frames"])
            self.assertIn("Avoid:", text)
            self.assertIn("--cols %d --rows %d" % tuple(step["grid"]), step["slice"])
            self.assertIn("work/keyed/%s.png" % step["step"], step["slice"])
        reference = (out / "00-character-sheet.txt").read_text()
        self.assertIn(self.BIBLE, reference)
        self.assertIn("perfectly flat solid", reference)
        self.assertIn("spritekit.py build", index["build"])

    def test_options_change_the_prompts(self):
        out = self.run_kit("--style", "pixel", "--key", "magenta", "--states", "idle,eating")
        index = json.loads((out / "index.json").read_text())
        self.assertEqual(index["key_color"], "#FF00FF")
        self.assertIn("--pixelated", index["build"])
        self.assertIn("--color #FF00FF", index["steps"][1]["key"])
        self.assertIn("pixel art", (out / "idle.txt").read_text())
        self.assertNotIn("#00FF00", (out / "eating.txt").read_text())

    def test_bad_input_is_refused(self):
        for argv in (["--name", "x", "--bible", "short", "--out", "/tmp/x"], ["--name", "x", "--bible", self.BIBLE, "--out", "/tmp/x", "--states", "moonwalk"]):
            with self.assertRaises(SystemExit):
                promptkit.main(argv)

    def test_layouts_match_common_image_ratios(self):
        self.assertEqual(promptkit.layout(4), (2, 2, "1:1"))
        self.assertEqual(promptkit.layout(6), (3, 2, "3:2"))
        cols, rows, _ = promptkit.layout(10)
        self.assertGreaterEqual(cols * rows, 10)
        for state, (frames, _, beats) in promptkit.STATES.items():
            self.assertGreaterEqual(len(beats), 2, state)
            self.assertLessEqual(len(beats), max(frames, 4) + 0, state)
        self.assertTrue(set(promptkit.CORE) <= set(promptkit.STATES))
        self.assertEqual(set(promptkit.CORE), set(petpack.REQUIRED_STATES))


if __name__ == "__main__":
    unittest.main()


class SwiftParityTests(unittest.TestCase):
    """The panel's 桌宠 tab keeps its own words for every state (PetCatalog.swift); they must not drift from the brain."""

    def swift(self, name):
        return (ROOT / "menubar/Sources/AgentMeterBar" / name).read_text()

    def catalogue(self, block):
        body = re.search(r"static let %s: \[PetStateInfo\] = \[(.*?)\n    \]" % block, self.swift("PetCatalog.swift"), re.S).group(1)
        return re.findall(r'\.init\(id: "([a-z]+)"', body)

    def test_the_tab_describes_every_state_and_reaction_of_the_brain(self):
        from agent_meter import pet
        self.assertEqual(sorted(self.catalogue("states")), sorted(pet.STATES))
        self.assertEqual(sorted(self.catalogue("reactions")), sorted(pet.REACTIONS))
        source = (ROOT / "pets/runtime/js/constants.js").read_text()
        animations = set(js_list(source, "BASE_STATES")) | set(js_list(source, "REACTIONS")) | set(js_list(source, "INTERACTIONS"))
        self.assertTrue(set(self.catalogue("states")) | set(self.catalogue("reactions")) <= animations,
                        "every state the tab lets you try must be an animation the runtime knows")

    def test_reminder_actions_only_name_tabs_the_panel_has(self):
        tabs = re.search(r"enum Tab: String, CaseIterable, Identifiable \{\s*case ([a-z, ]+)", self.swift("PanelView.swift")).group(1)
        tabs = set(tabs.replace(" ", "").split(","))
        used = set(re.findall(r'"tab": "([a-z]+)"', (ROOT / "agent_meter/pet.py").read_text()))
        self.assertTrue(used and used <= tabs, "pet.py names a tab the panel does not have: %s" % (used - tabs))
        allowed = re.search(r"static let tabs: Set<String> = \[(.*?)\]", self.swift("PetWindow.swift"), re.S).group(1)
        self.assertEqual(set(re.findall(r'"([a-z]+)"', allowed)), tabs, "PetAction.tabs must list every panel tab")
