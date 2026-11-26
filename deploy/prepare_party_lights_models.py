"""Build the party-lights models from the artist's .bbmodel: two states, one model each.

The lamp is a four-pixel shell, a core inside it, and a little hanger on top. The artist put the
hanger's outer face on the block's top plane, centred in x and z; that single placement is the model.
Every mounting face - ceiling, floor, the four walls - is reached by turning that one model in the
blockstate ("x" then "y"), so the model file stays the artist's geometry and the lamp cannot drift out
of shape when a mount is added.

The artist's texture is 32x128: four stacked 32x32 frames of the same drawing, frame 0 in the dim
palette and frame 2 in the lit one. A block model reads uv in sixteenths of the *frame*, which is what
Blockbench's uv editor shows (uv_width 32, uv_height 32), so each state ships a cropped 32x32 frame and
the artist's uv rects go in untouched - exactly what Blockbench's java_block export does. Feeding the
whole 32x128 sheet instead stretches every window across all four frames and the lamp turns into amber
bands.

The artist draws the lamp as a see-through paper cage around a bulb, and Blockbench shows exactly
that: a cream bulb inside an amber cage. The look is not painted - the sheet's alpha is binary
({0: 862, 255: 162} per frame) - it is the shell cube being authored with a negative size:
from.z(10) > to.z(6). The same coordinates go into the shipped model, together with the rotation
object Blockbench writes on every element.

How Minecraft treats that, read off the 26.1.2 sources: FaceBakery.bakeVertex selects corners as
vertexInfo.select(from, to) - from is the min corner and to the max corner, with no numeric
normalisation - so the shell's north quad lands on the z=10 plane facing north and its south quad on
the z=6 plane facing south, i.e. both are on the far side of the box and face away from a viewer.
FaceBakery.bakeQuad then only repairs the winding (`recalculateWinding`) when
`elementRotation == null && finalDirection != null`; because the element carries a rotation, the
repair is skipped and the two quads stay back-facing, so backface culling drops them and the bulb
inside shows through. Normalising from/to in Blockbench turns the cage into two solid amber cubes,
which is what a model file without the rotation object renders as.

The shell sheet therefore ships the artist's texels unchanged (alpha 255); SHELL_ALPHA only exists to
falsify that - it was the earlier workaround, kept reachable for comparison. Element order stays
core, shell, hanger, and the hanger draws on the core sheet.

Every element carries shade:false and light_emission:15 so the lamp renders at exactly the artist's
texel colours: no face-orientation shading, no sky/block light or AO modulation (26.1.2
VertexConsumer.putBlockBakedQuad reads the quad's lightEmission and forces the vertex lightmap to
full bright). The placed block's outward glow stays lightLevel=12 - that lights the room, it does not
tint the lamp. GUI/hand item proxies inherit both fields through deepcopy, so the icon matches too.

Run: .venv/Scripts/python.exe tools/deploy/prepare_party_lights_models.py [--mirror]
"""
from __future__ import annotations

import base64
import io
import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "tools/deploy/model_sources/party_lights/party_lights.bbmodel"
ASSETS = ROOT / "src/main/resources/assets/pastoral_home"
MODELS = ASSETS / "models/block"
TEXTURES = ASSETS / "textures/block"
BLOCKSTATES = ASSETS / "blockstates"

# Frame of the artist's 32x128 sheet that each state draws: dim, then lit.
STATE_FRAMES = {"unlit": 0, "lit": 2}
FRAME = 32
SHEET_SIZE = (32, 128)
# The artist's sheets are binary: the alpha histogram is exactly {0: 862, 255: 162} per frame, so the
# paper's translucency is not authored anywhere. The see-through cage comes from the shell's reversed
# z instead (see the module docstring), so every sheet ships exactly as painted. Anything below 255
# here is the abandoned alpha workaround, reachable only for side-by-side comparison.
SHELL_ALPHA = 255

LAMP = (0, 1, 2)
# The dropped twin sat at sheet x 2..6, so the kept lamp needs 4 px back to be centred.
LAMP_SHIFT = (-4.0, 0.0, 0.0)
# Which of the two sheets a part draws from: the shell has its own, everything else uses the core's.
PART_SHEET = {"core": "lamp_core", "shell": "lamp_shell", "neck": "lamp_core"}

ATTACHES = ("up", "down", "north", "south", "east", "west")
FACINGS = ("north", "east", "south", "west")
# Redstone turns the lamps into a display: the controller writes MODE=REMOTE on every lamp it
# reaches, so a variant exists for it like any other mode (6 mounts x 5 modes x 2 lit x 4 facings).
MODES = ("off", "chase", "steady", "beacon", "remote")
LIT_STATES = ("false", "true")

# The hanger points +Y in the model. Minecraft's "x"/"y" keys are Quadrant values, and Quadrant is
# named from -X: "x": 90 is BLOCK_ROT_X_90, which OctahedralGroup.java:67 defines as ROT_90_X_NEG, a
# *negative* quarter turn. Its matrix is (x, z, -y), so +Y lands on -Z (north) and "x": 90 hangs the
# lamp off the north wall, not the south one. "y": 90 is likewise ROT_90_Y_NEG. Applying x first and
# then y (Quadrant.fromXYZAngles composes z of y of x) reaches all six mounts with two integers:
# +Y -> south -> +X is east, +Y -> south -> -X is west. Both north and south shipped swapped once,
# which put the hanger into the player's face on two walls.
ROTATIONS = {
    "up":    {},
    "down":  {"x": 180},
    "south": {"x": 270},
    "north": {"x": 90},
    "east":  {"x": 270, "y": 270},
    "west":  {"x": 270, "y": 90},
}

# Item copies cannot borrow the placed block's trick. An item model is drawn without backface
# culling, so the shell's reversed quads survive there: keep all six and the cage closes into a
# solid amber box, drop the two that cull in world and the icon loses real faces. The item sheet
# therefore carries alpha, and BakedQuad.MaterialInfo.of picks the sheet from the sprite's own
# transparency - block-atlas sprites with a translucent texel go to Sheets.translucentBlockItemSheet()
# (blended, both sides drawn, BakedQuad.java:88-92), while the placed models keep their alpha-255
# sheet on the cutout path. Result: a complete translucent cage with the bulb behind it.
ITEM_SHELL_ALPHA = 235
# The held cameras aim at the mouth so the bulb reads first; the GUI context keeps vanilla's camera
# because the project's icon gate forbids anything else (any other yaw shows a block model's back
# face in a slot).
INVENTORY_DISPLAY = {
    "gui": {"rotation": [30.0, 225.0, 0.0], "translation": [0.0, 0.0, 0.0],
            "scale": [0.625, 0.625, 0.625]},
    "ground": {"rotation": [0.0, 0.0, 0.0], "translation": [0.0, 3.0, 0.0],
               "scale": [0.25, 0.25, 0.25]},
    "fixed": {"rotation": [0.0, 0.0, 0.0], "translation": [0.0, 0.0, 0.0],
              "scale": [0.5, 0.5, 0.5]},
    "thirdperson_righthand": {"rotation": [75.0, 0.0, 0.0], "translation": [0.0, 2.5, 0.0],
                              "scale": [0.375, 0.375, 0.375]},
    "firstperson_righthand": {"rotation": [0.0, 0.0, 0.0], "translation": [0.0, 0.0, 0.0],
                              "scale": [0.40, 0.40, 0.40]},
    "firstperson_lefthand": {"rotation": [0.0, 0.0, 0.0], "translation": [0.0, 0.0, 0.0],
                             "scale": [0.40, 0.40, 0.40]},
}

AXIS_INDEX = {"x": 0, "y": 1, "z": 2}


def load_source() -> dict:
    return json.loads(SRC.read_text(encoding="utf-8"))


def sheet_image(data: dict, index: int) -> Image.Image:
    raw = base64.b64decode(data["textures"][index]["source"].split(",", 1)[1])
    return Image.open(io.BytesIO(raw)).convert("RGBA")


def frame_image(data: dict, state: str) -> Image.Image:
    sheet = sheet_image(data, 0)
    if sheet.size != SHEET_SIZE:
        raise SystemExit(f"source sheet is {sheet.size}, expected {SHEET_SIZE}")
    top = STATE_FRAMES[state] * FRAME
    return sheet.crop((0, top, FRAME, top + FRAME))


ANIMATION = {"animation": {"frametime": 6}}


def write_sheet(image: Image.Image, name: str, animated: bool) -> None:
    """Write one texture, plus the descriptor that makes Minecraft read a 32x128 strip as 4 frames."""
    image.save(TEXTURES / (name + ".png"))
    meta = TEXTURES / (name + ".png.mcmeta")
    if animated:
        meta.write_text(json.dumps(ANIMATION, indent=2) + "\n", encoding="utf-8")
    elif meta.exists():
        meta.unlink()
        print(f"removed superseded {meta.relative_to(ROOT)}")


def ordered(element: dict) -> tuple[list[float], list[float]]:
    """The artist stores the cage with the z axis reversed; the model format wants from <= to."""
    low = [min(float(element["from"][i]), float(element["to"][i])) for i in range(3)]
    high = [max(float(element["from"][i]), float(element["to"][i])) for i in range(3)]
    return low, high


def shifted(box, offset) -> tuple[list[float], list[float]]:
    low = [round(box[0][i] + offset[i], 4) for i in range(3)]
    high = [round(box[1][i] + offset[i], 4) for i in range(3)]
    return low, high


def source_faces(element: dict) -> dict:
    """The artist's rectangles, verbatim - the same numbers Blockbench writes on java_block export."""
    return {face: [float(value) for value in spec["uv"]]
            for face, spec in element["faces"].items()
            if spec.get("texture") is not None}


def lamp_offset(boxes) -> list[float]:
    """Slide the artist's lamp so the hanger's top face lands on y=16 and the shell is centred."""
    neck = boxes[2]
    offset = [0.0, 0.0, 0.0]
    offset[1] = round(16.0 - max(neck[0][1], neck[1][1]), 4)
    for axis in ("x", "z"):
        j = AXIS_INDEX[axis]
        shell_low, shell_high = boxes[0]
        offset[j] = round(8.0 - (shell_low[j] + shell_high[j]) / 2.0, 4)
    return offset


def lamp_elements() -> list[dict]:
    artist = load_source()["elements"]
    boxes = [shifted(ordered(artist[index]), LAMP_SHIFT) for index in (LAMP[2], LAMP[0], LAMP[1])]
    offset = lamp_offset(boxes)
    out: list[dict] = []
    for name, index, box in (("core", LAMP[2], boxes[0]),
                             ("shell", LAMP[0], boxes[1]),
                             ("neck", LAMP[1], boxes[2])):
        low, high = shifted(box, offset)
        if name == "shell":
            # The artist's negative size, kept: z goes high -> low so the north and south quads land on
            # the far planes, and the rotation object stops Minecraft from repairing their winding.
            low, high = [low[0], low[1], high[2]], [high[0], high[1], low[2]]
        painted = source_faces(artist[index])
        faces = {face: {"texture": "#" + PART_SHEET[name], "uv": uv} for face, uv in painted.items()}
        element = {"name": name, "from": low, "to": high, "faces": faces}
        # Appearance must equal the artist's texels exactly, in every game lighting condition.
        # shade:false removes the face-orientation darkening; light_emission:15 makes the vertex
        # lightmap full bright regardless of sky/block light or AO (VertexConsumer.putBlockBakedQuad
        # -> QuadInstance.getLightCoordsWithEmission -> LightCoordsUtil.lightCoordsWithEmission,
        # 26.1.2 sources). The block's lightLevel=12 outward glow is separate and untouched.
        element["shade"] = False
        element["light_emission"] = 15
        if name == "shell":
            element["rotation"] = {"angle": 0.0, "axis": "y", "origin": [8.0, 8.0, 8.0]}
        out.append(element)
    return out


def frosted(image: Image.Image, alpha: int = SHELL_ALPHA) -> Image.Image:
    """Set the painted shell texels to one alpha; the artist's clear seams stay fully clear."""
    out = image.copy()
    pixels = out.load()
    for y in range(out.height):
        for x in range(out.width):
            r, g, b, a = pixels[x, y]
            if a:
                pixels[x, y] = (r, g, b, alpha)
    return out


def write_textures(data: dict) -> None:
    """Both states are static frames: a placed lamp only changes look when its block state changes.

    The artist's 32x128 strip animates in Blockbench, but one shared texture animation would make every
    hung lamp and every placed lamp breathe in lockstep with no per-lamp phase, and - critically - a
    STEADY lamp kept flickering even though its light level never moved. Brightness belongs to the
    block state (the `lit` property); the texture just draws the matching frame. Both sheets are now
    32x32 with no .mcmeta, so `lit=true` is genuinely steady.
    """
    for part in ("core", "shell"):
        unlit = frame_image(data, "unlit")
        lit = frame_image(data, "lit")
        if part == "shell" and SHELL_ALPHA < 255:
            unlit, lit = frosted(unlit), frosted(lit)
        write_sheet(unlit, f"party_lights_{part}_unlit", animated=False)
        write_sheet(lit, f"party_lights_{part}_lit", animated=False)
    # The item copy owns a third shell sheet: the same lit frame with translucent texels, so its quads
    # land on the blended item sheet instead of the cutout one (see ITEM_SHELL_ALPHA).
    write_sheet(frosted(frame_image(data, "lit"), ITEM_SHELL_ALPHA),
                "party_lights_shell_item", animated=False)
    print("wrote textures/block/party_lights_{core,shell}_{unlit,lit}.png (both 32x32 static frames, "
          "no animation: unlit frame 0, lit frame 2; "
          f"shell texels at alpha {SHELL_ALPHA}, core untouched at 255) plus "
          f"party_lights_shell_item.png at alpha {ITEM_SHELL_ALPHA}; the break tile is the build's, "
          "see normalize_block_model_particles.py")


def write_model(path: Path, elements: list[dict], state: str,
               display: dict | None = None, shell_texture: str | None = None) -> None:
    # Break debris is a derived tile named after the model, so the one repo-wide shaper owns it:
    # a texture merely mentioning "particle" is left alone, and the lamp's debris never gets a second
    # recipe that silently survives every later improvement (2026-11-26).
    textures = {"particle": f"pastoral_home:block/{path.stem}_particle",
                "lamp_shell": f"pastoral_home:block/{shell_texture or f'party_lights_shell_{state}'}",
                "lamp_core": f"pastoral_home:block/party_lights_core_{state}"}
    model = {
        "parent": "minecraft:block/block",
        "credit": "Derived from the artist's 彩灯.bbmodel",
        "textures": textures,
        "elements": elements,
    }
    if display:
        model["display"] = json.loads(json.dumps(display))
    path.write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_blockstates() -> None:
    variants = {}
    for attach in ATTACHES:
        for facing in FACINGS:
            for mode in MODES:
                for lit in LIT_STATES:
                    state = "lit" if lit == "true" else "unlit"
                    variant = {"model": f"pastoral_home:block/party_lights_{state}"}
                    variant.update(ROTATIONS[attach])
                    variants[f"attach={attach},facing={facing},mode={mode},lit={lit}"] = variant
    BLOCKSTATES.mkdir(parents=True, exist_ok=True)
    (BLOCKSTATES / "party_lights.json").write_text(
        json.dumps({"variants": variants}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote blockstates/party_lights.json ({len(variants)} variants, "
          f"{len(STATE_FRAMES)} models turned by x/y)")



# --- The redstone face: a companion block the artist never drew ------------------------------
# The controller is not in the .bbmodel, so its geometry and art are procedural, and they live in
# this same generator so the whole party-light feature ships from one command.
CONTROLLER_SIZE = 16
CONTROLLER_SIDE = (156, 115, 74)
CONTROLLER_SIDE_DARK = (124, 89, 57)
CONTROLLER_SIDE_LIGHT = (176, 135, 92)
CONTROLLER_FACE = {False: ((54, 44, 36), (122, 74, 40), (150, 100, 66)),
                   True: ((58, 46, 34), (243, 184, 88), (188, 120, 72))}
CONTROLLER_MODELS = {False: "party_lights_controller", True: "party_lights_controller_lit"}
CONTROLLER_ITEM = "party_lights_controller"
# Priority 0..3, highest first. It is a blockstate property (not a block-entity field) because the
# flood fill has to rank two neighbouring controllers while it walks blocks, and because a player
# reads it back with "data get block" rather than opening a menu.
CONTROLLER_PRIORITIES = (0, 1, 2, 3)


def planks() -> Image.Image:
    """A dark panelled wood body: seams every five rows, sparse light grain texels."""
    image = Image.new("RGBA", (CONTROLLER_SIZE, CONTROLLER_SIZE), CONTROLLER_SIDE + (255,))
    pixels = image.load()
    for y in range(CONTROLLER_SIZE):
        for x in range(CONTROLLER_SIZE):
            shade = CONTROLLER_SIDE_DARK if y % 5 == 4 else CONTROLLER_SIDE
            if y % 5 != 4 and (x * 3 + y * 7) % 11 == 0:
                shade = CONTROLLER_SIDE_LIGHT
            pixels[x, y] = shade + (255,)
    return image


def window(on: bool) -> Image.Image:
    """The reading face: an amber slot that brightens when the controller is eating signal."""
    base, slot, rivet = CONTROLLER_FACE[on]
    image = Image.new("RGBA", (CONTROLLER_SIZE, CONTROLLER_SIZE), base + (255,))
    pixels = image.load()
    for y in range(5, 11):
        for x in range(5, 11):
            pixels[x, y] = slot + (255,)
    for x, y in ((1, 1), (14, 1), (1, 14), (14, 14)):
        pixels[x, y] = rivet + (255,)
    return image


def controller_elements(face: str) -> list[dict]:
    """A 16-cube body whose z starts at 1, plus a plate that fills the last unit: no coplanar faces."""
    side = lambda uv: {"texture": "#side", "uv": uv}
    body = {"name": "body", "from": [0.0, 0.0, 1.0], "to": [16.0, 16.0, 16.0],
            "faces": {name: side([0, 0, 16, 16])
                      for name in ("north", "east", "south", "west", "up", "down")}}
    plate = {"name": "plate", "from": [2.0, 4.0, 0.0], "to": [14.0, 12.0, 1.0],
             "faces": {"north": {"texture": face, "uv": [2, 4, 14, 12]},
                       "east": side([0, 0, 1, 8]),
                       "west": side([0, 0, 1, 8]),
                       "up": side([2, 0, 14, 1]),
                       "down": side([2, 0, 14, 1])}}
    return [body, plate]


def write_controller() -> None:
    BLOCKSTATES.mkdir(parents=True, exist_ok=True)
    (ASSETS / "items").mkdir(parents=True, exist_ok=True)
    planks().save(TEXTURES / "party_lights_controller_side.png")
    window(False).save(TEXTURES / "party_lights_controller_face_off.png")
    window(True).save(TEXTURES / "party_lights_controller_face_on.png")
    for powered, stem in CONTROLLER_MODELS.items():
        textures = {"particle": f"pastoral_home:block/{stem}_particle",
                    "side": "pastoral_home:block/party_lights_controller_side",
                    "face": f"pastoral_home:block/party_lights_controller_face_{'on' if powered else 'off'}"}
        model = {"parent": "minecraft:block/block",
                 "credit": "Procedural companion to the party lights",
                 "textures": textures,
                 "elements": controller_elements("#face")}
        (MODELS / f"{stem}.json").write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n",
                                            encoding="utf-8")
    items = ASSETS / "items" / f"{CONTROLLER_ITEM}.json"
    if not items.exists():
        # Only the first bootstrap: from then on normalize_item_icons.py owns this definition, because
        # it rewrites it into the display-context select that points the GUI slot at a proxy.
        items.write_text(json.dumps({"model": {"type": "minecraft:model",
                                               "model": f"pastoral_home:block/{CONTROLLER_MODELS[False]}"}},
                                    ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    variants = {}
    for facing, yaw in (("north", 0), ("east", 90), ("south", 180), ("west", 270)):
        for powered in (False, True):
            for priority in CONTROLLER_PRIORITIES:
                variant = {"model": f"pastoral_home:block/{CONTROLLER_MODELS[powered]}"}
                if yaw:
                    variant["y"] = yaw
                variants[f"facing={facing},powered={'true' if powered else 'false'},priority={priority}"] = variant
    (BLOCKSTATES / f"{CONTROLLER_ITEM}.json").write_text(
        json.dumps({"variants": variants}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote controller: 2 models, 3 textures, {len(variants)} blockstate variants")


def main() -> None:
    data = load_source()
    TEXTURES.mkdir(parents=True, exist_ok=True)
    MODELS.mkdir(parents=True, exist_ok=True)
    write_textures(data)

    write_controller()

    kept = set()
    elements = lamp_elements()
    for state in STATE_FRAMES:
        path = MODELS / f"party_lights_{state}.json"
        write_model(path, elements, state)
        kept.add(path.name)
    # Same geometry, own shell sheet: no face is dropped, the cage reads whole because it is blended.
    write_model(MODELS / "party_lights_inventory.json", elements, "lit",
               display=INVENTORY_DISPLAY, shell_texture="party_lights_shell_item")
    kept.add("party_lights_inventory.json")
    kept |= {f"{stem}.json" for stem in CONTROLLER_MODELS.values()}

    for path in MODELS.glob("party_lights*.json"):
        if path.name not in kept:
            path.unlink()
            print(f"removed superseded {path.relative_to(ROOT)}")
    allowed = {f"party_lights_{part}_{state}.png" for state in STATE_FRAMES
               for part in ("core", "shell")}
    allowed |= {f"{stem}_particle.png" for stem in
                ["party_lights_" + state for state in STATE_FRAMES] + ["party_lights_inventory"]}
    # The lit sheets animate, so their descriptors are part of the shipped set.
    allowed |= {f"party_lights_{part}_lit.png.mcmeta" for part in ("core", "shell")}
    allowed |= {"party_lights_shell_item.png", "party_lights_shell_item.png.mcmeta"}
    allowed |= {"party_lights_controller_side.png", "party_lights_controller_face_off.png",
                "party_lights_controller_face_on.png"}
    allowed |= {f"{stem}_particle.png" for stem in CONTROLLER_MODELS.values()}
    for path in TEXTURES.glob("party_lights*"):
        if path.name not in allowed:
            path.unlink()
            print(f"removed superseded {path.relative_to(ROOT)}")

    write_blockstates()
    if "--mirror" in sys.argv[1:]:
        mirror_to_build()


def mirror_to_build() -> None:
    built = ROOT / "build/resources/main/assets/pastoral_home"
    copied = []
    for source_dir in (MODELS, TEXTURES, BLOCKSTATES):
        for path in source_dir.glob("party_lights*"):
            target = built / path.relative_to(ASSETS)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())
            copied.append(target.relative_to(ROOT))
    for source_dir in (MODELS, TEXTURES, BLOCKSTATES):
        for path in (built / source_dir.relative_to(ASSETS)).glob("party_lights*"):
            if not (ASSETS / path.relative_to(built)).exists():
                path.unlink()
                copied.append(f"removed {path.relative_to(ROOT)}")
    for rel in copied:
        print(f"mirrored {rel}")


if __name__ == "__main__":
    main()
