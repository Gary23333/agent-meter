#!/usr/bin/env python3
"""Starter for a new three.js pet: a round creature with a face, two arms, two feet and an antenna.

    python3 .claude/skills/agentmeter-pet-three/templates/new_character.py --id my-pet --name 小宠 \
        --body "#ffd6a5" --limb "#f4a261" --accent "#e76f51"

Copy this file next to your notes, change the shapes, run it again (it overwrites its own output), and keep going
until the contact sheet looks right. Valid out of the box: validate -> sheet -> iterate.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "pets" / "tools"))
from avatarkit import Avatar  # noqa: E402


def build(pid, name, body, limb, accent):
    av = Avatar(palette={"body": body, "limb": limb, "accent": accent}, outline_color="$ink")
    # Face materials (every face needs these five) and a soft ground shadow.
    av.palette(ink="$ink", white="#ffffff", blush="#ff8fb1", tongue="#ff6f91")
    av.material("ink", "basic", color="ink", decal=True)
    av.material("white", "basic", color="white", decal=True)
    av.material("blush", "basic", color="blush", opacity=0.55, decal=True)
    av.material("tongue", "basic", color="tongue", decal=True)
    av.material("heart", "basic", color="#ff5c8a", decal=True)
    av.material("shadow", "basic", color="#000000", opacity=0.28, texture="softdot")
    # Your colours: toon = cel shading. Use "$accent1" (theme colour) for anything that should follow the interface style.
    av.material("body", "toon", color="body", steps=3)
    av.material("limb", "toon", color="limb", steps=3)
    av.material("glow", "standard", color="accent", emissive="accent", emissiveIntensity=0.6, glow=True, roughness=0.4)

    av.group("root")                                                    # everything hangs off root; its feet are at y = 0
    av.node("shadow", "disc", "root", radius=0.62, position=[0, 0.004, 0], rotation=[-90, 0, 0], scale=[1, 0.8, 1],
            material="shadow", outline=False)
    av.group("body", "root", position=[0, 0.62, 0])                     # body = squash / breathing target
    av.node("shell", "sphere", "body", radius=0.5, scale=[1, 0.94, 0.92], segments=[40, 28], material="body")
    av.group("head", "body")                                            # head = nod / turn target; the face lives here
    av.face("head", head=((0, 0, 0), (0.5, 0.47, 0.46)), eye_x=0.19, eye_y=0.06, mouth_y=-0.1, cheeks=0.31)
    av.limb_pair("arm", "root", 0.5, 0.58, 0.04, "capsule", rest_z=6, radius=0.075, length=0.16, position=[0, -0.16, 0], material="limb")
    for side, x in (("L", -0.2), ("R", 0.2)):
        av.group(f"leg{side}", "root", position=[x, 0.13, 0.08])
        av.node(f"leg{side}Mesh", "sphere", f"leg{side}", radius=0.12, scale=[1, 0.62, 1.25], position=[0, -0.05, 0.04], material="limb")
    av.group("antenna", "root", position=[0, 1.07, 0])
    av.node("stalk", "cylinder", "antenna", radiusTop=0.012, radiusBottom=0.014, height=0.2, position=[0, 0.1, 0], material="ink", outline=False)
    av.node("tip", "sphere", "antenna", radius=0.05, position=[0, 0.24, 0], material="glow", outline=False)

    av.slots(root="root", body="body", head="head", armL="armL", armR="armR", legL="legL", legR="legR", antenna="antenna",
             shadow="shadow", mouth="mouthOpen")
    # Props appear when a state asks for them: laptop (working), sign (alert), plug (offline), brush (painting), ...
    av.prop("laptop", parent="root", position=[0, 0.1, 0.7], rotation=[0, -14, 0], scale=0.8)
    av.prop("sign", parent="root", position=[0.8, 0.28, 0.1], scale=0.95)
    av.prop("plug", parent="root", position=[0, 0, 0.1])
    av.prop("brush", parent="armR", position=[0, -0.3, 0.06], rotation=[-70, 0, 0], scale=0.8)
    av.prop("headphones", parent="body", position=[0, 0.02, 0], scale=1.58)
    av.prop("crystal", parent="root", position=[0.78, 0, 0.28])
    av.anchor("head", "body", [0.12, 0.55, 0.1]).anchor("body", "body", [0, 0, 0.3]).anchor("prop", "armR", [0, -0.3, 0.2]) \
        .anchor("root", "root", [0, 0.05, 0])

    meta = {
        "format": "agentmeter-pet/1", "id": pid, "name": name, "name_en": pid, "version": "0.1.0", "author": "you", "license": "CC0-1.0",
        "description": "我的第一个桌宠，请改写这句话。", "renderer": "three",
        "stage": {"width": 240, "height": 260, "ground": 0.9},
        "three": {"avatar": "avatar.json", "camera": {"fov": 28, "position": [0, 0.9, 5.3], "target": [0, 0.82, 0]}, "lights": "soft"},
        "states": {},                      # per-animation overrides go here, e.g. {"eating": {"show": ["fish"]}}
        "voice": {"idle": ["你好呀～"], "working": ["在干活，别催。"], "alarm": ["额度告急！"]},
    }
    return meta, av.build()


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--id", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--body", default="#ffd6a5")
    p.add_argument("--limb", default="#f4a261")
    p.add_argument("--accent", default="#e76f51")
    p.add_argument("--out", type=Path, help="default: pets/presets/<id>")
    args = p.parse_args()
    meta, avatar = build(args.id, args.name, args.body, args.limb, args.accent)
    out = args.out or ROOT / "pets" / "presets" / args.id
    out.mkdir(parents=True, exist_ok=True)
    (out / "pet.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n")
    (out / "avatar.json").write_text(json.dumps(avatar, ensure_ascii=False, indent=1) + "\n")
    print("wrote", out)


if __name__ == "__main__":
    main()
