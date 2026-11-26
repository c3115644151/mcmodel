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
RENDERER = ROOT / "src/main/java/com/pastoralhome/client/renderer/BridgeRopeRenderer.java"
ITEM = ASSETS / "items/party_lights.json"
CONTROLLER_STATE = ASSETS / "blockstates/party_lights_controller.json"
CONTROLLER_ITEM = ASSETS / "items/party_lights_controller.json"
CONTROLLER_BLOCK = ROOT / "src/main/java/com/pastoralhome/block/PartyLightsControllerBlock.java"
CONTROLLER_BE = ROOT / "src/main/java/com/pastoralhome/blockentity/PartyLightsControllerBlockEntity.java"
ROPE_LAMPS = ROOT / "src/main/java/com/pastoralhome/entity/BridgeRopeLamps.java"
ROPE_DRIVE = ROOT / "src/main/java/com/pastoralhome/entity/BridgeRopeDrive.java"
ROPE_ENTITY = ROOT / "src/main/java/com/pastoralhome/entity/BridgeRopeEntity.java"
PROGRAM = ROOT / "src/main/java/com/pastoralhome/block/PartyLightsProgram.java"
NETWORK = ROOT / "src/main/java/com/pastoralhome/block/PartyLightsNetwork.java"
SCORE = ROOT / "src/main/java/com/pastoralhome/block/PartyLightsScore.java"
SCORES = ROOT / "src/main/java/com/pastoralhome/block/PartyLightsScores.java"
TAPE = ROOT / "src/main/java/com/pastoralhome/block/PartyLightsTape.java"
MOD_MAIN = ROOT / "src/main/java/com/pastoralhome/PastoralHome.java"
SCORE_DATA = ROOT / "src/main/resources/data/pastoral_home/party_lights"

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

# The controller carries one more property than the lamp: two nets that touch can both want the same
# lamp, and the player settles the tie by right-clicking the controller, so 4 priorities x 4 facings x
# 2 powered states is 32 variants.
CONTROLLER_PRIORITIES = ("0", "1", "2", "3")
PROGRAM_NAMES = ("off", "solid", "beacon", "breath", "chase", "converge", "diverge", "cross", "ripple",
                 "comet", "heart", "rain", "strobe", "alternate", "meter", "ribbon")
ATTACHES = ("up", "down", "north", "south", "east", "west")
FACINGS = ("north", "east", "south", "west")
# Redstone turns the lamps into a display: the controller writes MODE=REMOTE on every lamp it can
# reach, so the enum and the blockstate both carry five modes, not the three a player can click.
MODES = ("off", "chase", "steady", "beacon", "remote")
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
        check(all(element.get("shade") is False and element.get("light_emission") == 15
                  for element in model["elements"]),
              "geometry: " + name + " every element is unshaded and full-bright so the lamp "
              "shows the artist's texels in any game lighting")
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
    # Both states are now static frames: no .mcmeta ships with any lamp sheet. A placed lamp
    # changes look only through its block state, so STEADY really is steady.
    # The build still writes a name_particle.png next to any atlas-backed model, so those stay permitted.
    # The controller is drawn procedurally by the same generator, so its three tiles live in this
    # folder too and would otherwise read as orphans of the lamp pipeline.
    allowed = (expected | {stem + "_particle.png" for stem in stems}
               | {"party_lights_controller_side.png", "party_lights_controller_face_off.png",
                  "party_lights_controller_face_on.png", "party_lights_controller_particle.png",
                  "party_lights_controller_lit_particle.png"})
    shipped = {p.name for p in TEXTURES.glob("party_lights*")}
    check(expected <= shipped and shipped <= allowed,
          "sheet: only the two frames per state and their particle copies ship - unexpected "
          + str(sorted(shipped - allowed)) + ", missing " + str(sorted(expected - shipped)))
    strip = source_sheet()
    dim = source_frame(STATE_FRAMES['unlit'])
    bright = source_frame(STATE_FRAMES['lit'])
    # Both states are static frames now: the lamp changes look only through the block state's
    # `lit` property. A shared texture animation made every lamp breathe in lockstep and kept a
    # STEADY lamp visibly flickering while its light level never moved, so no lamp sheet may
    # carry an .mcmeta. Only the shell's painted texels are alpha-moulded; the core keeps the
    # artist's binary alpha so the bulb stays solid behind the paper cage.
    shells = {'core': SOURCE_ALPHA, 'shell': SHELL_ALPHA}
    for part in ('core', 'shell'):
        alpha = shells[part]
        for state, want in (('unlit', dim), ('lit', bright)):
            name = f'party_lights_{part}_{state}'
            path = TEXTURES / (name + '.png')
            check(path.exists(), 'sheet: ' + name + ' exists')
            if path.exists():
                image = Image.open(path).convert('RGBA')
                check(image.size == (FRAME, FRAME),
                      'sheet: ' + name + ' is a 32x32 static frame ' + str(image.size))
                if image.size == (FRAME, FRAME):
                    off = texels_differing(image, want, rgb_only=(part == 'shell'))
                    check(not off, 'sheet: ' + name + ' carries the artist frame colours - '
                          + str(len(off)) + ' texels off')
                    check(alpha_moulded(image, want, alpha),
                          'sheet: ' + name + ' paints the shell at alpha ' + str(alpha)
                          + ' and keeps every clear seam clear')
                    check(sum(1 for pixel in image.getdata() if pixel[3] == 0) > 0,
                          'sheet: ' + name + ' keeps the artist\'s clear seams')
                if part == 'shell':
                    alphas = {pixel[3] for pixel in image.getdata()}
                    check(alphas == {0, SOURCE_ALPHA},
                          'sheet: ' + name + ' stays binary so a placed block keeps the cutout path '
                          + str(sorted(alphas)))
            check(not (TEXTURES / (name + '.png.mcmeta')).exists(),
                  'sheet: ' + name + ' is static and carries no animation descriptor')
    item_sheet = TEXTURES / 'party_lights_shell_item.png'
    check(item_sheet.exists(), 'sheet: party_lights_shell_item exists')
    if item_sheet.exists():
        image = Image.open(item_sheet).convert('RGBA')
        check(image.size == (FRAME, FRAME),
              'sheet: party_lights_shell_item is a 32x32 static frame ' + str(image.size))
        if image.size == (FRAME, FRAME):
            off = texels_differing(image, bright, rgb_only=True)
            check(not off, 'sheet: party_lights_shell_item carries the artist lit frame colours - '
                  + str(len(off)) + ' texels off')
            check(alpha_moulded(image, bright, ITEM_SHELL_ALPHA),
                  'sheet: party_lights_shell_item paints the paper at alpha ' + str(ITEM_SHELL_ALPHA)
                  + ' and keeps every clear seam clear')
            alphas = {pixel[3] for pixel in image.getdata()}
            check(ITEM_SHELL_ALPHA in alphas and 0 in alphas,
                  'sheet: party_lights_shell_item really carries a translucent texel, which is what '
                  'puts its quads on the blended item sheet ' + str(sorted(alphas)))
        check(not (TEXTURES / 'party_lights_shell_item.png.mcmeta').exists(),
              'sheet: party_lights_shell_item is static and carries no animation descriptor')


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


def arithmetic(text):
    """Value of a Java float expression such as "1.0F / 16.0F + 0.002F", or None."""
    text = re.sub(r"([0-9])[Ff]\b", r"\1", text).strip()
    if not re.fullmatch(r"[0-9.+\-*/() ]+", text):
        return None
    try:
        return float(eval(text, {"__builtins__": {}}, {}))
    except (SyntaxError, ZeroDivisionError, TypeError):
        return None


def hanger_checks():
    """The rope hangs lamps by the model's top, so the renderer's anchor and the geometry must agree."""
    source = RENDERER.read_text(encoding="utf-8")
    values = {}
    for name in ("ANCHOR_X", "ANCHOR_Y", "ANCHOR_Z", "HANGER_SINK"):
        match = re.search(name + r"\s*=\s*([^;]+);", source)
        values[name] = match.group(1).strip() if match else None
        check(bool(match), "hanger: BridgeRopeRenderer declares " + name)
    placed = load(MODELS / "party_lights_lit.json")
    lows = [element["from"] for element in placed["elements"]]
    highs = [element["to"] for element in placed["elements"]]
    top = max(high[1] for high in highs)
    middle_x = (min(low[0] for low in lows) + max(high[0] for high in highs)) / 2.0
    middle_z = (min(low[2] for low in lows) + max(high[2] for high in highs)) / 2.0
    check(top == 16.0, "hanger: the lamp model reaches y=16 " + str(top))
    for name, want in (("ANCHOR_Y", top), ("ANCHOR_X", middle_x), ("ANCHOR_Z", middle_z)):
        text = values.get(name) or ""
        got = float(re.sub(r"[Ff]$", "", text)) if text else None
        check(got == want,
              "hanger: " + name + " sits on the model's top centre " + str(want) + " but is " + str(text))
    sink = values.get("HANGER_SINK") or ""
    amount = arithmetic(sink)
    check(amount is not None and 0.0625 <= amount <= 0.1,
          "hanger: HANGER_SINK clears the rope half but stays under a quarter " + sink)


def controller_checks():
    """The redstone face: a procedurally drawn controller whose eight states and program table hold."""
    variants = load(CONTROLLER_STATE)["variants"]
    expected = {"facing=" + facing + ",powered=" + powered + ",priority=" + priority
                for facing in FACINGS for powered in LIT_STATES for priority in CONTROLLER_PRIORITIES}
    check(set(variants) == expected,
          "controller: blockstate covers " + str(len(expected)) + " combinations, got " + str(len(variants)))
    yaw = {"north": 0, "east": 90, "south": 180, "west": 270}
    for facing in FACINGS:
        for powered in LIT_STATES:
            for priority in CONTROLLER_PRIORITIES:
                key = "facing=" + facing + ",powered=" + powered + ",priority=" + priority
                variant = variants.get(key, {})
                stem = "party_lights_controller_lit" if powered == "true" else "party_lights_controller"
                check(variant.get("model") == "pastoral_home:block/" + stem,
                      "controller: " + key + " draws " + stem)
                got = variant.get("y", 0)
                check(got == yaw[facing],
                      "controller: " + key + " turns the face to " + str(yaw[facing]) + ", got " + str(got))
    for stem in ("party_lights_controller", "party_lights_controller_lit"):
        path = MODELS / (stem + ".json")
        check(path.exists(), "controller: model " + stem + " exists")
        if not path.exists():
            continue
        model = load(path)
        textures = model.get("textures", {})
        check(textures.get("particle") == "pastoral_home:block/" + stem + "_particle",
              "controller: " + stem + " derives its break tile, got " + str(textures.get("particle")))
        check(textures.get("side") == "pastoral_home:block/party_lights_controller_side",
              "controller: " + stem + " draws the panelled side")
        face = "on" if stem.endswith("_lit") else "off"
        check(textures.get("face") == "pastoral_home:block/party_lights_controller_face_" + face,
              "controller: " + stem + " draws the " + face + " window")
        elements = {element.get("name"): element for element in model.get("elements", [])}
        check(set(elements) == {"body", "plate"},
              "controller: " + stem + " is a body plus a reading plate, got " + str(sorted(elements)))
        body = elements.get("body", {})
        plate = elements.get("plate", {})
        check(body.get("from") == [0.0, 0.0, 1.0] and body.get("to") == [16.0, 16.0, 16.0],
              "controller: the body fills the cell except the last unit of z")
        check(plate.get("from") == [2.0, 4.0, 0.0] and plate.get("to") == [14.0, 12.0, 1.0],
              "controller: the plate sits in that last unit, so no face is coplanar with the body")
        # No element may reach past the cell: a controller that pokes out of its block clips into the
        # lamp next to it and looks like a modelling mistake in every screenshot.
        for element in (body, plate):
            span = element.get("from", [0, 0, 0]) + element.get("to", [0, 0, 0])
            check(all(-0.001 <= value <= 16.001 for value in span),
                  "controller: " + str(element.get("name")) + " stays inside the cell")
    for name in ("side", "face_off", "face_on"):
        path = TEXTURES / ("party_lights_controller_" + name + ".png")
        check(path.exists(), "controller: texture " + name + " exists")
        if not path.exists():
            continue
        image = Image.open(path)
        check(image.size == (16, 16), "controller: texture " + name + " is 16x16, got " + str(image.size))
        check(image.convert("RGBA").getextrema()[3] == (255, 255),
              "controller: texture " + name + " is fully opaque")
    check(CONTROLLER_ITEM.exists(), "controller: items/party_lights_controller.json exists")
    if CONTROLLER_ITEM.exists():
        check("party_lights_controller" in json.dumps(load(CONTROLLER_ITEM)),
              "controller: the item points at the controller's own model")

    text = CONTROLLER_BLOCK.read_text(encoding="utf-8")
    check("HORIZONTAL_FACING" in text and "POWERED" in text,
          "controller block: declares facing and powered")
    # Priority is a block state, not a block entity field, so it survives a chunk reload without the
    # entity being read and so the blockstate can draw it in one look. `data get block` reads it too.
    check('IntegerProperty.create("priority", 0, 3)' in text and "builder.add(FACING, POWERED, PRIORITY)" in text,
          "controller block: priority is a 0..3 block state the player can click")
    # The analog output is the whole output contract: a comparator next to the controller reads the
    # network's clock, which is what lets a second group of lamps follow the first without any new
    # wiring. An output that silently returns 0 would look identical in a screenshot.
    check("hasAnalogOutputSignal" in text and "getAnalogOutputSignal" in text,
          "controller block: answers a comparator with the network phase")
    check("isSignalSource" not in text,
          "controller block: does not transmit power, so redstone dust cannot feed it back")
    be = CONTROLLER_BE.read_text(encoding="utf-8")
    check("getBestNeighborSignal" in be,
          "controller entity: reads the vanilla best-neighbour signal, so every redstone part works")
    check("PartyLightsProgram.lit(" in be, "controller entity: drives the lamps through the program table")
    check("PartyLightsNetwork.compile(" in be, "controller entity: compiles the network before driving")
    # Claiming only what is still OFF is the difference between a controller and a thief: a player
    # who right-clicks a lamp to STEADY while the network is live must keep that lamp. Re-claiming
    # anything that is not REMOTE would take it back on the very next tick and make the click useless.
    check("boolean claim = mode == PartyLightsBlock.Mode.OFF;" in be,
          "controller entity: only claims lamps the player left on OFF, so a right-click takes one back")
    check("if (!claim && !mine) continue;" in be,
          "controller entity: never touches a lamp the player drives himself, not even its LIT")
    check("Mode.REMOTE" in be and "releaseMembers" in be,
          "controller entity: hands every REMOTE lamp back when the signal drops")

    program = PROGRAM.read_text(encoding="utf-8")
    check("COUNT = 16" in program, "program table: sixteen levels, one per redstone strength")
    for name in PROGRAM_NAMES:
        check("int " + name.upper() + " = " in program, "program table: level " + name + " exists")
    # A score file names its steps; the names live in one list, and a rename that misses that list is
    # exactly the kind of edit that loads fine and then plays OFF forever.
    for name in PROGRAM_NAMES:
        check('"' + name + '"' in program,
              "program table: the name list spells " + name + " the way a score file has to")
    network = NETWORK.read_text(encoding="utf-8")
    check("MAX_LAMPS = 512" in network, "network: the span limit is 512 lamps")
    check("instanceof PartyLightsBlock" in network, "network: flood fill only walks through lamps")
    # Ownership has to be settled by data, not by which controller ticked last: a lamp touching two
    # controllers would otherwise flicker between two programs every tick.
    check("prefersAnotherController" in network,
          "network: a lamp touching two controllers is owned by the lower block position")


def rope_network_checks():
    """The cord half: lamps on a rope are entities, so the controller cannot flood fill to them."""
    lamps = ROPE_LAMPS.read_text(encoding="utf-8")
    drive = ROPE_DRIVE.read_text(encoding="utf-8")
    entity = ROPE_ENTITY.read_text(encoding="utf-8")
    be = CONTROLLER_BE.read_text(encoding="utf-8")
    network = NETWORK.read_text(encoding="utf-8")
    # A cord under a controller must run the same program as the block lamps, through the same call.
    check("PartyLightsProgram.lit(" in drive,
          "rope drive: a cord lamp asks the same program table a block lamp asks")
    check("case REMOTE -> drive.lit(" in lamps,
          "rope layout: REMOTE answers with the network drive, not with a hard-coded dark")
    check("BridgeRopeDrive.NONE" in lamps,
          "rope layout: a cord that lost its controller falls back to dark")
    check("DRIVE" in entity and "setDrive" in entity and "drive()" in entity,
          "rope entity: carries the network clock as synched data")
    check("if (!encoded.equals(this.entityData.get(DRIVE)))" in entity,
          "rope entity: writes the drive only when it changes, so a tick loop cannot spam the sync")
    check('output.putString("drive"' in entity, "rope entity: persists the drive with the rope")
    # Real light: each bright hanging lamp gets an invisible vanilla light block, driven by the
    # same layout() the renderer uses so the emitted light can never disagree with the appearance.
    check("private void syncLightBlocks(ServerLevel level)" in entity
          and "BridgeRopeLamps.layout(start, end, ts, this.lampMode()" in entity,
          "rope light: the lit set comes from the same layout the client renderer draws")
    check("if (!slot.lit()) continue;" in entity and "Blocks.LIGHT.defaultBlockState()" in entity
          and "LightBlock.LEVEL" in entity,
          "rope light: only bright lamps place a vanilla light block at the right level")
    check("level.getBlockState(cell).isAir()" in entity,
          "rope light: only air cells are lit, so supports and terrain are never overwritten")
    check("this.syncLightBlocks(serverLevel)" in entity and "clearLightBlocks" in entity
          and "onRemoval(Entity.RemovalReason reason)" in entity,
          "rope light: the cord syncs every tick and clears its lights when removed")
    # Claiming and releasing the cord follows the same OFF/REMOTE rule as the block lamps.
    check("findRopes" in be and "driveRopes" in be,
          "controller entity: finds the cords tied to its own network and hands them the clock")
    check("getEntitiesOfClass(BridgeRopeEntity.class" in be,
          "controller entity: a rope's centre is mid-span, so the search needs the network box plus reach")
    check("rope.setLampMode(PartyLightsBlock.Mode.REMOTE)" in be,
          "controller entity: claims a cord that is still OFF, exactly like a block lamp")
    check("BridgeRopeDrive.NONE" in be,
          "controller entity: clears the drive when it hands the cord back")
    check("invalidateNear" in network,
          "network: a rope waking its controller is a helper, not a second copy of the flood fill")
    check("PartyLightsNetwork.invalidateNear" in entity,
          "rope entity: hanging or taking a lamp wakes the controller, which has no neighbour change to see")
    # Entity.getBoundingBox() is final; makeBoundingBox(Vec3) is the protected hook every
    # setPos/reapplyPosition eventually calls. Overriding it with the cord span is the only
    # fix that survives spawn packets and command summons, which setPos after loading NBT.
    check("protected AABB makeBoundingBox(Vec3 position)" in entity
          and "return bounds(this.start(), this.end())" in entity,
          "rope entity: every position refresh keeps the whole cord pickable")
    check("onSyncedDataUpdated(EntityDataAccessor<?>" in entity
          and "onSyncedDataUpdated(List<SynchedEntityData.DataValue<?>>" in entity,
          "rope entity: also rebuilds its pick box on both sync callbacks")
    check("START.equals(accessor) || END.equals(accessor)" in entity,
          "rope entity: only the two anchors trigger the per-field rebuild")
    # BEACON is a building-wide double flash: every lamp under one controller locks to that
    # controller's seed, and the cord receives the same seed through the focus slot.
    check("PartyLightsProgram.BEACON" in be and "seedOf(this.worldPosition)" in be,
          "controller entity: block lamps share the controller seed for BEACON")
    check("wireFocus" in be and "program == PartyLightsProgram.BEACON ? this.worldPosition" in be,
          "controller entity: cords get the controller position as the BEACON phase anchor")
    check("program == PartyLightsProgram.BEACON && focus != null" in drive and "seedOf(focus)" in drive,
          "rope drive: a driven cord locks BEACON to the controller seed")


def score_checks():
    """The choreography tape: a JSON score, a head that walks it, and the tie-break between nets."""
    score = SCORE.read_text(encoding="utf-8")
    tape = TAPE.read_text(encoding="utf-8")
    scores = SCORES.read_text(encoding="utf-8")
    main = MOD_MAIN.read_text(encoding="utf-8")
    be = CONTROLLER_BE.read_text(encoding="utf-8")
    drive = ROPE_DRIVE.read_text(encoding="utf-8")
    network = NETWORK.read_text(encoding="utf-8")
    block = CONTROLLER_BLOCK.read_text(encoding="utf-8")

    # The tape is data, so every bound lives in the codec: an unparsed file is a lamp that never lights
    # and a crash-free server, which is the hardest failure to trace back to a typo in a resource.
    check("RecordCodecBuilder" in score and '"steps"' in score and '"tempo"' in score and '"loop"' in score,
          "score: the tape is a codec with tempo, loop and steps")
    check("MAX_STEPS = 64" in score and "MAX_TICKS = 1200" in score,
          "score: a tape is bounded to 64 steps of at most 1200 ticks")
    check("PartyLightsProgram.CODEC" in score,
          "score: a step names its programme, so a typo fails the load instead of playing OFF")
    check("distance(" in score and "Math.abs" in score,
          "score: a focus measures Manhattan distance, which is how far a lamp is along a wall")
    check("record Frame" in tape and "floorMod" in tape,
          "tape: the head is a pure function of elapsed ticks and wraps when the score loops")
    # Adding the score path must not change a controller with no score bound to it: the old reading is
    # "distance + index" from the flood fill, and the old programme is the redstone strength itself.
    check("scoreId" in be and "PartyLightsTape.frame(" in be,
          "controller entity: a bound score moves the programme from the signal to the tape")
    check("PartyLightsScore.distance(" in be,
          "controller entity: a focus replaces the flood-fill distance for every lamp it drives")
    for field in ('"Score"', '"StartedAt"', '"Lamps"', '"MaxDistance"', '"Step"', '"StepTicks"'):
        check(field in be, "controller entity: persists " + field.strip('"') + " for `data get block`")
    check('getStringOr("Score"' in be,
          "controller entity: reads its score id back as a string, empty meaning none")
    # Binding is by id, so one JSON can drive many controllers and a datapack swap re-costumes a house
    # without touching a block. The item is only the handle: any renamed item whose name parses works.
    check("bindScore" in block and "unbindScore" in block,
          "controller block: a renamed item binds a score, crouching unbinds it")
    check("PartyLightsScores.parse(" in block,
          "controller block: the name on the item is resolved through the score loader")
    check("SimpleJsonResourceReloadListener" in scores and "FileToIdConverter.json(" in scores,
          "score loader: reads data/<ns>/party_lights/*.json through a vanilla reload listener")
    check("AddServerReloadListenersEvent" in main and "PartyLightsScores.LISTENER_ID" in main,
          "score loader: registered on the server reload so /reload picks a new tape up")
    # Ties are settled by the player, block order only breaks the remaining ties. Priority has to be
    # read from the neighbour's state, which is why the flood fill takes the level and not a snapshot.
    check("priorityAt" in network and "PartyLightsControllerBlock.PRIORITY" in network,
          "network: a lamp touching two controllers goes to the higher priority, block order breaks ties")
    check("focus" in drive and "PartyLightsScore.distance(" in drive,
          "rope drive: a cord lamp measures its own distance from the focus, not from the cord's foot")
    check("decode" in drive and '",nil"' in drive,
          "rope drive: the synched tag carries the focus and still decodes a pre-score payload")

    # The shipped examples are the ones a player actually reads. Load them the way the game does: any
    # unknown programme, an empty step list or a tempo outside 4..200 would fail the whole reload.
    for name in ("ribbon_demo", "porch_night"):
        path = SCORE_DATA / (name + ".json")
        check(path.exists(), "score data: " + name + ".json ships")
        if not path.exists():
            continue
        try:
            tape_json = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            check(False, "score data: " + name + ".json parses (" + str(error) + ")")
            continue
        tempo = tape_json.get("tempo", 16)
        steps = tape_json.get("steps") or []
        check(4 <= tempo <= 200, "score data: " + name + " tempo " + str(tempo) + " is inside 4..200")
        check(1 <= len(steps) <= 64, "score data: " + name + " has 1..64 steps")
        for step in steps:
            programme = step.get("program")
            ticks = step.get("ticks")
            check(programme in PROGRAM_NAMES,
                  "score data: " + name + " step names " + str(programme) + ", which the table knows")
            check(isinstance(ticks, int) and 1 <= ticks <= 1200,
                  "score data: " + name + " step runs " + str(ticks) + " ticks, inside 1..1200")
            check(isinstance(step.get("focus"), (list, type(None))) or step.get("focus") is None,
                  "score data: " + name + " focus is a position or absent")


def player_and_chain_checks():
    """The four player-observation fixes: shift-to-off, Jade name, static sheets, cord chain claim."""
    block = BLOCK.read_text(encoding="utf-8")
    check("player.isSecondaryUseActive() ? Mode.OFF" in block,
          "player: sneak right-click turns the lamp straight off, not a four-step cycle")
    lang = ROOT / "src/main/java/com/pastoralhome/data/ModLanguageProvider.java"
    check("addEntityType(ModEntities.BRIDGE_ROPE" in lang.read_text(encoding="utf-8"),
          "Jade: the rope entity has a display name, not the raw language key")
    rope = (ROOT / "src/main/java/com/pastoralhome/entity/BridgeRopeEntity.java").read_text(encoding="utf-8")
    pick = (ROOT / "src/main/java/com/pastoralhome/client/RopePickPolicy.java").read_text(encoding="utf-8")
    check("removeLampUnderCrosshair" in rope and "lampBox(" in rope and ".clip(from, to)" in rope,
          "rope: sneak-right-click ray-tests the aimed lamp body, not the whole cord")
    check("? this.removeLampUnderCrosshair(serverLevel, player)" in rope
          and ": this.cycleLampMode(serverLevel, player)" in rope,
          "rope: empty right-click cycles the cord, sneak-right-click takes one lamp")
    kb = rope.find("public void kill(ServerLevel level)")
    check(kb >= 0 and "discard" not in rope[kb:kb + 120] and "spawnAtLocation" not in rope[kb:kb + 120],
          "rope: kill() is a no-op so mob clearing cannot remove a tied cord")
    check("player.getMainHandItem().isEmpty() && player.getOffhandItem().isEmpty()" in pick,
          "rope: empty hands pick the cord without holding a lamp or sneaking")
    lang_text = lang.read_text(encoding="utf-8")
    check("bridge_rope.no_lamp_targeted" in lang_text and "bridge_rope.lamp_removed" in lang_text,
          "rope: interaction feedback strings exist for aiming and removing")
    gen_lang = ROOT / "src/generated/resources/assets/pastoral_home/lang/en_us.json"
    if gen_lang.exists():
        check("entity.pastoral_home.bridge_rope" in gen_lang.read_text(encoding="utf-8"),
              "Jade: generated lang carries the rope entity name (datagen has been run)")
    be = CONTROLLER_BE.read_text(encoding="utf-8")
    check("members.count() == 0" not in be[be.find("private List<BridgeRopeEntity> findRopes"):
                                           be.find("private List<BridgeRopeEntity> findRopes") + 4000],
          "network: a controller wired only to a fence still owns its cord")
    check("while (grew)" in be and "cells.add(support.asLong())" in be
          and "claimed.contains(rope.getId())" in be,
          "network: claiming one cord adds its supports so a chained cord joins transitively")
    check("members.count() == 0 && ropes.isEmpty()" in be,
          "network: a rope-only controller still drives its cords (no block lamps needed)")

def main():
    player_and_chain_checks()
    rope_network_checks()
    score_checks()
    geometry_checks()
    uv_checks()
    intent_checks()
    sheet_checks()
    state_checks()
    item_checks()
    display_checks()
    particle_checks()
    hanger_checks()
    contract_checks()
    controller_checks()
    failed = [label for ok, label in checks if not ok]
    for label in failed:
        print("FAIL " + label)
    print(("{} of {} checks passed".format(len(checks) - len(failed), len(checks))))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
