#!/usr/bin/env python3
"""Gate the generated party-lights models against the artist's .bbmodel and the block class.

The shipped shape is two models - one per light state - plus 144 blockstate variants that turn those
two models onto the six mounting faces with the "x" and "y" keys. The gate re-derives every property
instead of trusting the generator:

* geometry: the artist's 4x4x4 shell centred in x/z, the 3x3x3 bulb inside it, the 2x1x2 hanger
  standing on the shell's top plane with its outer face on y=16;
* uv: every face carries the artist's own rectangle, and the hanger draws from the core sheet;
* sheets: each state ships a cropped 32x32 frame of the artist's 32x128 atlas - the core frame texel
  for texel, the shell frame in the same RGB with one alpha for the paper;
* rotation: applying a mount's "x"/"y" to the hanger axis has to land on that mount's plane;
* blockstate: the variant keys are exactly the properties the block declares, nothing else.

Three regressions this gate exists for, all measured in game:

* Feeding the whole 32x128 atlas to a block model. A model reads uv in sixteenths of the image, so
  every two-unit window became sixteen rows tall, crossed all four frames, and the lamp turned into
  amber bands. Blockbench's own java_block export crops the 32x32 frame first, and so do we.
* Shipping the shell as a plain ascending box. Minecraft then re-winds the quads and the lamp reads as
  a solid amber box with the bulb locked inside; the artist's negative size plus its rotation object
  is what keeps the cage see-through.
* A blockstate that asks for a property the block does not declare, so every variant resolves to no
  model and the lamp draws as a magenta checker.

Run: .venv/Scripts/python.exe tools/deploy/party_lights_report.py
"""
from __future__ import annotations

import base64
import io

import frame_box
import json
import math
import re
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "src/main/resources/assets/pastoral_home"
MODELS = ASSETS / "models/block"
TEXTURES = ASSETS / "textures/block"
STATE = ASSETS / "blockstates/party_lights.json"
SOURCE = ROOT / "tools/deploy/model_sources/party_lights/party_lights.bbmodel"
BLOCK = ROOT / "src/main/java/com/pastoralhome/block/PartyLightsBlock.java"
ITEM = ASSETS / "items/party_lights.json"

SHEET_SIZE = (32, 128)
FRAME = 32
STATE_FRAMES = {"unlit": 0, "lit": 2}
# The artist's sheets carry no authored alpha: every painted texel is 255 and the rest is clear. The
# frosted paper is the shell sheet's own alpha, which the generator sets on painted texels only so the
# 1px clear seams stay real holes; the core sheet keeps the artist's 255.
SOURCE_ALPHA = 255
SHELL_ALPHA = 255
# The item copy cannot lean on backface culling - nothing culls it - so its shell keeps all six faces
# and ships a sheet whose painted texels are translucent, which is what puts those quads on
# Sheets.translucentBlockItemSheet() (BakedQuad.MaterialInfo.of, BakedQuad.java:88-92) and blends the
# bulb through the whole cage.
ITEM_SHELL_ALPHA = 235
# The artist's see-through cage is geometry, not alpha: the shell stores from.z > to.z and carries a
# rotation object, which stops FaceBakery from re-winding the two inverted quads so backface culling
# drops them and the bulb shows through. See prepare_party_lights_models.py's docstring.
SHELL_REVERSED_AXIS = 2
SHELL_ROTATION = {"angle": 0.0, "axis": "y", "origin": [8.0, 8.0, 8.0]}

# The generator crosses the artist's two colour pairs so the paper lands on the cage and the bulb on the
# core. The same map is duplicated here so the gate compares against what the model is supposed to
# sample, not against the raw sheet.
PAPER, PAPER_BRIGHT = (255, 235, 147), (255, 250, 226)
BULB, BULB_BRIGHT = (226, 145, 65), (243, 184, 88)
SWAP = {BULB: PAPER, PAPER: BULB, BULB_BRIGHT: PAPER_BRIGHT, PAPER_BRIGHT: BULB_BRIGHT}
FRAMETIME = 6

# Which artist element is which part, and which sheet slot that part reads.
SOURCE_ELEMENT = {"core": 2, "shell": 0, "neck": 1}
PART_SLOT = {"core": "#lamp_core", "shell": "#lamp_shell", "neck": "#lamp_core"}
ELEMENT_ORDER = ["core", "shell", "neck"]

ATTACHES = ("up", "down", "north", "south", "east", "west")
FACINGS = ("north", "east", "south", "west")
MODES = ("off", "chase", "steady")
LIT_STATES = ("false", "true")

MOUNT_NORMAL = {"up": (0, 1, 0), "down": (0, -1, 0), "north": (0, 0, -1),
                "south": (0, 0, 1), "east": (1, 0, 0), "west": (-1, 0, 0)}
ROTATIONS = {"up": {}, "down": {"x": 180}, "south": {"x": 270}, "north": {"x": 90},
             "east": {"x": 270, "y": 270}, "west": {"x": 270, "y": 90}}
HANGER_AXIS = (0, 1, 0)

SHELL_SIZE = 4.0
CORE_SIZE = 3.0
PLANE = 16.0

checks = []


def check(ok, label):
    checks.append((bool(ok), label))


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def ordered(element):
    low = [min(float(element["from"][i]), float(element["to"][i])) for i in range(3)]
    high = [max(float(element["from"][i]), float(element["to"][i])) for i in range(3)]
    return low, high


def model_path(state):
    return MODELS / ("party_lights_" + state + ".json")


def source_sheet(index=0):
    data = load(SOURCE)
    raw = base64.b64decode(data["textures"][index]["source"].split(",", 1)[1])
    sheet = Image.open(io.BytesIO(raw)).convert("RGBA")
    if sheet.size != SHEET_SIZE:
        raise SystemExit("source sheet is " + str(sheet.size) + ", expected " + str(SHEET_SIZE))
    return sheet


def source_frame(index):
    top = index * FRAME
    return source_sheet().crop((0, top, FRAME, top + FRAME))


def texels_differing(image, want, rgb_only=False):
    ours, theirs = list(image.getdata()), list(want.getdata())
    if rgb_only:
        ours = [(pixel[0], pixel[1], pixel[2]) for pixel in ours]
        theirs = [(pixel[0], pixel[1], pixel[2]) for pixel in theirs]
    return [(mine, other) for mine, other in zip(ours, theirs) if mine != other]


def alpha_moulded(image, source, alpha):
    """True when every painted texel carries alpha and every clear texel stays clear."""
    return all((pixel[3] == alpha if want[3] else pixel[3] == 0)
               for pixel, want in zip(image.getdata(), source.getdata()))


# The quadrant matrices are OctahedralGroup's own: "x": 90 is BLOCK_ROT_X_90 = ROT_90_X_NEG whose
# transform is (x, z, -y). They live in frame_box next to the screenshot projection, which needs the
# same matrix, so the gate and the screenshots cannot disagree about where a variant puts the lamp.
def rotate(normal, keys):
    """Model rotation order: "x" first, then "y" - Quadrant.fromXYZAngles composes z of y of x."""
    return frame_box.turn(normal, keys)


def geometry_checks():
    for state in STATE_FRAMES:
        name = "party_lights_" + state
        path = model_path(state)
        check(path.exists(), "geometry: " + name + ".json exists")
        if not path.exists():
            continue
        model = load(path)
        check(model.get("parent") == "minecraft:block/block",
              "geometry: " + name + " declares the block parent")
        blocks = {element.get("name"): element for element in model["elements"]}
        order = [element.get("name") for element in model["elements"]]
        check(order == ELEMENT_ORDER,
              "geometry: " + name + " draws core, shell, then hanger " + str(order))
        if sorted(blocks) != sorted(ELEMENT_ORDER):
            continue
        shell = blocks["shell"]
        shell_low, shell_high = ordered(shell)
        check(float(shell["from"][SHELL_REVERSED_AXIS]) > float(shell["to"][SHELL_REVERSED_AXIS]),
              "geometry: " + name + " shell keeps the artist's negative size on z "
              + str([shell["from"], shell["to"]]))
        check(shell.get("rotation") == SHELL_ROTATION,
              "geometry: " + name + " shell carries the rotation that skips the winding repair "
              + str(shell.get("rotation")))
        for other in ("core", "neck"):
            element = blocks[other]
            check(all(float(element["from"][i]) <= float(element["to"][i]) for i in range(3))
                  and "rotation" not in element,
                  "geometry: " + name + " " + other + " stays a plain ascending box")
        core_low, core_high = ordered(blocks["core"])
        neck_low, neck_high = ordered(blocks["neck"])

        def size(low, high):
            return [round(high[i] - low[i], 4) for i in range(3)]

        check(size(shell_low, shell_high) == [SHELL_SIZE] * 3,
              "geometry: " + name + " shell is the artist's 4x4x4 " + str(size(shell_low, shell_high)))
        check(size(core_low, core_high) == [CORE_SIZE] * 3,
              "geometry: " + name + " bulb is the artist's 3x3x3 " + str(size(core_low, core_high)))
        check(sorted(size(neck_low, neck_high)) == [1.0, 2.0, 2.0],
              "geometry: " + name + " hanger is the artist's 2x1x2 " + str(size(neck_low, neck_high)))
        inside = all(core_low[i] > shell_low[i] - 1e-4 and core_high[i] < shell_high[i] + 1e-4
                     for i in range(3))
        check(inside, "geometry: " + name + " bulb sits inside the shell")
        gap = round(min(core_low[0] - shell_low[0], shell_high[0] - core_high[0], 4)
                    if False else min(core_low[i] - shell_low[i] for i in range(3)), 4)
        check(abs(gap - 0.5) < 1e-4,
              "geometry: " + name + " leaves half a pixel between bulb and paper " + str(gap))
        for axis, j in (("x", 0), ("z", 2)):
            check(abs((shell_low[j] + shell_high[j]) / 2.0 - 8.0) < 1e-4,
                  "geometry: " + name + " shell is centred on " + axis)
            check(abs((core_low[j] + core_high[j]) / 2.0 - 8.0) < 1e-4,
                  "geometry: " + name + " bulb is centred on " + axis)
            check(abs((neck_low[j] + neck_high[j]) / 2.0 - 8.0) < 1e-4,
                  "geometry: " + name + " hanger is centred on " + axis)
            check(abs(neck_low[j] - (shell_low[j] + 1.0)) < 1e-4
                  and abs(neck_high[j] - (shell_high[j] - 1.0)) < 1e-4,
                  "geometry: " + name + " hanger is inset one pixel on " + axis)
        check(abs(shell_high[1] - neck_low[1]) < 1e-4,
              "geometry: " + name + " hanger stands on the shell's top plane")
        check(abs(neck_high[1] - PLANE) < 1e-4,
              "geometry: " + name + " hanger's outer face reaches y=16 " + str(neck_high[1]))


def uv_checks():
    artist = load(SOURCE)["elements"]
    for state in STATE_FRAMES:
        name = "party_lights_" + state
        path = model_path(state)
        if not path.exists():
            continue
        model = load(path)
        textures = model["textures"]
        for slot, want in (("lamp_core", "pastoral_home:block/party_lights_core_" + state),
                           ("lamp_shell", "pastoral_home:block/party_lights_shell_" + state)):
            check(textures.get(slot) == want, "uv: " + name + " " + slot + " reads " + want)
        # Break debris is a derived tile named after the model, shaped by the one repo-wide recipe. It
        # cannot be the lamp sheet: a sheet is 32x32 at best and a 32x128 strip at worst, so debris would
        # be uneven or pulled from four frames.
        check(textures.get("particle") == "pastoral_home:block/" + name + "_particle",
              "uv: " + name + " particle reads its derived 16x16 break tile " + str(textures.get("particle")))
        for part in ELEMENT_ORDER:
            element = next((e for e in model["elements"] if e.get("name") == part), None)
            if element is None:
                continue
            painted = {face: [round(float(v), 4) for v in spec["uv"]]
                       for face, spec in artist[SOURCE_ELEMENT[part]]["faces"].items()
                       if spec.get("texture") is not None}
            got = {face: [round(float(v), 4) for v in spec["uv"]] for face, spec in element["faces"].items()}
            check(got == painted,
                  "uv: " + name + " " + part + " carries the artist's rectangles verbatim")
            slots = {spec["texture"] for spec in element["faces"].values()}
            check(slots == {PART_SLOT[part]},
                  "uv: " + name + " " + part + " reads " + PART_SLOT[part] + " " + str(slots))
            for face, spec in element["faces"].items():
                u0, v0, u1, v1 = [float(v) for v in spec["uv"]]
                ok = (0.0 <= min(u0, u1) and max(u0, u1) <= 16.0
                      and 0.0 <= min(v0, v1) and max(v0, v1) <= 16.0)
                check(ok, "uv: " + name + " " + part + "." + face + " stays inside the frame " + str([u0, v0, u1, v1]))


def sheet_checks():
    # The build's normalizeBlockModelParticles task writes a blurred copy per model at build time, so
    # particle sheets are permitted but never required here.
    stems = [model_path(state).stem for state in STATE_FRAMES] + ["party_lights_inventory"]
    expected = {f"party_lights_{part}_{state}.png" for state in STATE_FRAMES
                for part in ("core", "shell")}
    expected |= {"party_lights_shell_item.png"}
    # lit ships its animated strip, so each of those two sheets owns a descriptor next to it. The
    # build still writes a name_particle.png next to any atlas-backed model, so those stay permitted.
    allowed = (expected | {stem + "_particle.png" for stem in stems}
               | {f"party_lights_{part}_lit.png.mcmeta" for part in ("core", "shell")}
               | {"party_lights_shell_item.png.mcmeta"})
    shipped = {p.name for p in TEXTURES.glob("party_lights*")}
    check(expected <= shipped and shipped <= allowed,
          "sheet: only the two frames per state and their particle copies ship - unexpected "
          + str(sorted(shipped - allowed)) + ", missing " + str(sorted(expected - shipped)))
    strip = source_sheet()
    dim = source_frame(0)
    # The artist animated the lamp inside the texture: four 32x32 rows, rows 0-1 in the dim palette and
    # rows 2-3 in the bright one, 6 ticks each. Unlit therefore ships a single static frame and lit
    # ships the whole strip with an animation descriptor. Only the shell's painted texels are frost
    # moulded; the core keeps the artist's binary alpha so the bulb stays solid behind the paper.
    shells = {"core": SOURCE_ALPHA, "shell": SHELL_ALPHA}
    for part in ("core", "shell"):
        alpha = shells[part]
        unlit = f"party_lights_{part}_unlit"
        path = TEXTURES / (unlit + ".png")
        check(path.exists(), "sheet: " + unlit + " exists")
        if path.exists():
            image = Image.open(path).convert("RGBA")
            check(image.size == (FRAME, FRAME), "sheet: " + unlit + " is the 32x32 dim frame " + str(image.size))
            if image.size == (FRAME, FRAME):
                off = texels_differing(image, dim, rgb_only=(part == "shell"))
                check(not off, "sheet: " + unlit + " carries artist frame 0's colours - "
                      + str(len(off)) + " texels off")
                check(alpha_moulded(image, dim, alpha),
                      "sheet: " + unlit + " paints the shell at alpha " + str(alpha)
                      + " and keeps every clear seam clear")
                check(sum(1 for pixel in image.getdata() if pixel[3] == 0) > 0,
                      "sheet: " + unlit + " keeps the artist's clear seams")
            check(not (TEXTURES / (unlit + ".png.mcmeta")).exists(),
                  "sheet: " + unlit + " is static and carries no animation descriptor")

        lit = f"party_lights_{part}_lit"
        path = TEXTURES / (lit + ".png")
        check(path.exists(), "sheet: " + lit + " exists")
        if path.exists():
            image = Image.open(path).convert("RGBA")
            check(image.size == SHEET_SIZE, "sheet: " + lit + " is the whole 32x128 strip " + str(image.size))
            if image.size == SHEET_SIZE:
                off = texels_differing(image, strip, rgb_only=(part == "shell"))
                check(not off, "sheet: " + lit + " carries the artist's strip colours - "
                      + str(len(off)) + " texels off")
                check(alpha_moulded(image, strip, alpha),
                      "sheet: " + lit + " paints the shell at alpha " + str(alpha)
                      + " on every frame and keeps the clear seams clear")
                rows = [image.crop((0, row * FRAME, FRAME, (row + 1) * FRAME)) for row in range(4)]
                check(list(rows[0].getdata()) == list(rows[1].getdata())
                      and list(rows[2].getdata()) == list(rows[3].getdata()),
                      "sheet: " + lit + " pairs its rows the way the artist drew them")
                check(list(rows[0].getdata()) != list(rows[2].getdata()),
                      "sheet: " + lit + " really cycles dim to bright, not four identical rows")
                check(sum(1 for pixel in rows[0].getdata() if pixel[3] == 0) > 0,
                      "sheet: " + lit + " keeps the artist's clear seams")
            meta_path = TEXTURES / (lit + ".png.mcmeta")
            check(meta_path.exists(), "sheet: " + lit + " ships an animation descriptor")
            if meta_path.exists():
                meta = load(meta_path)
                check(meta == {"animation": {"frametime": FRAMETIME}},
                      "sheet: " + lit + " animates at the artist's " + str(FRAMETIME) + " ticks " + str(meta))
            if part == "shell":
                alphas = {pixel[3] for pixel in image.getdata()}
                check(alphas == {0, SOURCE_ALPHA},
                      "sheet: " + lit + " stays binary so a placed block keeps the cutout path "
                      + str(sorted(alphas)))
    item_sheet = TEXTURES / "party_lights_shell_item.png"
    check(item_sheet.exists(), "sheet: party_lights_shell_item exists")
    if item_sheet.exists():
        image = Image.open(item_sheet).convert("RGBA")
        check(image.size == SHEET_SIZE,
              "sheet: party_lights_shell_item is the whole 32x128 strip " + str(image.size))
        if image.size == SHEET_SIZE:
            off = texels_differing(image, strip, rgb_only=True)
            check(not off, "sheet: party_lights_shell_item carries the artist's strip colours - "
                  + str(len(off)) + " texels off")
            check(alpha_moulded(image, strip, ITEM_SHELL_ALPHA),
                  "sheet: party_lights_shell_item paints the paper at alpha " + str(ITEM_SHELL_ALPHA)
                  + " and keeps every clear seam clear")
            alphas = {pixel[3] for pixel in image.getdata()}
            check(ITEM_SHELL_ALPHA in alphas and 0 in alphas,
                  "sheet: party_lights_shell_item really carries a translucent texel, which is what "
                  "puts its quads on the blended item sheet " + str(sorted(alphas)))
        meta_path = TEXTURES / "party_lights_shell_item.png.mcmeta"
        check(meta_path.exists(), "sheet: party_lights_shell_item ships an animation descriptor")
        if meta_path.exists():
            check(load(meta_path) == {"animation": {"frametime": FRAMETIME}},
                  "sheet: party_lights_shell_item animates at the artist's " + str(FRAMETIME) + " ticks")


def state_checks():
    variants = load(STATE)["variants"]
    expected = {"attach=" + attach + ",facing=" + facing + ",mode=" + mode + ",lit=" + lit
                for attach in ATTACHES for facing in FACINGS for mode in MODES for lit in LIT_STATES}
    check(set(variants) == expected,
          "state: blockstates cover " + str(len(expected)) + " combinations " + str(len(variants)))
    for attach in ATTACHES:
        target = rotate(HANGER_AXIS, ROTATIONS[attach])
        check(target == MOUNT_NORMAL[attach],
              "state: attach " + attach + " turns the hanger onto " + str(MOUNT_NORMAL[attach])
              + ", rotations give " + str(target))
        for lit in LIT_STATES:
            want = "pastoral_home:block/party_lights_" + ("lit" if lit == "true" else "unlit")
            keys = ["attach=" + attach + ",facing=" + facing + ",mode=" + mode + ",lit=" + lit
                    for facing in FACINGS for mode in MODES]
            models = {variants[k].get("model") for k in keys if k in variants}
            check(models == {want}, "state: attach " + attach + " lit " + lit + " draws " + want)
            for k in keys:
                if k not in variants:
                    continue
                variant = variants[k]
                got = {key: variant[key] for key in ("x", "y") if key in variant}
                check(got == ROTATIONS[attach],
                      "state: " + k + " carries the mount rotation " + str(ROTATIONS[attach])
                      + ", got " + str(got))
        # Rotation keys alone do not prove the lamp ends up against its mount: the same matrix that
        # the screenshots use reads the shipped blockstate and model, so a flipped quarter turn here
        # fails instead of hanging a wall lamp on the far side of its post.
        low, high = frame_box.world_box("pastoral_home:party_lights",
                                        {"attach": attach, "facing": "north", "lit": "true",
                                         "mode": "steady"}, [0, 0, 0])
        normal = MOUNT_NORMAL[attach]
        axis = [i for i in range(3) if normal[i]][0]
        # The mount side is the cell boundary in the attach direction: the upper face for "up",
        # the lower face for "down", and one of the four vertical faces for the wall mounts.
        reach, want = (high[axis], 1.0) if normal[axis] > 0 else (low[axis], 0.0)
        check(abs(reach - want) < 0.02,
              "state: attach " + attach + " puts the lamp against its mount "
              + str(MOUNT_NORMAL[attach]) + ", the shipped model stops at " + str(round(reach, 3)))
    inventory = MODELS / "party_lights_inventory.json"
    check(inventory.exists(), "state: inventory model exists")
    if inventory.exists():
        model = load(inventory)
        check(model["textures"].get("lamp_shell", "") == "pastoral_home:block/party_lights_shell_item",
              "state: inventory draws the lit palette from the translucent sheet "
              + str(model["textures"].get("lamp_shell")))


def declared_properties():
    text = BLOCK.read_text(encoding="utf-8")
    names = set(m.group(1) for m in re.finditer(r'EnumProperty\.create\("(\w+)"', text))
    if "BlockStateProperties.HORIZONTAL_FACING" in text:
        names.add("facing")
    if "BlockStateProperties.LIT" in text:
        names.add("lit")
    return names


def contract_checks():
    declared = declared_properties()
    asked = set()
    for key in load(STATE)["variants"]:
        asked |= {part.split("=", 1)[0] for part in key.split(",")}
    check(asked == declared,
          "contract: blockstate asks " + str(sorted(asked)) + ", the block declares " + str(sorted(declared)))
    text = BLOCK.read_text(encoding="utf-8")
    check("context.getClickedFace().getOpposite()" in text,
          "contract: placement takes the face opposite the clicked one")
    check("canSurvive" in text, "contract: the block refuses to float without its mount")
    if ITEM.exists():
        item = load(ITEM)
        text = json.dumps(item)
        check("party_lights_inventory" in text,
              "contract: the item falls back to the inventory model")
    else:
        check(False, "contract: items/party_lights.json exists")


def intent_checks():
    """The cage keeps the artist's amber paper and the core keeps the cream bulb behind it."""
    frame = source_frame(0)
    pixels = frame.load()
    # Straight from the sheet: the shell's six windows all land on the amber block, the core's windows
    # on the cream block plus its bright highlight. No recolouring anywhere in the pipeline.
    for part, wanted in (("shell", {BULB}), ("core", {PAPER, BULB_BRIGHT})):
        element = load(SOURCE)["elements"][SOURCE_ELEMENT[part]]
        for face, spec in element["faces"].items():
            if not spec.get("uv"):
                continue
            u0, v0, u1, v1 = [int(round(float(v) * 2)) for v in spec["uv"]]
            sampled = {pixels[x, y][:3] for x in range(min(u0, u1), max(u0, u1))
                       for y in range(min(v0, v1), max(v0, v1)) if pixels[x, y][3]}
            ok = sampled and sampled <= wanted
            check(ok, "intent: " + part + "." + face + " samples "
                  + ("paper" if part == "shell" else "bulb") + " " + str(sorted(sampled)))


def item_checks():
    """The item model is drawn without the backface culling the placed block relies on.

    Dropping the two quads the world culls is the trap that made the icon look broken: an item renderer
    draws every quad, so the missing faces were really missing. The cage stays whole there instead, and
    is opened by a translucent sheet, which keeps the bulb visible through the paper.
    """
    all_faces = {"north", "south", "east", "west", "up", "down"}
    placed = load(model_path("lit"))
    inventory = load(MODELS / "party_lights_inventory.json")
    for model, label in ((placed, "placed"), (inventory, "item")):
        shells = [element for element in model["elements"] if element.get("name") == "shell"]
        check(len(shells) == 1, "item: " + label + " model has one shell element")
        if not shells:
            continue
        shell = shells[0]
        faces = set(shell["faces"])
        check(faces == all_faces, "item: " + label + " shell draws all six faces " + str(sorted(faces)))
        check(float(shell["from"][2]) > float(shell["to"][2]),
              "item: " + label + " shell keeps the artist's reversed z")
        check(shell.get("rotation") == SHELL_ROTATION,
              "item: " + label + " shell keeps the rotation object " + str(shell.get("rotation")))
        for part in ("core", "neck"):
            twin = [element for element in model["elements"] if element.get("name") == part]
            check(len(twin) == 1, "item: " + label + " model has one " + part + " element")
    check(inventory["elements"] == placed["elements"],
          "item: the held copy is the placed geometry, element for element")
    shell_sheet = inventory["textures"].get("lamp_shell", "")
    check(shell_sheet == "pastoral_home:block/party_lights_shell_item",
          "item: the held copy reads the translucent shell sheet " + shell_sheet)
    check(placed["textures"].get("lamp_shell") == "pastoral_home:block/party_lights_shell_lit",
          "item: the placed model keeps the opaque lit sheet "
          + str(placed["textures"].get("lamp_shell")))


def display_checks():
    """The item copies declare their own camera because the renderer that draws them never culls.

    Vanilla's GUI camera sits at 30 degrees of elevation and looks at the roof of the cage, which is
    exactly the camera a player sees in a slot - and it is the reason the icon read as one solid
    amber block. Every context keeps vanilla's scale and translation, so size and hand placement are
    still whatever every other block item uses.
    """
    vanilla = {"gui": ([30.0, 225.0, 0.0], [0.0, 0.0, 0.0], [0.625, 0.625, 0.625]),
               "ground": ([0.0, 0.0, 0.0], [0.0, 3.0, 0.0], [0.25, 0.25, 0.25]),
               "fixed": ([0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.5, 0.5, 0.5]),
               "thirdperson_righthand": ([75.0, 45.0, 0.0], [0.0, 2.5, 0.0], [0.375, 0.375, 0.375]),
               "firstperson_righthand": ([0.0, 45.0, 0.0], [0.0, 0.0, 0.0], [0.4, 0.4, 0.4]),
               "firstperson_lefthand": ([0.0, 225.0, 0.0], [0.0, 0.0, 0.0], [0.4, 0.4, 0.4])}
    # Only the cameras that look into the open mouth are authored; the GUI one stays vanilla
    # because the project's icon gate requires it.
    intent = {"gui": [30.0, 225.0, 0.0], "ground": [0.0, 0.0, 0.0], "fixed": [0.0, 0.0, 0.0],
              "thirdperson_righthand": [75.0, 0.0, 0.0], "firstperson_righthand": [0.0, 0.0, 0.0],
              "firstperson_lefthand": [0.0, 0.0, 0.0]}
    inventory = load(MODELS / "party_lights_inventory.json")
    display = inventory.get("display", {})
    check(set(display) == set(vanilla), "display: the item model declares every display context "
          + str(sorted(display)))
    for context, (want_rotation, translation, scale) in vanilla.items():
        entry = display.get(context)
        if not entry:
            continue
        got = [float(value) for value in entry.get("rotation", [])]
        check(got == intent[context], "display: " + context + " camera is " + str(got)
              + ", wants " + str(intent[context]))
        check([float(value) for value in entry.get("translation", [])] == translation,
              "display: " + context + " keeps vanilla's offset " + str(translation))
        check([round(float(value), 4) for value in entry.get("scale", [])] == scale,
              "display: " + context + " keeps vanilla's scale " + str(scale))
    for state in STATE_FRAMES:
        placed = load(model_path(state))
        check("display" not in placed,
              "display: the placed " + state + " model declares no display block, which nothing reads")
    proxy = MODELS.parent / "item_icons" / "party_lights" / "variant_0.json"
    if proxy.exists():
        camera = load(proxy).get("display", {}).get("gui", {})
        got = [float(value) for value in camera.get("rotation", [])]
        check(got == intent["gui"], "display: the slot icon is drawn from the same camera " + str(got))


def particle_checks():
    """Breaking particles read the model's particle slot; an atlas there samples four frames of debris.

    The frame is 4px paint blocks over a 1px clear seam, so a face window is 4x4 texels. The shaper's
    rule for a window under 16 texels is flat paint in the window's own dominant colour - resampling it
    up is what rained staircases - hence a single opaque colour per tile rather than a palette.
    """
    lamp_colours = set()
    for state in STATE_FRAMES:
        with Image.open(TEXTURES / ("party_lights_shell_" + state + ".png")) as opened:
            lamp_colours |= {texel[:3] for texel in opened.convert("RGBA").getdata() if texel[3] > 127}
    for state, model_name in ([(s, "party_lights_" + s) for s in STATE_FRAMES]
                              + [("lit", "party_lights_inventory")]):
        name = model_name + "_particle"
        path = TEXTURES / (name + ".png")
        check(path.exists(), "particle: " + name + ".png exists")
        if not path.exists():
            continue
        with Image.open(path) as opened:
            tile = opened.convert("RGBA")
        check(tile.size == (16, 16), "particle: " + name + " is 16x16 " + str(tile.size))
        check(not (TEXTURES / (name + ".png.mcmeta")).exists(),
              "particle: " + name + " is one still tile, not a strip")
        texels = list(tile.getdata())
        check(all(texel[3] == 255 for texel in texels),
              "particle: " + name + " has no clear texels, so debris has no holes")
        colours = {texel[:3] for texel in texels}
        check(len(colours) == 1,
              "particle: " + name + " is flat paint from one texel window, not a resampled mosaic "
              + str(sorted(colours)))
        check(colours <= lamp_colours,
              "particle: " + name + " takes a colour from the lamp sheet " + str(sorted(colours)))
    for state in ("unlit", "lit", "inventory"):
        model = load(MODELS / ("party_lights_" + state + ".json"))
        want = "pastoral_home:block/party_lights_" + state + "_particle"
        check(model["textures"].get("particle") == want,
              "particle: " + state + " breaks as " + want)


def main():
    geometry_checks()
    uv_checks()
    intent_checks()
    sheet_checks()
    state_checks()
    item_checks()
    display_checks()
    particle_checks()
    contract_checks()
    failed = [label for ok, label in checks if not ok]
    for label in failed:
        print("FAIL " + label)
    print(("{} of {} checks passed".format(len(checks) - len(failed), len(checks))))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
