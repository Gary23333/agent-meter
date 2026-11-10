"""Authoring kit for three.js avatars (stdlib only). It writes the declarative avatar.json that
pets/runtime reads, so a character is a short Python script instead of hand-placed JSON.

    from avatarkit import Avatar
    av = Avatar(palette={"skin": "#ffe3d1"})
    av.material("skin", "toon", color="skin")
    av.node("root", "group")
    ...
    av.face(parent="head", head=((0, 0, 0), (0.5, 0.47, 0.46)))      # eyes, brows, mouths, cheeks, 12 expressions
    data = av.build()

Conventions (see pets/SPEC.md): +Y up, the character faces +Z, ground at y = 0, a character is about 1.5 tall.
"""
import math

EXPRESSIONS = ("neutral", "happy", "excited", "determined", "worried", "sad", "sleepy", "surprised",
               "confused", "dizzy", "yawn", "love")
EXPRESSION_PARTS = {
    "neutral": ["eye", "mouthSmile"],
    "happy": ["eyeHappy", "mouthOpen"],
    "excited": ["eyeBig", "mouthOpen"],
    "determined": ["eye", "browDet", "mouthFlat"],
    "worried": ["eye", "browWorry", "mouthFrown"],
    "sad": ["eye", "browWorry", "mouthFrown"],
    "sleepy": ["eyeSleep", "mouthFlat"],
    "surprised": ["eyeBig", "mouthO"],
    "confused": ["eye", "browWorry:L", "mouthFlat"],
    "dizzy": ["eyeX", "mouthFrown"],
    "yawn": ["eyeSleep", "mouthOpen"],
    "love": ["eyeHeart", "mouthSmile"],
}
SLOT_NAMES = ("root", "body", "head", "armL", "armR", "legL", "legR", "tail", "earL", "earR", "antenna", "mouth", "gauge",
              "prop", "shadow")


def _r(v):
    return round(v, 4)


def surface(ellipsoid, x, y, lift=0.004):
    """Point on an ellipsoid (center, radii) above (x, y), with the yaw/pitch that lays a +Z-facing decal flat on it."""
    (cx, cy, cz), (rx, ry, rz) = ellipsoid
    inside = 1 - (x / rx) ** 2 - (y / ry) ** 2
    if inside <= 0.02:
        raise ValueError("decal at (%.2f, %.2f) falls off the head surface" % (x, y))
    z = rz * math.sqrt(inside)
    n = (x / rx ** 2, y / ry ** 2, z / rz ** 2)
    length = math.sqrt(sum(c * c for c in n))
    n = tuple(c / length for c in n)
    yaw = math.asin(max(-1, min(1, n[0])))
    pitch = -math.asin(max(-1, min(1, n[1] / max(math.cos(yaw), 1e-6))))
    pos = [_r(cx + x + n[0] * lift), _r(cy + y + n[1] * lift), _r(cz + z + n[2] * lift)]
    return pos, [_r(math.degrees(pitch)), _r(math.degrees(yaw))]


class Avatar:
    def __init__(self, palette=None, outline=0.014, outline_color="$ink"):
        self.data = {"format": "agentmeter-avatar/1", "palette": dict(palette or {}), "materials": {},
                     "outline": {"enabled": outline > 0, "thickness": outline, "color": outline_color},
                     "nodes": [], "slots": {}, "face": {}, "props": {}, "anchors": {}}
        self.ids = set()

    # ---- data

    def palette(self, **colors):
        self.data["palette"].update(colors)
        return self

    def material(self, name, kind="toon", **kw):
        self.data["materials"][name] = dict(kind=kind, **kw)
        return name

    def node(self, id, type, parent=None, **kw):
        if id in self.ids:
            raise ValueError("duplicate node id %s" % id)
        if parent is not None and parent not in self.ids:
            raise ValueError("node %s: parent %s must be defined first" % (id, parent))
        self.ids.add(id)
        entry = {"id": id, "type": type}
        if parent is not None:
            entry["parent"] = parent
        entry.update({k: v for k, v in kw.items() if v is not None})
        self.data["nodes"].append(entry)
        return id

    def group(self, id, parent=None, **kw):
        return self.node(id, "group", parent, **kw)

    def slots(self, **mapping):
        self.data["slots"].update(mapping)
        return self

    def prop(self, name, **kw):
        self.data["props"][name] = kw
        return self

    def anchor(self, name, node, offset):
        self.data["anchors"][name] = {"node": node, "offset": list(offset)}
        return self

    def meter(self, node, colors=None):
        self.data["meter"] = {"node": node, "colors": colors or {
            "ok": "$accent1", "low": "$low", "critical": "$crit", "empty": "$crit", "unknown": "$unknown"}}
        return self

    def limb_pair(self, base, parent, xs, y, z, mesh_type, rest_z=6, **mesh):
        """Symmetric limbs: groups `<base>L`/`<base>R` at the joint with one mesh hanging below each."""
        for side, x, rz in (("L", -xs, -rest_z), ("R", xs, rest_z)):
            self.group(f"{base}{side}", parent, position=[x, y, z], rotation=[0, 0, rz])
            self.node(f"{base}{side}Mesh", mesh_type, f"{base}{side}", **mesh)

    # ---- face

    def face(self, parent="head", head=None, flat_z=None, eye_x=0.19, eye_y=0.06, eye_r=0.066, brow_dy=0.125,
             mouth_y=-0.1, cheeks=0.31, cheek_y=-0.04, glint=True, mats=None, eye_stretch=1.3):
        """Standard face: open/big/happy/sleepy/X/heart eyes, two brows, five mouths, optional cheeks.

        `head` is (center, radii) of the ellipsoid the decals lie on; `flat_z` puts them on a flat plate instead.
        Material names come from `mats` (ink, white, blush, tongue, heart) and must exist on the avatar.
        """
        m = {"ink": "ink", "white": "white", "blush": "blush", "tongue": "tongue", "heart": "heart"}
        m.update(mats or {})

        def place(x, y, lift=0.004):
            if flat_z is not None:
                return [x, y, flat_z + lift], [0, 0]
            return surface(head, x, y, lift)

        def decal(id, type, x, y, tilt=0, lift=0.004, hidden=True, material=None, **kw):
            pos, (pitch, yaw) = place(x, y, lift)
            return self.node(id, type, parent, position=pos, rotation=[pitch, yaw, tilt], material=material or m["ink"],
                             visible=False if hidden else None, outline=False, **kw)

        def eye_group(id, x, y, radius, glint_scale, hidden):
            pos, (pitch, yaw) = place(x, y, 0.004)
            self.group(id, parent, position=pos, rotation=[pitch, yaw, 0], visible=False if hidden else None)
            self.node(id + "Pupil", "disc", id, radius=radius, scale=[1, eye_stretch * 0.9, 1], material=m["ink"], outline=False)
            if glint:
                self.node(id + "Glint", "disc", id, radius=radius * 0.34, position=[radius * 0.3, radius * 0.6, 0.004],
                          material=m["white"], outline=False)

        for side, sx in (("L", -1), ("R", 1)):
            x = sx * eye_x
            eye_group(f"eye{side}", x, eye_y, eye_r, 1, False)
            eye_group(f"eyeBig{side}", x, eye_y, eye_r * 1.3, 1.2, True)
            decal(f"eyeHappy{side}", "ring", x, eye_y - 0.015, inner=eye_r * 0.64, outer=eye_r * 1.12, start=0, arc=180)
            decal(f"eyeSleep{side}", "ring", x, eye_y + 0.025, inner=eye_r * 0.55, outer=eye_r * 0.97, start=180, arc=180)
            pos, (pitch, yaw) = place(x, eye_y)
            self.group(f"eyeX{side}", parent, position=pos, rotation=[pitch, yaw, 0], visible=False)
            for tag, tilt in (("a", 45), ("b", -45)):
                self.node(f"eyeX{tag}{side}", "plane", f"eyeX{side}", size=[eye_r * 1.7, eye_r * 0.36], rotation=[0, 0, tilt],
                          material=m["ink"], outline=False)
            decal(f"eyeHeart{side}", "extrude", x, eye_y, material=m["heart"], shape="heart", size=eye_r * 1.15, depth=0.01, bevel=0.004)
            decal(f"browWorry{side}", "plane", x, eye_y + brow_dy, tilt=18 * -sx, size=[eye_r * 1.5, 0.022])
            decal(f"browDet{side}", "plane", x, eye_y + brow_dy - 0.01, tilt=16 * sx, size=[eye_r * 1.5, 0.022])
            if cheeks:
                decal(f"cheek{side}", "disc", sx * cheeks, cheek_y, hidden=False, material=m["blush"], radius=0.058)

        decal("mouthSmile", "ring", 0, mouth_y + 0.025, hidden=False, inner=0.034, outer=0.055, start=180, arc=180, scale=[1.3, 1, 1])
        pos, (pitch, yaw) = place(0, mouth_y - 0.015)
        self.group("mouthOpen", parent, position=pos, rotation=[pitch, yaw, 0], visible=False)
        self.node("mouthOpenBg", "disc", "mouthOpen", radius=0.058, scale=[1.15, 1.3, 1], material=m["ink"], outline=False)
        self.node("mouthTongue", "disc", "mouthOpen", radius=0.032, position=[0, -0.034, 0.003], scale=[1.3, 0.8, 1], material=m["tongue"], outline=False)
        decal("mouthFlat", "plane", 0, mouth_y - 0.015, size=[0.095, 0.02])
        decal("mouthFrown", "ring", 0, mouth_y - 0.05, inner=0.03, outer=0.05, start=0, arc=180, scale=[1.2, 1, 1])
        decal("mouthO", "disc", 0, mouth_y - 0.02, radius=0.036)

        expressions = {}
        managed = set()
        for name, parts in EXPRESSION_PARTS.items():
            show = []
            for part in parts:
                base, _, only = part.partition(":")
                for side in (only,) if only else ("L", "R") if not base.startswith("mouth") else ("",):
                    show.append(base + side)
            expressions[name] = {"show": show}
            managed.update(show)
        self.data["face"] = {
            "blink": ["eyeL", "eyeR"],
            "look": [{"node": "eyeL", "range": [0.03, 0.022]}, {"node": "eyeR", "range": [0.03, 0.022]}],
            "managed": sorted(managed), "expressions": expressions,
        }
        return self

    def build(self):
        d = self.data
        d["slots"].setdefault("root", "root")
        for slot, node in d["slots"].items():
            if slot not in SLOT_NAMES:
                raise ValueError("unknown slot %s" % slot)
            if node not in self.ids:
                raise ValueError("slot %s points at unknown node %s" % (slot, node))
        return d
