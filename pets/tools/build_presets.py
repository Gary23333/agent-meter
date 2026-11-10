#!/usr/bin/env python3
"""Regenerates the built-in three.js presets (pets/presets/<id>/{pet,avatar}.json) from avatarkit.

    python3 pets/tools/build_presets.py            # all presets
    python3 pets/tools/build_presets.py cat bot    # only these

The JSON is the deliverable the runtime reads; this script is the readable source of it. To make your own
character, copy one function, change the shapes and palette, and validate with petpack.py.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from avatarkit import Avatar, surface  # noqa: E402

PRESETS = Path(__file__).resolve().parents[1] / "presets"
SOFT = {"fov": 28, "position": [0, 0.9, 5.3], "target": [0, 0.82, 0]}


def decals(av, ink="$ink", blush="#ff8fb1", tongue="#ff6f91"):
    """Materials every face needs, plus the soft ground shadow."""
    av.palette(ink=ink, white="#ffffff", blush=blush, tongue=tongue)
    av.material("ink", "basic", color="ink", decal=True)
    av.material("white", "basic", color="white", decal=True)
    av.material("blush", "basic", color="blush", opacity=0.55, decal=True)
    av.material("tongue", "basic", color="tongue", decal=True)
    av.material("heart", "basic", color="#ff5c8a", decal=True)
    av.material("shadow", "basic", color="#000000", opacity=0.28, texture="softdot")


def shadow(av, radius=0.62):
    av.node("shadow", "disc", "root", radius=radius, position=[0, 0.004, 0], rotation=[-90, 0, 0], scale=[1, 0.8, 1],
            material="shadow", outline=False)


def pack(id, name, name_en, description, voice, states=None, camera=None, lights="soft", stage=None):
    return {
        "format": "agentmeter-pet/1", "id": id, "name": name, "name_en": name_en, "version": "1.0.0",
        "author": "AgentMeter", "license": "MIT", "description": description, "renderer": "three",
        "stage": stage or {"width": 240, "height": 260, "ground": 0.9},
        "three": {"avatar": "avatar.json", "camera": camera or SOFT, "lights": lights},
        "states": states or {}, "voice": voice,
    }


# --------------------------------------------------------------------------------------------- gauge

def gauge():
    av = Avatar(palette={"shell": "#f3efff", "limb": "#cdbfff", "accent": "$accent1"})
    decals(av)
    av.material("shell", "toon", color="shell", steps=3)
    av.material("limb", "toon", color="limb", steps=3)
    av.material("star", "standard", color="accent", emissive="accent", emissiveIntensity=0.55, glow=True, roughness=0.4)
    av.material("ring", "standard", color="accent", emissive="accent", emissiveIntensity=0.8, glow=True, roughness=0.5)
    av.material("track", "basic", color="ink", opacity=0.14)
    av.group("root")
    shadow(av)
    arc = dict(radius=0.98, tube=0.05, start=225, sweep=270, segments=[8, 96], outline=False)
    av.node("ringTrack", "arc", "root", position=[0, 0.86, -0.34], material="track", **arc)
    av.node("ring", "arc", "root", position=[0, 0.86, -0.3], material="ring", **arc)
    av.group("body", "root", position=[0, 0.62, 0])
    av.node("shell", "sphere", "body", radius=0.5, scale=[1, 0.94, 0.92], segments=[40, 28], material="shell")
    av.group("head", "body")
    av.face("head", head=((0, 0, 0), (0.5, 0.47, 0.46)), eye_x=0.19, eye_y=0.06, brow_dy=0.125, mouth_y=-0.1, cheeks=0.31)
    av.limb_pair("arm", "root", 0.5, 0.58, 0.04, "capsule", rest_z=6, radius=0.075, length=0.16, position=[0, -0.16, 0], material="limb")
    for side, x in (("L", -0.2), ("R", 0.2)):
        av.group(f"leg{side}", "root", position=[x, 0.13, 0.08])
        av.node(f"leg{side}Mesh", "sphere", f"leg{side}", radius=0.12, scale=[1, 0.62, 1.25], position=[0, -0.05, 0.04], material="limb")
    av.group("antenna", "root", position=[0, 1.07, 0])
    av.node("stalk", "cylinder", "antenna", radiusTop=0.012, radiusBottom=0.014, height=0.2, position=[0, 0.1, 0], material="ink", outline=False)
    av.node("star", "extrude", "antenna", shape={"kind": "star", "points": 4, "inner": 0.4}, size=0.11, depth=0.07, bevel=0.012,
            position=[0, 0.27, 0], material="star", outline=False)
    av.slots(root="root", body="body", head="head", armL="armL", armR="armR", legL="legL", legR="legR", antenna="antenna",
             gauge="ring", shadow="shadow", mouth="mouthOpen")
    av.meter("ring")
    av.prop("laptop", parent="root", position=[0, 0.1, 0.7], rotation=[0, -14, 0], scale=0.8)
    av.prop("sign", parent="root", position=[0.8, 0.28, 0.1], scale=0.95)
    av.prop("plug", parent="root", position=[0, 0, 0.1])
    av.prop("brush", parent="armR", position=[0, -0.3, 0.06], rotation=[-70, 0, 0], scale=0.8)
    av.prop("headphones", parent="body", position=[0, 0.02, 0], scale=1.58)
    av.prop("crystal", parent="root", position=[0.78, 0, 0.28])
    av.anchor("head", "body", [0.12, 0.55, 0.1]).anchor("body", "body", [0, 0, 0.3]).anchor("prop", "armR", [0, -0.3, 0.2]) \
        .anchor("root", "root", [0, 0.05, 0])
    meta = pack("gauge", "量量", "Gauge",
                "圆滚滚的小仪表兽。身后的圆环就是你正在用的额度：满格是主题色，见底会变橙变红；脸盘会跟着心情和光标转。",
                {"idle": ["圆环满满，心情不错～", "我一直在盯着额度。", "戳我可以看摘要哦。"],
                 "working": ["圆环转起来！", "Agent 干活，我值班。", "叮叮当当，敲得好快。"],
                 "tired": ["圆环缩了一圈……", "电量有点低了。"], "alarm": ["红圈了红圈了！", "快没电啦！！"],
                 "exhausted": ["圆环空了……", "我先躺平，等重置。"], "celebrate": ["圆环回满！", "耶～满格！"],
                 "sleeping": ["Zzz……圆环也在休息。"]})
    return meta, av.build()


# ---------------------------------------------------------------------------------------------- blob

def blob():
    av = Avatar(palette={"gel": "#7ee8c7", "gelDark": "#4fcfa8", "leaf": "#4fbf6a"}, outline_color="#1f6b57")
    decals(av, ink="#17463a", blush="#ff9fb8")
    av.material("gel", "toon", color="gel", steps=3)
    av.material("gelDark", "toon", color="gelDark", steps=3)
    av.material("leaf", "toon", color="leaf", steps=3)
    av.material("shine", "basic", color="#ffffff", opacity=0.6, decal=True)
    av.group("root")
    shadow(av, 0.74)
    av.group("body", "root", position=[0, 0.5, 0])
    av.node("shell", "sphere", "body", radius=0.62, scale=[1.12, 0.86, 1.0], segments=[44, 30], material="gel")
    ellipsoid = ((0, 0, 0), (0.694, 0.533, 0.62))
    for id, (x, y), radius, scale, tilt in (("shine1", (-0.3, 0.27), 0.1, [1, 0.55, 1], 35), ("shine2", (-0.16, 0.36), 0.04, [1, 1, 1], 0)):
        pos, (pitch, yaw) = surface(ellipsoid, x, y, 0.006)
        av.node(id, "disc", "body", radius=radius, scale=scale, position=pos, rotation=[pitch, yaw, tilt], material="shine", outline=False)
    av.group("head", "body")
    av.face("head", head=ellipsoid, eye_x=0.22, eye_y=0.1, eye_r=0.075, brow_dy=0.13, mouth_y=-0.1, cheeks=0.4, cheek_y=-0.06)
    av.limb_pair("arm", "root", 0.64, 0.5, 0.06, "sphere", rest_z=16, radius=0.11, scale=[1, 1.25, 1], position=[0, -0.07, 0], material="gelDark")
    av.group("antenna", "root", position=[0, 0.99, 0])
    av.node("stalk", "cylinder", "antenna", radiusTop=0.014, radiusBottom=0.02, height=0.22, position=[0, 0.11, 0], material="leaf", outline=False)
    for side, tilt in (("L", 38), ("R", -38)):
        av.group(f"leaf{side}", "antenna", position=[0, 0.22, 0], rotation=[0, 0, tilt])
        av.node(f"leaf{side}Mesh", "extrude", f"leaf{side}", shape="drop", size=0.13, depth=0.03, bevel=0.008, position=[0, 0.1, 0],
                scale=[0.8, 1, 1], material="leaf", outline=False)
    av.slots(root="root", body="body", head="head", armL="armL", armR="armR", antenna="antenna", shadow="shadow", mouth="mouthOpen")
    av.prop("laptop", parent="root", position=[0, 0.08, 0.74], rotation=[0, -14, 0], scale=0.85)
    av.prop("sign", parent="root", position=[0.92, 0.28, 0.12], scale=0.95)
    av.prop("plug", parent="root", position=[0, 0, 0.1])
    av.prop("brush", parent="armR", position=[0, -0.17, 0.06], rotation=[-70, 0, 0], scale=0.8)
    av.prop("headphones", parent="body", position=[0, 0.08, 0], scale=1.9)
    av.prop("crystal", parent="root", position=[0.9, 0, 0.3])
    av.anchor("head", "body", [0.1, 0.56, 0.1]).anchor("body", "body", [0, 0, 0.35]).anchor("prop", "armR", [0, -0.2, 0.2]) \
        .anchor("root", "root", [0, 0.05, 0])
    meta = pack("blob", "团团", "Blobby",
                "果冻史莱姆：挤压拉伸特别夸张，额度耗尽时会化成一滩，回血时 Q 弹地蹦起来。",
                {"idle": ["Q 弹 Q 弹～", "我是软的，不是硬的。"], "working": ["咕叽咕叽，在干活。", "我也想帮忙！"],
                 "tired": ["有点瘫……", "要化了……"], "alarm": ["我要化啦！！"], "exhausted": ["已化成一滩。"],
                 "celebrate": ["蹦蹦蹦！", "回血啦！"], "sleeping": ["（咕嘟咕嘟）"]},
                states={"exhausted": {"pose": {"root": {"pos": [0, -0.1, 0], "scl": [1.4, 0.5, 1.4]}}},
                        "tired": {"pose": {"root": {"scl": [1.08, 0.9, 1.08]}}},
                        "celebrate": {"scale": {"amp": 1.25, "speed": 1.0}}})
    return meta, av.build()


# ----------------------------------------------------------------------------------------------- bot

def bot():
    av = Avatar(palette={"shell": "#eef3ff", "trim": "#c4cee8", "plate": "#171b30", "glow": "$accent2", "accent": "$accent1"},
                outline_color="#2a3358")
    decals(av, ink="$accent2", tongue="$accent1")
    av.material("ink", "basic", color="glow", decal=True)           # on a robot the "ink" of the face is light
    av.material("shell", "toon", color="shell", steps=3)
    av.material("trim", "toon", color="trim", steps=3)
    av.material("plate", "basic", color="plate")
    av.material("tip", "standard", color="accent", emissive="accent", emissiveIntensity=0.7, glow=True, roughness=0.4)
    av.material("meter", "standard", color="accent", emissive="accent", emissiveIntensity=0.9, glow=True, roughness=0.5)
    av.material("track", "basic", color="#ffffff", opacity=0.18)
    av.group("root")
    shadow(av, 0.55)
    av.group("body", "root", position=[0, 0.45, 0])
    av.node("torso", "box", "body", size=[0.56, 0.5, 0.44], round=0.09, material="shell")
    av.node("chestPlate", "box", "body", size=[0.3, 0.2, 0.02], round=0.02, position=[0, 0.02, 0.225], material="plate", outline=False)
    arc = dict(radius=0.075, tube=0.014, start=180, sweep=180, segments=[6, 48], outline=False)
    av.node("chestTrack", "arc", "body", position=[0, -0.02, 0.24], material="track", **arc)
    av.node("chestMeter", "arc", "body", position=[0, -0.02, 0.245], material="meter", **arc)
    av.group("head", "root", position=[0, 1.0, 0])
    av.node("skull", "box", "head", size=[0.84, 0.66, 0.62], round=0.16, material="shell")
    av.node("visor", "box", "head", size=[0.66, 0.44, 0.04], round=0.08, position=[0, 0.0, 0.31], material="plate", outline=False)
    av.face("head", flat_z=0.332, eye_x=0.17, eye_y=0.035, eye_r=0.058, brow_dy=0.115, mouth_y=-0.12, cheeks=0, glint=False,
            mats={"white": "ink"})
    for side, x in (("L", -0.45), ("R", 0.45)):
        av.group(f"ear{side}", "head", position=[x, 0, 0])
        av.node(f"ear{side}Mesh", "cylinder", f"ear{side}", radiusTop=0.12, radiusBottom=0.12, height=0.08, rotation=[0, 0, 90], material="trim")
    av.group("antenna", "head", position=[0, 0.33, 0])
    av.node("stalk", "cylinder", "antenna", radiusTop=0.012, radiusBottom=0.014, height=0.16, position=[0, 0.08, 0], material="trim", outline=False)
    av.node("tip", "sphere", "antenna", radius=0.05, position=[0, 0.19, 0], material="tip", outline=False)
    av.limb_pair("arm", "root", 0.37, 0.64, 0.0, "capsule", rest_z=8, radius=0.06, length=0.14, position=[0, -0.12, 0], material="trim")
    for side in ("L", "R"):
        av.node(f"arm{side}Hand", "sphere", f"arm{side}", radius=0.075, position=[0, -0.28, 0], material="shell")
    for side, x in (("L", -0.15), ("R", 0.15)):
        av.group(f"leg{side}", "root", position=[x, 0.2, 0])
        av.node(f"leg{side}Post", "cylinder", f"leg{side}", radiusTop=0.07, radiusBottom=0.07, height=0.1, position=[0, -0.03, 0], material="trim")
        av.node(f"leg{side}Foot", "box", f"leg{side}", size=[0.2, 0.08, 0.3], round=0.035, position=[0, -0.13, 0.05], material="shell")
    av.slots(root="root", body="body", head="head", armL="armL", armR="armR", legL="legL", legR="legR", earL="earL", earR="earR",
             antenna="antenna", gauge="chestMeter", shadow="shadow", mouth="mouthOpen")
    av.meter("chestMeter")
    av.prop("laptop", parent="root", position=[0, 0.08, 0.62], rotation=[0, -14, 0], scale=0.8)
    av.prop("sign", parent="root", position=[0.78, 0.28, 0.1], scale=0.95)
    av.prop("plug", parent="root", position=[0, 0, 0.1])
    av.prop("brush", parent="armR", position=[0, -0.3, 0.06], rotation=[-70, 0, 0], scale=0.8)
    av.prop("headphones", parent="head", position=[0, 0, 0], scale=1.27)
    av.prop("crystal", parent="root", position=[0.76, 0, 0.28])
    av.anchor("head", "head", [0.12, 0.5, 0.1]).anchor("body", "body", [0, 0, 0.3]).anchor("prop", "armR", [0, -0.3, 0.2]) \
        .anchor("root", "root", [0, 0.05, 0])
    meta = pack("bot", "码码", "Codey",
                "戴屏幕脸的小机器人：胸口的小表盘是额度，开心时眼睛是 ^ ^，干活时敲键盘敲得飞快。",
                {"idle": ["系统运行正常。", "待命中……滴。", "胸口表盘一切正常。"], "working": ["编译中，请勿打扰。", "键盘已过热（假的）。"],
                 "tired": ["电量偏低。", "进入省电模式……"], "alarm": ["警告！电量不足！"], "exhausted": ["电量耗尽。关机。"],
                 "celebrate": ["任务完成！", "耶，运行成功。"], "sleeping": ["待机……"], "offline": ["连接断开。重连中……"]},
                camera={"fov": 28, "position": [0, 0.95, 5.4], "target": [0, 0.82, 0]})
    return meta, av.build()


# ----------------------------------------------------------------------------------------------- cat

def cat():
    av = Avatar(palette={"fur": "#ffb36b", "furDark": "#e58f45", "cream": "#fff1de", "inner": "#ff9aa8", "stripe": "#c96f2d"},
                outline_color="#5a3318")
    decals(av, ink="#2e1b10", blush="#ff8a8a", tongue="#ff7f94")
    av.material("fur", "toon", color="fur", steps=3)
    av.material("furDark", "toon", color="furDark", steps=3)
    av.material("cream", "toon", color="cream", steps=3)
    av.material("inner", "toon", color="inner", steps=3)
    av.material("stripe", "basic", color="stripe", decal=True)
    av.material("nose", "basic", color="#ff8fa3", decal=True)
    av.material("whisker", "basic", color="#6b4a33", decal=True)
    av.group("root")
    shadow(av, 0.62)
    av.group("body", "root", position=[0, 0.38, 0])
    av.node("torso", "sphere", "body", radius=0.4, scale=[1, 0.92, 0.95], segments=[32, 22], material="fur")
    av.node("belly", "sphere", "body", radius=0.27, scale=[1, 1, 0.6], position=[0, -0.02, 0.26], segments=[24, 16], material="cream", outline=False)
    av.group("head", "root", position=[0, 0.98, 0])
    ellipsoid = ((0, 0, 0), (0.56, 0.46, 0.475))
    av.node("skull", "sphere", "head", radius=0.5, scale=[1.12, 0.92, 0.95], segments=[40, 28], material="fur")
    for side, x, tilt in (("L", -0.3, 14), ("R", 0.3, -14)):
        av.group(f"ear{side}", "head", position=[x, 0.36, 0], rotation=[0, 0, tilt])
        av.node(f"ear{side}Mesh", "cone", f"ear{side}", radius=0.17, height=0.3, position=[0, 0.13, 0], segments=[4], material="fur")
        av.node(f"ear{side}In", "cone", f"ear{side}", radius=0.1, height=0.2, position=[0, 0.11, 0.045], segments=[4], material="inner", outline=False)
    av.face("head", head=ellipsoid, eye_x=0.2, eye_y=0.04, eye_r=0.07, brow_dy=0.13, mouth_y=-0.13, cheeks=0.36, cheek_y=-0.07)
    pos, (pitch, yaw) = surface(ellipsoid, 0, -0.06, 0.006)
    av.node("nose", "disc", "head", radius=0.032, scale=[1.2, 0.8, 1], position=pos, rotation=[pitch, yaw, 0], material="nose", outline=False)
    for side, sx in (("L", -1), ("R", 1)):
        for k, dy in enumerate((0.0, -0.035, -0.07)):
            pos, (pitch, yaw) = surface(ellipsoid, sx * 0.39, -0.09 + dy * 0.7, 0.006)
            av.node(f"whisker{side}{k}", "plane", "head", size=[0.2, 0.008], position=pos, rotation=[pitch, yaw, sx * (8 - k * 8)],
                    material="whisker", outline=False)
    for k, x in enumerate((-0.11, 0.0, 0.11)):
        pos, (pitch, yaw) = surface(ellipsoid, x, 0.3 - (0.02 if k == 1 else 0), 0.006)
        av.node(f"stripe{k}", "box", "head", size=[0.04, 0.1 if k == 1 else 0.08, 0.004], round=0.015, position=pos,
                rotation=[pitch, yaw, (k - 1) * -14], material="stripe", outline=False)
    av.limb_pair("arm", "root", 0.27, 0.5, 0.2, "capsule", rest_z=4, radius=0.075, length=0.1, position=[0, -0.1, 0], material="fur")
    for side, x in (("L", -0.2), ("R", 0.2)):
        av.group(f"leg{side}", "root", position=[x, 0.1, 0.12])
        av.node(f"leg{side}Mesh", "sphere", f"leg{side}", radius=0.12, scale=[1, 0.6, 1.25], position=[0, -0.04, 0.04], material="furDark")
    av.group("tail", "root", position=[0, 0.3, -0.32])
    av.node("tailMesh", "tube", "tail", path=[[0, 0, 0], [0, 0.08, -0.16], [0, 0.3, -0.24], [0, 0.52, -0.18]], radius=0.06, segments=[10, 20], material="fur")
    av.node("tailTip", "sphere", "tail", radius=0.07, position=[0, 0.54, -0.17], material="furDark", outline=False)
    av.slots(root="root", body="body", head="head", armL="armL", armR="armR", legL="legL", legR="legR", tail="tail", earL="earL",
             earR="earR", shadow="shadow", mouth="mouthOpen")
    av.prop("laptop", parent="root", position=[0, 0.08, 0.62], rotation=[0, -14, 0], scale=0.8)
    av.prop("sign", parent="root", position=[0.78, 0.28, 0.1], scale=0.95)
    av.prop("plug", parent="root", position=[0, 0, 0.1])
    av.prop("brush", parent="armR", position=[0, -0.2, 0.06], rotation=[-70, 0, 0], scale=0.8)
    av.prop("headphones", parent="head", position=[0, 0.0, 0], scale=1.62)
    av.prop("crystal", parent="root", position=[0.76, 0, 0.28])
    av.prop("fish", parent="root", position=[0.42, 0.12, 0.45], rotation=[0, -30, 0], scale=1.1)
    av.anchor("head", "head", [0.14, 0.5, 0.1]).anchor("body", "body", [0, 0, 0.35]).anchor("prop", "armR", [0, -0.2, 0.2]) \
        .anchor("root", "root", [0, 0.05, 0])
    meta = pack("cat", "缓存猫", "Cache Cat",
                "抱着小鱼（缓存命中）的橘猫：token 一多就开吃，尾巴会跟着心情摇；睡着时会蜷成一团。",
                {"idle": ["喵～", "缓存命中率，我最关心。", "摸摸我？"], "working": ["敲键盘比抓老鼠有趣。", "喵喵，代码在跑。"],
                 "tired": ["没力气抓鱼了……", "喵呜……饿。"], "alarm": ["额度喵喵叫！！"], "exhausted": ["躺平，等重置，喵。"],
                 "eating": ["吃 token 吃 token！", "嚼嚼嚼～"], "celebrate": ["喵！满血！", "撒花喵～"], "sleeping": ["呼噜呼噜……"]},
                states={"eating": {"show": ["fish"]}})
    return meta, av.build()


# ---------------------------------------------------------------------------------------------- tibo

def tibo():
    av = Avatar(palette={"skin": "#ffe3d1", "hair": "#756bfa", "shirt": "#33d1cc", "pants": "#5c579e", "shoe": "#2b2660"},
                outline_color="#292457")
    decals(av, ink="#292457", blush="#ff7a9e", tongue="#e0527a")
    for name in ("skin", "hair", "shirt", "pants", "shoe"):
        av.material(name, "toon", color=name, steps=3)
    av.group("root")
    shadow(av, 0.55)
    av.group("body", "root", position=[0, 0.5, 0])
    av.node("torso", "sphere", "body", radius=0.26, scale=[1, 1.15, 0.85], segments=[28, 20], material="shirt")
    av.node("badge", "disc", "body", radius=0.045, position=[0, 0.06, 0.215], material="white", outline=False)
    av.group("head", "root", position=[0, 1.03, 0])
    ellipsoid = ((0, 0, 0), (0.46, 0.44, 0.44))
    av.node("skull", "sphere", "head", radius=0.46, scale=[1, 0.96, 0.96], segments=[40, 28], material="skin")
    av.node("hairCap", "sphere", "head", radius=0.5, scale=[1.04, 1.0, 1.0], position=[0, 0.075, -0.075], segments=[40, 28], material="hair")
    for i, (x, y, z, tilt) in enumerate(((-0.2, 0.29, 0.34, 18), (0.0, 0.33, 0.37, 0), (0.2, 0.29, 0.34, -18))):
        av.node(f"fringe{i}", "cone", "head", radius=0.1, height=0.2, segments=[12], position=[x, y, z], rotation=[160, 0, tilt], material="hair")
    for side, x in (("L", -0.45), ("R", 0.45)):
        av.group(f"ear{side}", "head", position=[x, -0.02, 0])
        av.node(f"ear{side}Mesh", "sphere", f"ear{side}", radius=0.08, scale=[0.6, 1, 0.8], material="skin")
    av.face("head", head=ellipsoid, eye_x=0.17, eye_y=-0.03, eye_r=0.07, brow_dy=0.14, mouth_y=-0.2, cheeks=0.3, cheek_y=-0.13)
    av.group("antenna", "head", position=[0, 0.55, -0.02])
    av.node("ahoge", "extrude", "antenna", shape="drop", size=0.11, depth=0.03, bevel=0.008, position=[0, 0.07, 0], material="hair", outline=False)
    av.limb_pair("arm", "root", 0.31, 0.64, 0.0, "capsule", rest_z=8, radius=0.065, length=0.12, position=[0, -0.12, 0], material="shirt")
    for side in ("L", "R"):
        av.node(f"arm{side}Hand", "sphere", f"arm{side}", radius=0.07, position=[0, -0.27, 0], material="skin")
    for side, x in (("L", -0.12), ("R", 0.12)):
        av.group(f"leg{side}", "root", position=[x, 0.25, 0])
        av.node(f"leg{side}Mesh", "capsule", f"leg{side}", radius=0.075, length=0.08, position=[0, -0.07, 0], material="pants")
        av.node(f"leg{side}Shoe", "sphere", f"leg{side}", radius=0.1, scale=[1, 0.65, 1.4], position=[0, -0.2, 0.05], material="shoe")
    av.slots(root="root", body="body", head="head", armL="armL", armR="armR", legL="legL", legR="legR", earL="earL", earR="earR",
             antenna="antenna", shadow="shadow", mouth="mouthOpen")
    av.prop("laptop", parent="root", position=[0, 0.1, 0.55], rotation=[0, -14, 0], scale=0.75)
    av.prop("resetter", parent="root", position=[0.62, 0, 0.22], rotation=[0, -25, 0], scale=1.1)
    av.prop("sign", parent="root", position=[0.74, 0.28, 0.1], scale=0.95)
    av.prop("plug", parent="root", position=[0, 0, 0.1])
    av.prop("brush", parent="armR", position=[0, -0.27, 0.06], rotation=[-70, 0, 0], scale=0.8)
    av.prop("headphones", parent="head", position=[0, 0.04, 0], scale=1.4)
    av.prop("crystal", parent="root", position=[-0.7, 0, 0.25])
    av.anchor("head", "head", [0.12, 0.55, 0.1]).anchor("body", "body", [0, 0, 0.3]).anchor("prop", "armR", [0, -0.27, 0.2]) \
        .anchor("root", "root", [0, 0.05, 0])
    meta = pack("tibo", "Tibo", "Tibo",
                "App 里「重置预测」页那位 Q 版吉祥物的 3D 版（沿用同一套配色）：期待重置时会抱出重置器，真的重置了就按下红按钮。",
                {"idle": ["重置什么时候来呢～", "今天也盯着额度。"], "working": ["在干活，别催。", "敲敲敲。"],
                 "excited": ["听说要重置了！", "重置器已就位！"], "celebrate": ["重置啦！！", "按下去了！"],
                 "tired": ["额度见底了……"], "alarm": ["红灯！红灯！"], "sleeping": ["（梦见额度满格）"]},
                states={"excited": {"show": ["resetter"]}, "celebrate": {"show": ["resetter"]}})
    return meta, av.build()


BUILDERS = {"gauge": gauge, "blob": blob, "bot": bot, "cat": cat, "tibo": tibo}


def main(argv):
    wanted = argv or list(BUILDERS)
    for id in wanted:
        if id not in BUILDERS:
            raise SystemExit("unknown preset %s (known: %s)" % (id, ", ".join(BUILDERS)))
        meta, avatar = BUILDERS[id]()
        directory = PRESETS / id
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "pet.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n")
        (directory / "avatar.json").write_text(json.dumps(avatar, ensure_ascii=False, indent=1) + "\n")
        print("%-6s %3d nodes  %5d bytes" % (id, len(avatar["nodes"]), (directory / "avatar.json").stat().st_size))


if __name__ == "__main__":
    main(sys.argv[1:])
