#!/usr/bin/env python3
r"""Rebuild the piano entirely from instruments/piano.bbmodel.

The piano is a three-wide by two-high structure. Everything below derives from two inputs: the
authored Blockbench source and the layout constants in PianoBlock.java, which are also what the
block uses to decide where a click lands.

The keyboard is assembled as a SHELF, the way a real one is built, instead of as stripes on a front
face. At fifteen white keys over 35 px the pitch is 2.3333 px, so a per-key seam would have to be
sub-pixel and would mip away; an earlier revision did exactly that and shipped as cream/navy zebra
stripes with no horizontal surface at all. What actually carries the read is the profile:

    shelf  y 12.0 .. 13.6, z 0.05 .. 6.0   wooden key slip, the artist's lip rows keep its front
    band   y 13.6 .. 14.6, z 0.05 .. field_back
                                           ivory: its front face is the white-key fronts, its top
                                           face is the continuous key field a player looks down on
    blacks y 14.6 .. 14.6 + raise          navy slabs on the field, set back from its front edge
    board  y 14.6 .. 16.0, z field_back .. 6.0
                                           the nameboard closing the field at the back

No per-key seams and no shaded gap slabs exist any more: the ivory field is one continuous surface,
because at this pitch a geometric seam is either invisible or wider than the key it separates.

Tuning loop, numbers first:

Tuning loop, numbers first:
    1. edit tools/deploy/piano_keys.json (seam width, black key size, key depths)
    2. .venv\Scripts\python.exe tools/deploy/prepare_piano_models.py --mirror
    3. .venv\Scripts\python.exe tools/deploy/piano_key_report.py
The report measures the assembled shelf as numbers (field continuity, black key pitch offsets,
raise and depth ratios against the real instrument, uv continuity across cell seams); only once it
passes is an image worth looking at:
    .venv\Scripts\python.exe tools/deploy/preview_block_model.py "piano_l0_c0:0,0;piano_l0_c1:16,0;piano_l0_c2:32,0;piano_l1_c0:0,16;piano_l1_c1:16,16;piano_l1_c2:32,16" --out build/clay/piano_full.png --views front,quarter,iso --fit --size 820x620
--mirror also copies the assets into build/resources/main so a single "reload" in a running client
picks them up without a restart.
"""
from __future__ import annotations

import copy
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "src/main/resources/assets/pastoral_home"
MODELS = ASSETS / "models/block"
PALETTE = ASSETS / "textures/block/piano_palette.png"
KEYS = ASSETS / "textures/block/piano_keys.png"
ARTWORK = ASSETS / "textures/block/piano.png"
PIANO_BLOCK = ROOT / "src/main/java/com/pastoralhome/block/PianoBlock.java"
sys.path.insert(0, str(ROOT / "tools/deploy"))
from prepare_instrument_models import (  # noqa: E402
    cell_bounds, clamp_depth, extents, import_model, save, shift, split_model,
)

PIANO_COLUMNS = 3
PIANO_LAYERS = 2
FOOTPRINT = PIANO_COLUMNS * 16.0
DEPTH_EPSILON = 0.05

# The shelf the keyboard is built on, in model pixels (one texel of piano.png is one pixel).
BED_TOP_Y = 12.0          # the key slip's underside, where the case fascia starts
SHELF_TOP_Y = 13.6        # the wooden slip ends here; the ivory band starts
FIELD_TOP_Y = 14.6        # the ivory band's top face: the key field a player looks down on
CASING_TOP_Y = 16.0       # the keyboard never reaches the cell top, or keys would cross layers
ART_LIP_ROWS = (69, 71)   # the lip occupies texel rows 69..70 of a 128 px sheet
ART_TEXELS = 128

# A palette sheet: each tone is a block of texels, and every face samples the middle of a block, so
# mip levels stay inside one flat colour whatever the distance.
PALETTE_SIZE = 64
TEXELS_PER_BLOCK = 16
TONES = {
    "light": (0, (255, 236, 208, 255)),
    "mid": (1, (221, 193, 168, 255)),
    "shade": (2, (200, 166, 148, 255)),
    "navy": (3, (54, 53, 73, 255)),
}
ALL_FACES = ("north", "south", "east", "west", "up", "down")

# The ivory field is one slab, so every white key separation has to come from its top face's
# texture: a 2.3333 px pitch cannot carry a geometric seam that survives the block-scale mip chain.
# 0.375 uv per pixel puts exactly 3 texels on each pixel, so one key pitch is exactly 7 texels: the
# seam columns land on integer texels with no rounding, and every key border renders at the same
# distance. A non-integral rate (0.4 -> 3.2 texels/px, 7.4667 texels a key) makes the seams alternate
# 7 and 8 texels, which reads as uneven key widths at block scale.
KEYS_SIZE = 128
KEYS_UV_PER_PX = 0.375
KEYS_TEXELS_PER_PX = KEYS_SIZE / 16.0 * KEYS_UV_PER_PX

SPEC = ROOT / "tools/deploy/piano_keys.json"
DEFAULTS = {
    "field_back_px": 5.7,    # where the ivory field ends and the nameboard starts
    "black_width_px": 1.1,   # 0.47 of the 2.3333 px pitch, as on a real keyboard
    "black_raise_px": 1.0,   # how far the blacks stand above the ivory field
    "black_front_px": 1.9,   # blacks start a third of the way back
    "black_back_px": 5.6,    # ... and run back to the nameboard, as real blacks do
}


def load_band_params() -> dict:
    """Knobs from piano_keys.json, validated so a bad edit fails here and not in-game."""
    data = json.loads(SPEC.read_text(encoding="utf-8")) if SPEC.exists() else {}
    unknown = set(data) - set(DEFAULTS) - {"_comment"}
    if unknown:
        raise SystemExit(f"piano_keys.json has unknown keys: {sorted(unknown)}")
    params = dict(DEFAULTS)
    params.update({key: float(value) for key, value in data.items() if key in DEFAULTS})
    if not 2.0 <= params["field_back_px"] <= 6.0 - DEPTH_EPSILON:
        raise SystemExit(f"field_back_px must leave room for the blacks and the nameboard: {params}")
    if not 0.5 <= params["black_width_px"] <= 2.0:
        raise SystemExit(f"black_width_px must stay between half and two pixels: {params}")
    if not 0.6 <= params["black_raise_px"] <= CASING_TOP_Y - FIELD_TOP_Y:
        raise SystemExit(f"black_raise_px must lift the blacks but stay under the casing: {params}")
    # Real blacks butt against the nameboard at the back of the white keys; ending them early
    # leaves a bare ivory strip behind the blacks and the keyboard stops reading as one.
    if not params["field_back_px"] - 0.3 <= params["black_back_px"] < params["field_back_px"]:
        raise SystemExit(f"black_back_px must reach the nameboard: {params}")
    if not DEPTH_EPSILON + 0.5 <= params["black_front_px"] <= 0.45 * params["field_back_px"]:
        raise SystemExit(f"black_front_px must start a third of the way back: {params}")
    return params


def block_constants() -> dict:
    source = PIANO_BLOCK.read_text(encoding="utf-8")
    wanted = {
        "KEY_MIN_X": r"public static final double KEY_MIN_X = ([\d.]+);",
        "KEY_MAX_X": r"public static final double KEY_MAX_X = ([\d.]+);",
        "KEY_DEPTH": r"public static final double KEY_DEPTH = ([\d.]+);",
        "BLACK_KEY_DEPTH": r"public static final double BLACK_KEY_DEPTH = ([\d.]+);",
        "WHITE_KEYS": r"private static final double WHITE_KEYS = ([\d.]+);",
    }
    found: dict[str, float] = {}
    for name, pattern in wanted.items():
        match = re.search(pattern, source)
        if match is None:
            raise SystemExit(f"PianoBlock.java no longer declares {name}")
        found[name] = float(match.group(1))
    semitones = re.search(r"WHITE_SEMITONES = \{([^}]*)\}", source)
    if semitones is None:
        raise SystemExit("PianoBlock.java no longer declares WHITE_SEMITONES")
    found["semitones"] = [int(part) for part in semitones.group(1).split(",") if part.strip()]
    return found


def white_key_width(constants: dict) -> float:
    return (constants["KEY_MAX_X"] - constants["KEY_MIN_X"]) / int(constants["WHITE_KEYS"])


def black_key_after(semitones: list[int], index: int) -> bool:
    """A black key sits after a white key unless the next semitone is itself a white key."""
    return (semitones[index % len(semitones)] + 1) % 12 not in semitones


def black_key_boundaries(constants: dict) -> list[int]:
    """Which white-key boundaries carry a black key, as boundary indices 1..WHITE_KEYS-1."""
    return [boundary for boundary in range(1, int(constants["WHITE_KEYS"]))
            if black_key_after(constants["semitones"], boundary - 1)]


def key_bed_element(model: dict) -> dict:
    """The slab the keyboard lives on: the wide, shallow box under the lid."""
    for element in model["elements"]:
        if ("north" in element["faces"] and "up" in element["faces"]
                and abs(element["from"][1] - BED_TOP_Y) < 1e-6
                and abs(element["to"][1] - 16.0) < 1e-6
                and element["to"][0] - element["from"][0] > 8.0):
            return element
    raise SystemExit("source piano has no key bed")


def lip_uv(model: dict) -> list[float]:
    """The artist's wooden lip rows as a uv window, taken from the bed's own front face."""
    face = key_bed_element(model)["faces"]["north"]
    u0, _, u1, v1 = face["uv"]
    low = ART_LIP_ROWS[0] * 16.0 / ART_TEXELS
    high = ART_LIP_ROWS[1] * 16.0 / ART_TEXELS
    if not abs(high - max(face["uv"][1], v1)) < 1e-6:
        raise SystemExit(f"the lip must end at the bed's face bottom: {face['uv']}")
    return [u0, low, u1, high]


def carve_key_shelf(model: dict) -> list[float]:
    """Remove the painted bed box and hand back the artist's lip window for the new shelf.

    The bed is a solid 4 px tall box whose front face carries the whole painted band. The shelf
    replaces it volume for volume, but built from parts with a profile: a wooden slip, a continuous
    ivory field and raised black keys. Only the lip's own uv window survives the swap, so its pixels
    still come out of piano.png untouched.
    """
    bed = key_bed_element(model)
    lip = lip_uv(model)
    model["elements"].remove(bed)
    return lip


def write_palette() -> "Image":
    from PIL import Image

    sheet = Image.new("RGBA", (PALETTE_SIZE, PALETTE_SIZE), (0, 0, 0, 0))
    for texel, colour in TONES.values():
        for y in range(PALETTE_SIZE):
            for x in range(texel * TEXELS_PER_BLOCK, (texel + 1) * TEXELS_PER_BLOCK):
                sheet.putpixel((x, y), colour)
    return sheet


def write_keys_sheet(constants: dict) -> "Image":
    """The white keys: one light body with a single shade texel on every key boundary."""
    from PIL import Image

    sheet = Image.new("RGBA", (KEYS_SIZE, KEYS_SIZE), TONES["light"][1])
    seam = TONES["shade"][1]
    keys = int(constants["WHITE_KEYS"])
    span = (constants["KEY_MAX_X"] - constants["KEY_MIN_X"]) * KEYS_TEXELS_PER_PX
    for boundary in range(keys + 1):
        column = min(KEYS_SIZE - 1, int(round(boundary * span / keys)))
        for y in range(KEYS_SIZE):
            sheet.putpixel((column, y), seam)
    return sheet


def tone_uv(tone: str) -> list[float]:
    """A degenerate uv window in the middle of a tone block: flat colour at every mip level."""
    texel, _ = TONES[tone]
    centre = texel * TEXELS_PER_BLOCK + TEXELS_PER_BLOCK * 0.5
    scale = 16.0 / PALETTE_SIZE
    low = round((centre - 1.0) * scale, 4)
    high = round((centre + 1.0) * scale, 4)
    return [low, low, high, high]


def slab(low: tuple, high: tuple, tone: str, faces=ALL_FACES, name: str | None = None) -> dict:
    """One key piece. Named so previews and audits can pick a band out of the model."""
    uv = tone_uv(tone)
    element = {"from": [round(value, 6) for value in low],
               "to": [round(value, 6) for value in high],
               "faces": {face: {"texture": "#piano_palette", "uv": list(uv)} for face in faces}}
    if name:
        element["name"] = name
    return element


def keyboard_elements(constants: dict, params: dict, lip: list[float]) -> list[dict]:
    """Build the shelf the keyboard sits on: slip, continuous ivory field, raised blacks, nameboard."""
    pitch = white_key_width(constants)
    origin = constants["KEY_MIN_X"]
    end = constants["KEY_MAX_X"]
    low = DEPTH_EPSILON
    field_back = params["field_back_px"]
    black_front, black_back = params["black_front_px"], params["black_back_px"]
    elements: list[dict] = []

    # The wooden key slip: the fascia a real upright has under the keys. Its front keeps the
    # artist's lip pixels; everything else is the flat wood tone so mips cannot smear the band.
    slip = slab((origin, BED_TOP_Y, low), (end, SHELF_TOP_Y, 6.0), "mid",
                faces=("south", "east", "west", "down"), name="key_slip")
    slip["faces"]["north"] = {"texture": "#bb_texture_0", "uv": list(lip)}
    elements.append(slip)

    # The ivory field: one continuous surface. Only the front face carries the per-key hairlines
    # the geometry cannot hold -- that is the face a player standing at the piano reads, and it is
    # axis-aligned, so a 1 texel line stays a line. The top face stays a flat tone on purpose: seen
    # at a grazing angle a 0.33 px line degenerates into diagonal mip slivers that read as damage.
    field = slab((origin, SHELF_TOP_Y, low), (end, FIELD_TOP_Y, field_back), "light",
                 name="key_field")
    field["faces"]["north"] = {"texture": "#piano_keys",
                               "uv": [0.0, 0.0,
                                      round((end - origin) * KEYS_UV_PER_PX, 4),
                                      round((FIELD_TOP_Y - SHELF_TOP_Y) * KEYS_UV_PER_PX, 4)]}
    elements.append(field)

    # Black keys: narrower than a white key, set back from its front edge, and raised above the
    # field -- the three numbers that make a keyboard read as a keyboard at any distance.
    half = params["black_width_px"] * 0.5
    for boundary in black_key_boundaries(constants):
        centre = origin + boundary * pitch
        elements.append(slab((centre - half, FIELD_TOP_Y, black_front),
                             (centre + half, FIELD_TOP_Y + params["black_raise_px"], black_back),
                             "navy", faces=("north", "up", "east", "west"),
                             name=f"key_black_{boundary}"))

    # The nameboard closes the back of the field, so the ivory does not run into the case interior.
    elements.append(slab((origin, FIELD_TOP_Y, field_back), (end, CASING_TOP_Y, 6.0), "mid",
                         faces=("north", "up", "south", "east", "west"), name="key_nameboard"))
    return elements


def piano_blockstates() -> dict:
    parts = []
    for facing, rotation in (("north", 0), ("east", 90), ("south", 180), ("west", 270)):
        for layer in range(PIANO_LAYERS):
            for column in range(PIANO_COLUMNS):
                apply = {"model": f"pastoral_home:block/piano_l{layer}_c{column}"}
                if rotation:
                    apply["y"] = rotation
                parts.append({"when": {"facing": facing, "layer": str(layer), "column": str(column)},
                              "apply": apply})
    return {"multipart": parts}


def mirror_to_build(paths: list[Path]) -> None:
    """Copies assets into build/resources/main so a running client reloads them without a restart."""
    build_resources = ROOT / "build/resources/main/assets/pastoral_home"
    if not build_resources.parent.parent.exists():
        print("  build/resources missing, nothing mirrored")
        return
    for path in paths:
        target = build_resources / path.relative_to(ASSETS)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        print(f"  mirrored {path.relative_to(ASSETS)}")


def main() -> None:
    from block_item_model import block_item_model

    constants = block_constants()
    params = load_band_params()
    width = white_key_width(constants)
    print(f"keyboard {constants['KEY_MIN_X']:g}..{constants['KEY_MAX_X']:g} px, "
          f"{int(constants['WHITE_KEYS'])} white keys at {width:.4f} px pitch, "
          f"{len(black_key_boundaries(constants))} black keys "
          f"{params['black_width_px']:.4f} px wide "
          f"({params['black_width_px'] / width:.0%} of the pitch), raised "
          f"{params['black_raise_px']:g} px over a field {params['field_back_px'] - DEPTH_EPSILON:.2f} px deep")

    raw = import_model("piano")
    model = shift(raw, 13.5, 0.0, 0.0)
    left, _, _, right, _, _ = extents(model)
    margin = (FOOTPRINT - (right - left)) * 0.5
    model = shift(model, margin, 0.0, 0.0)
    clamped = clamp_depth(model, DEPTH_EPSILON, 16.0 - DEPTH_EPSILON)
    x0, y0, z0, x1, y1, z1 = extents(model)
    if (abs(x0 - margin) > 0.02 or abs(x1 - (FOOTPRINT - margin)) > 0.02
            or abs(y0) > 0.02 or abs(y1 - 32.0) > 0.02):
        raise SystemExit(f"unexpected piano extents: {(x0, y0, z0, x1, y1, z1)}")

    lip = carve_key_shelf(model)
    model["textures"]["piano_palette"] = "pastoral_home:block/piano_palette"
    model["textures"]["piano_keys"] = "pastoral_home:block/piano_keys"
    model["elements"].extend(keyboard_elements(constants, params, lip))

    palette = write_palette()
    PALETTE.parent.mkdir(parents=True, exist_ok=True)
    palette.save(PALETTE)
    print(f"wrote {PALETTE.relative_to(ROOT)} {palette.size}")

    keys_sheet = write_keys_sheet(constants)
    keys_sheet.save(KEYS)
    print(f"wrote {KEYS.relative_to(ROOT)} {keys_sheet.size}")

    # keep_seam_faces: the cabinet, top cap and key bed are three single elements that span all
    # three cells. Dropping the split faces leaves every half an open shell at the seam, and an
    # oblique view straight into that seam sees through into the model, which reads as the piano
    # being cut into three separate boxes. Keeping them closes each fragment.
    cells, warnings = split_model(model, keep_seam_faces=True)
    if warnings:
        raise SystemExit(f"piano geometry crosses cells: {warnings}")
    if sorted({key[0] for key in cells}) != list(range(PIANO_COLUMNS)):
        raise SystemExit("piano must occupy all three columns")
    if sorted({key[1] for key in cells}) != list(range(PIANO_LAYERS)):
        raise SystemExit("piano must occupy both layers")

    written: list[Path] = [PALETTE, KEYS]
    manifest = {"piano:depth_clamped": clamped}
    for (column, layer, row), elements in sorted(cells.items()):
        if row != 0:
            raise SystemExit("piano geometry leaked into depth row {row}")
        cell_model = copy.deepcopy(model)
        cell_model["elements"] = elements
        painted = {face["texture"] for element in cell_model["elements"]
                   for face in element["faces"].values()}
        for sheet in ("piano_palette", "piano_keys"):
            if f"#{sheet}" not in painted:
                cell_model["textures"].pop(sheet, None)
        path = MODELS / f"piano_l{layer}_c{column}.json"
        save(path, cell_model)
        written.append(path)
        print(f"  piano_l{layer}_c{column}: {len(elements)} elements, "
              f"bounds {cell_bounds(elements)}")
        manifest[f"piano:{layer}:{column}"] = {"elements": len(elements),
                                               "bounds": cell_bounds(elements)}

    save(MODELS / "piano_item.json", block_item_model(model, label="piano"))
    written.append(MODELS / "piano_item.json")
    save(ASSETS / "blockstates/piano.json", piano_blockstates())
    written.append(ASSETS / "blockstates/piano.json")
    save(ASSETS / "items/piano.json", {"model": {"type": "minecraft:model",
                                                 "model": "pastoral_home:block/piano_item"}})
    written.append(ASSETS / "items/piano.json")
    save(ROOT / "build/instrument_models/piano_manifest.json", manifest)
    for key, value in manifest.items():
        print(" ", key, value)

    if "--mirror" in sys.argv[1:]:
        mirror_to_build(written)


if __name__ == "__main__":
    main()
