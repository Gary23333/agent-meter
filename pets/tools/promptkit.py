#!/usr/bin/env python3
"""Prompts for building a sprite pet with an image-generation model (stdlib only).

    promptkit.py --name 麻薯 --bible "a round white mochi dumpling with tiny dot eyes, pink cheeks, a green leaf on top" \\
                 --style flat --out work/mochi/prompts

Writes one prompt file per step plus index.json, which also holds the exact spritekit command that post-processes
each result. The recipe that makes characters stay consistent: first generate ONE reference image from the
character bible, then pass that image as the reference for every state strip, and repeat the bible verbatim.
"""
import argparse
import json
import sys
from pathlib import Path

KEYS = {"green": ("#00FF00", "pure green"), "magenta": ("#FF00FF", "pure magenta"), "blue": ("#0000FF", "pure blue")}

STYLES = {
    "flat": ("flat sticker illustration, one uniform dark outline, solid colour fills with a single soft shade, clean vector look",
             "扁平贴纸插画：统一粗细的深色描边，纯色块 + 一层柔和阴影"),
    "chibi3d": ("cute chibi 3D render, soft clay material, rounded forms, soft studio lighting, subtle rim light",
                "Q 版 3D 渲染：软陶质感，圆润，柔和棚拍光"),
    "pixel": ("pixel art sprite, 32x32 pixel character, limited 16-colour palette, hard pixel edges, no anti-aliasing, no dithering",
              "像素画：32×32，16 色，硬边，无抗锯齿"),
    "watercolor": ("soft watercolour illustration, gentle pigment gradients, thin ink linework, paper-free clean cut-out",
                   "柔和水彩：淡彩渐变 + 细墨线，干净抠图"),
}

# state -> (frames, one-line meaning, per-frame beats). Beats are what changes between frames.
STATES = {
    "idle": (4, "standing calmly, breathing", ["neutral standing pose, eyes open", "slight inhale: body 3% taller, arms lifted a hair",
                                              "neutral standing pose, eyes open", "slight exhale: body 3% shorter, a soft blink"]),
    "working": (4, "typing on a small laptop, focused", ["looking down at the laptop, left hand pressed, right hand raised",
                                                         "right hand pressed, left hand raised, head slightly forward",
                                                         "both hands raised, eyes bright", "left hand pressed, right hand raised, small smile"]),
    "tired": (3, "low on energy, drooping", ["shoulders slumped, eyes half closed, small sweat drop", "head drooping lower, mouth a flat line",
                                             "slowly lifting the head, eyes half closed, sweat drop falling"]),
    "alarm": (4, "panicking: quota almost gone", ["eyes wide, mouth open, both arms up, exclamation mark above",
                                                  "body shifted a little left, arms flailing, sweat drops",
                                                  "eyes wide, mouth open, body shifted a little right", "arms up, trembling, exclamation mark above"]),
    "sleeping": (3, "asleep, curled up, eyes closed", ["eyes closed, head tilted down, body relaxed, one small Z", "body 3% bigger as it breathes in, two Z",
                                                       "back to relaxed, one small Z"]),
    "celebrate": (6, "jumping for joy", ["crouching, about to jump, big smile", "jumping up, arms raised, eyes shut with joy", "peak of the jump, confetti around",
                                         "falling, arms still up, confetti around", "landing squash, arms out", "standing, one fist raised, beaming"]),
    "offline": (3, "disconnected, confused, greyed out", ["eyes as small crosses, mouth wavy, a small question mark above",
                                                          "head tilted left, question mark above", "head tilted right, question mark above"]),
    "waiting": (4, "waving to get attention: needs your confirmation", ["right arm raised high, mouth open, looking at the viewer", "arm swinging out",
                                                                       "arm raised high again, eyebrows up", "arm swinging out, small exclamation mark"]),
    "busy": (4, "overloaded, juggling many tasks", ["both hands busy, sweat drop, eyes darting", "head tilted, sweat drops flying", "hands blurred, steam puff above head", "slightly slumped, sweat drop"]),
    "painting": (4, "painting with a brush", ["brush raised, one eye squinting", "brush stroking forward", "brush lifted, happy smile", "stepping back to look, brush at the side"]),
    "alert": (3, "holding up a small warning sign, urgent", ["holding up a round sign with an exclamation mark, eyebrows up", "sign slightly tilted, tapping a foot", "sign raised higher"]),
    "excited": (4, "bouncing with anticipation, holding a small crystal ball", ["holding a glowing crystal ball, big sparkling eyes", "small hop, sparkles", "landing, crystal glowing", "small hop, sparkles"]),
    "eating": (4, "munching on glowing tokens", ["mouth wide open, a glowing coin flying in", "chewing, cheeks puffed", "swallowing, eyes closed happily", "licking lips"]),
    "exhausted": (2, "collapsed, out of battery, dizzy", ["lying flat, eyes as spirals, stars circling", "lying flat, stars in a different spot"]),
    "wave": (4, "greeting with a wave", ["right hand up, smile", "hand tilted left", "hand tilted right", "hand up, smile"]),
    "startle": (3, "startled", ["eyes huge, jumping back", "in the air, arms out", "landing, hands on cheeks"]),
}
CORE = ["idle", "working", "tired", "alarm", "sleeping", "celebrate", "offline", "waiting"]

# Image models offer a handful of aspect ratios, so strips are generated as grids.
LAYOUTS = {1: (1, 1, "1:1"), 2: (2, 1, "16:9"), 3: (3, 1, "16:9"), 4: (2, 2, "1:1"), 6: (3, 2, "3:2"), 8: (4, 2, "16:9")}

NEGATIVE = ("text, letters, watermark, logo, signature, border, frame, grid lines, ground shadow, cast shadow on the background, "
            "background gradient, background texture, extra limbs, extra fingers, different character, different outfit, "
            "different colours, cropped, cut off, blurry, low quality")


def layout(frames):
    if frames in LAYOUTS:
        return LAYOUTS[frames]
    cols = 4 if frames > 6 else 3
    return cols, -(-frames // cols), "16:9"


def character_sheet_prompt(bible, style, key):
    hexcode, word = KEYS[key]
    return (
        "Character reference sheet for a desktop pet. %s\n"
        "Style: %s.\n"
        "Show the character full body, centred, front three-quarter view, neutral standing pose, calm expression, "
        "with generous empty margin around it.\n"
        "Background: perfectly flat solid %s (%s), one single colour with no gradient, no vignette, no floor, no shadow, no text. "
        "The character must not use that colour anywhere." % (bible.strip(), STYLES[style][0], word, hexcode)
    )


def strip_prompt(bible, style, state, key, frames=None):
    default_frames, meaning, beats = STATES[state]
    frames = frames or default_frames
    cols, rows, aspect = layout(frames)
    hexcode, word = KEYS[key]
    beats = (beats * 2)[:frames] if len(beats) < frames else beats[:frames]
    listing = "\n".join("  frame %d: %s" % (i + 1, b) for i, b in enumerate(beats))
    return (
        "Using the attached reference image, draw the SAME character (identical face, proportions, colours, outfit and outline style) "
        "performing the animation \"%s\": %s.\n"
        "Character: %s\n"
        "Style: %s.\n"
        "Layout: a sprite sheet of %d frames arranged in a %d-column by %d-row grid, read left to right then top to bottom, "
        "equal-size square cells, the character the same size and standing on the same baseline in every cell, "
        "fully inside its cell with margin, never touching the cell edge. Nothing crosses between cells.\n"
        "Frames:\n%s\n"
        "Background: perfectly flat solid %s (%s) in every cell, one single colour with no gradient, no floor, no shadow, no text, no grid lines. "
        "The character must not use that colour anywhere.\n"
        "Image aspect ratio: %s.\n"
        "Avoid: %s." % (state, meaning, bible.strip(), STYLES[style][0], frames, cols, rows, listing, word, hexcode, aspect, NEGATIVE)
    )


def build_index(name, bible, style, key, states, out):
    steps = [{"step": "reference", "file": "00-character-sheet.txt", "frames": 1, "needs_reference": False,
              "after": "Pick the best image, save it as work/reference.png, and use it as the reference for every strip below."}]
    for state in states:
        frames = STATES[state][0]
        cols, rows, aspect = layout(frames)
        # The prompt asks for equal-size cells, so a regular grid is the dependable cut; --frames N is the fallback.
        slice_cmd = "python3 pets/tools/spritekit.py slice work/keyed/%s.png --cols %d --rows %d --out work/frames/%s" % (state, cols, rows, state)
        steps.append({
            "step": state, "file": "%s.txt" % state, "frames": frames, "grid": [cols, rows], "aspect": aspect, "needs_reference": True,
            "save_as": "work/raw/%s.png" % state,
            "key": "python3 pets/tools/spritekit.py key work/raw/%s.png work/keyed/%s.png%s" % (
                state, state, "" if key == "green" else " --color " + KEYS[key][0]),
            "slice": slice_cmd,
        })
    return {"name": name, "style": style, "key_color": KEYS[key][0], "states": states, "steps": steps,
            "build": "python3 pets/tools/spritekit.py build work/frames --id <id> --name %s --frame 256 --out pets/presets/<id>%s" % (
                name, " --pixelated" if style == "pixel" else ""),
            "validate": "python3 pets/tools/petpack.py validate pets/presets/<id>"}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--name", required=True, help="display name of the pet")
    p.add_argument("--bible", required=True, help="one paragraph that fully describes the character; it is repeated verbatim in every prompt")
    p.add_argument("--style", choices=sorted(STYLES), default="flat")
    p.add_argument("--key", choices=sorted(KEYS), default="green", help="flat background colour to key out (pick one the character does not use)")
    p.add_argument("--states", default="core", help="core | all | comma list (default core: the 8 required states)")
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args(argv)
    if len(args.bible.strip()) < 20:
        raise SystemExit("the bible is too short; describe shape, colours, face, and any accessory in a full sentence or two")
    states = CORE if args.states == "core" else list(STATES) if args.states == "all" else [s for s in args.states.split(",") if s]
    unknown = [s for s in states if s not in STATES]
    if unknown:
        raise SystemExit("no prompt template for: %s (known: %s)" % (", ".join(unknown), ", ".join(STATES)))
    missing = [s for s in CORE if s not in states]
    if missing:
        print("note: a valid sprite pack needs the core states; missing %s" % ", ".join(missing), file=sys.stderr)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "00-character-sheet.txt").write_text(character_sheet_prompt(args.bible, args.style, args.key) + "\n\nAvoid: " + NEGATIVE + ".\n")
    for state in states:
        (args.out / ("%s.txt" % state)).write_text(strip_prompt(args.bible, args.style, state, args.key) + "\n")
    index = build_index(args.name, args.bible, args.style, args.key, states, args.out)
    (args.out / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1) + "\n")
    print("%d prompts + index.json -> %s" % (len(states) + 1, args.out))
    for step in index["steps"]:
        print("  %-10s %2d frames  %s" % (step["step"], step["frames"], step.get("aspect", "1:1")))


if __name__ == "__main__":
    main()
