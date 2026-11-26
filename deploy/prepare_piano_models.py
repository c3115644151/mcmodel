#!/usr/bin/env python3
r"""Rebuild the piano static assets from tools/deploy/model_sources/instruments/piano_recolor.bbmodel.

The artist's delivery is authority for the cabinet, key-well floor/back wall and the two key
samples. The generator only performs the mechanical work a Blockbench file cannot express:

* centre the 43 px shell in the 48 px 3x2 footprint and align depth to PianoBlock's 0..6 px
  contract (the recolour source is 1 px deeper than the original art);
* turn the delivered floor/back wall into the OPEN key well from the design brief: floor top
  y 13.6, back wall front z 5.7, back wall bottom y 13.6;
* EXCLUDE the two sample keys from every static cell model -- a static key would remain behind
  when a player presses one, which is the whole problem this redesign exists to solve;
* write the samples as standalone block models in pivot-local coordinates, so the BER copies one
  sample to all 25 keys and rotates only the pressed ones;
* keep the item model a full STATIC keyboard, because the inventory has no per-key state.

Numerical contract (design/piano-art-brief.md sections 6/12, PianoBlock.java):
    pitch = 2.3333 px, white face width = pitch - 2*0.06 = 2.2133 px,
    black width = 1.1 px; key pivots are the artist's rear-bottom edges, NOT the key-bed floor.
    white pivot (centre, 14.4, 4.0), black pivot (centre, 14.3, 4.0).
"""
from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "src/main/resources/assets/pastoral_home"
MODELS = ASSETS / "models/block"
TEXTURES = ASSETS / "textures/block"
PIANO_BLOCK = ROOT / "src/main/java/com/pastoralhome/block/PianoBlock.java"
SOURCE = ROOT / "tools/deploy/model_sources/instruments/piano_recolor.bbmodel"
IMPORTER = ROOT / "tools/deploy/import_java_block_bbmodel.py"
RAW = ROOT / "build/instrument_models/piano_recolor_raw.json"
TEX_DIR = ROOT / "build/instrument_models/piano_recolor_tex"
TEX_OUT = ROOT / "build/piano_recolor_cabinet.png"
GEOMETRY = ROOT / "build/instrument_models/piano_key_geometry.json"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from block_item_model import block_item_model  # noqa: E402
from prepare_instrument_models import (  # noqa: E402
    cell_bounds, clamp_depth, extents, save, shift, split_model,
)

PIANO_COLUMNS = 3
PIANO_LAYERS = 2
FOOTPRINT = PIANO_COLUMNS * 16.0
DEPTH_EPSILON = 0.05
SHELL_X_SHIFT = 16.0     # -13.5 source + 2.5 centred margin
SHELL_Z_SHIFT = -1.0     # recolour art is 1 px deeper than the original art
FLOOR_TOP_Y = 13.6
BACK_FRONT_Z = 5.7
BACK_BOTTOM_Y = 13.6
KEY_GAP_PX = 0.06
WHITE_LENGTH_PX = 4.0    # artist shortened the key so it no longer sinks into the inner wall
WHITE_THICKNESS_PX = 1.6  # artist thickened the key: it read too flat before
BLACK_LENGTH_PX = 2.7
BLACK_THICKNESS_PX = 2.4
WHITE_PIVOT_Y = 14.4   # artist key sample from y=14.4; rear-bottom edge is the hinge
WHITE_PIVOT_Z = 4.0    # artist key sample z[1,5] shifted -1 -> [0,4]; rear edge at 4
BLACK_PIVOT_Y = 14.3   # artist black key from y=14.3
BLACK_PIVOT_Z = 4.0    # artist black key z[2.3,5] shifted -1 -> [1.3,4]; rear edge at 4

# Kept for tools/deploy/piano_key_report.py and older audit imports.
BED_TOP_Y = 12.0
SHELF_TOP_Y = FLOOR_TOP_Y
FIELD_TOP_Y = 14.6
CASING_TOP_Y = 16.0
ART_TEXELS = 128
ART_LIP_ROWS = (69, 71)
PALETTE_SIZE = 64
TEXELS_PER_BLOCK = 16
KEYS_SIZE = 128
KEYS_UV_PER_PX = 0.375
TONES = {
    "light": (0, (255, 236, 208, 255)),
    "mid": (1, (221, 193, 168, 255)),
    "shade": (2, (200, 166, 148, 255)),
    "navy": (3, (54, 53, 73, 255)),
}
DEFAULTS = {
    "field_back_px": BACK_FRONT_Z,
    "black_width_px": 1.1,
    "black_raise_px": 1.0,
    "black_front_px": 1.9,
    "black_back_px": 5.6,
    "key_gap_px": KEY_GAP_PX,
}


def load_band_params() -> dict:
    spec = ROOT / "tools/deploy/piano_keys.json"
    data = json.loads(spec.read_text(encoding="utf-8")) if spec.is_file() else {}
    unknown = set(data) - set(DEFAULTS) - {"_comment"}
    if unknown:
        raise SystemExit(f"piano_keys.json has unknown keys: {sorted(unknown)}")
    params = dict(DEFAULTS)
    params.update({key: float(value) for key, value in data.items() if key in DEFAULTS})
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
    found = {}
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
    return (semitones[index % len(semitones)] + 1) % 12 not in semitones


def black_key_boundaries(constants: dict) -> list[int]:
    return [boundary for boundary in range(1, int(constants["WHITE_KEYS"]))
            if black_key_after(constants["semitones"], boundary - 1)]


def import_recolor() -> dict:
    if not SOURCE.is_file():
        raise SystemExit(f"missing art source {SOURCE}")
    subprocess.run([
        sys.executable, str(IMPORTER), str(SOURCE),
        "--model-out", str(RAW),
        "--texture-out", str(TEX_OUT),
        "--texture-dir", str(TEX_DIR),
        "--texture-name", "piano_recolor",
        "--texture-prefix", "piano_recolor",
    ], cwd=ROOT, check=True)
    return json.loads(RAW.read_text(encoding="utf-8"))


def classify_samples(raw: dict) -> tuple[dict, dict]:
    """The recolor model names its two sample keys 白键 / 黑键; geometry is a fallback."""
    named = {}
    for element in raw["elements"]:
        if element["from"][2] >= -8.0:
            continue
        name = str(element.get("name", ""))
        if "白" in name or "white" in name.lower():
            kind = "white"
        elif "黑" in name or "black" in name.lower():
            kind = "black"
        else:
            width = float(element["to"][0]) - float(element["from"][0])
            kind = "white" if width > 1.5 else "black"
        if kind in named:
            raise SystemExit(f"duplicate {kind} sample key in the source model")
        named[kind] = element
    if set(named) != {"white", "black"}:
        raise SystemExit(f"the art source must ship one white and one black sample key, got {sorted(named)}")
    return named["white"], named["black"]


def open_key_well(model: dict) -> None:
    """Turn the artist's solid key bed into the open slot the design brief specifies."""
    floors = [element for element in model["elements"]
              if abs(float(element["from"][1]) - 12.0) < 1e-6
              and abs(float(element["to"][1]) - 14.0) < 1e-6
              and float(element["to"][0]) - float(element["from"][0]) > 30.0
              and "#bb_texture_1" in {face.get("texture") for face in element["faces"].values()}]
    backs = [element for element in model["elements"]
             if abs(float(element["from"][1]) - 14.0) < 1e-6
             and abs(float(element["to"][1]) - 16.0) < 1e-6
             and "#bb_texture_2" in {face.get("texture") for face in element["faces"].values()}]
    if len(floors) != 1 or len(backs) != 1:
        raise SystemExit(f"expected one key-well floor and one back wall, got {len(floors)}/{len(backs)}")
    floors[0]["to"][1] = FLOOR_TOP_Y
    backs[0]["from"][1] = BACK_BOTTOM_Y
    backs[0]["from"][2] = BACK_FRONT_Z


def remap_sample_faces(sample: dict, texture_key: str) -> dict:
    """Map the artist's sample uv windows onto the rear-pivot key orientation.

    Both the artist sample and our pivot-local key run z from front (negative) to rear (zero):
    the sample spans -16..-10.5, our pivot-local key spans -length..0 with the rear pivot at z=0.
    North is the -z (front) face and south is the +z (rear) face in both, so uv windows map
    one-to-one; east/west/up/down are unchanged.
    """
    faces = sample["faces"]

    def uv(face: str) -> list[float]:
        if face not in faces:
            raise SystemExit(f"the sample key has no {face} face")
        return list(faces[face]["uv"])

    return {
        "north": {"texture": f"#{texture_key}", "uv": uv("north")},
        "south": {"texture": f"#{texture_key}", "uv": uv("south")},
        "east": {"texture": f"#{texture_key}", "uv": uv("east")},
        "west": {"texture": f"#{texture_key}", "uv": uv("west")},
        "up": {"texture": f"#{texture_key}", "uv": uv("up")},
        "down": {"texture": f"#{texture_key}", "uv": uv("down")},
    }


def standalone_key_model(sample: dict, kind: str) -> dict:
    tex_index = 3 if kind == "white" else 4
    texture_key = f"bb_texture_{tex_index}"
    constants = block_constants()
    params = load_band_params()
    pitch = white_key_width(constants)
    width = pitch - 2.0 * params["key_gap_px"] if kind == "white" else params["black_width_px"]
    length = WHITE_LENGTH_PX if kind == "white" else BLACK_LENGTH_PX
    thickness = WHITE_THICKNESS_PX if kind == "white" else BLACK_THICKNESS_PX
    return {
        "parent": "minecraft:block/block",
        "ambientocclusion": True,
        "textures": {
            texture_key: f"pastoral_home:block/piano_recolor_tex{tex_index}",
            "particle": "pastoral_home:block/piano_recolor_particle",
        },
        "elements": [{
            "from": [round(-width / 2.0, 6), 0.0, round(-length, 6)],
            "to": [round(width / 2.0, 6), round(thickness, 6), 0.0],
            "faces": remap_sample_faces(sample, texture_key),
            "name": f"piano_{kind}_key",
        }],
    }


def static_key_element(sample: dict, kind: str, centre_x: float, constants: dict, params: dict) -> dict:
    """A raised, unpressed key for the item model: full keyboard, still static in the inventory."""
    tex_index = 3 if kind == "white" else 4
    pitch = white_key_width(constants)
    width = pitch - 2.0 * params["key_gap_px"] if kind == "white" else params["black_width_px"]
    length = WHITE_LENGTH_PX if kind == "white" else BLACK_LENGTH_PX
    thickness = WHITE_THICKNESS_PX if kind == "white" else BLACK_THICKNESS_PX
    pivot_z = WHITE_PIVOT_Z if kind == "white" else BLACK_PIVOT_Z
    pivot_y = WHITE_PIVOT_Y if kind == "white" else BLACK_PIVOT_Y
    return {
        "from": [round(centre_x - width / 2.0, 6), round(pivot_y, 6), round(pivot_z - length, 6)],
        "to": [round(centre_x + width / 2.0, 6), round(pivot_y + thickness, 6), round(pivot_z, 6)],
        "faces": remap_sample_faces(sample, f"bb_texture_{tex_index}"),
        "name": f"item_{kind}_key",
    }


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
    constants = block_constants()
    params = load_band_params()
    pitch = white_key_width(constants)
    white_face = pitch - 2.0 * params["key_gap_px"]
    print(f"keyboard {constants['KEY_MIN_X']:g}..{constants['KEY_MAX_X']:g} px, "
          f"{int(constants['WHITE_KEYS'])} white keys at {pitch:.4f} px pitch, "
          f"white face {white_face:.4f} px, black {params['black_width_px']:.4f} px")

    raw = import_recolor()
    white_sample, black_sample = classify_samples(raw)
    static = copy.deepcopy(raw)
    static["elements"] = [element for element in static["elements"]
                          if element["from"][2] >= -8.0]
    if len(static["elements"]) != 11:
        raise SystemExit(f"expected 11 static shell elements, got {len(static['elements'])}")
    static = shift(static, SHELL_X_SHIFT, 0.0, SHELL_Z_SHIFT)
    open_key_well(static)
    clamped = clamp_depth(static, DEPTH_EPSILON, 16.0 - DEPTH_EPSILON)
    x0, y0, z0, x1, y1, z1 = extents(static)
    if abs(x0 - 2.5) > 0.02 or abs(x1 - 45.5) > 0.02 or abs(y1 - 32.0) > 0.02:
        raise SystemExit(f"unexpected static piano extents: {(x0, y0, z0, x1, y1, z1)}")

    sources = {
        "piano_recolor": TEX_OUT,
        "piano_recolor_particle": TEX_OUT.with_name("piano_recolor_cabinet_particle.png"),
        "piano_recolor_tex1": TEX_DIR / "piano_recolor_tex1.png",
        "piano_recolor_tex2": TEX_DIR / "piano_recolor_tex2.png",
        "piano_recolor_tex3": TEX_DIR / "piano_recolor_tex3.png",
        "piano_recolor_tex4": TEX_DIR / "piano_recolor_tex4.png",
    }
    textures_written = []
    for name, source in sources.items():
        if not source.is_file():
            raise SystemExit(f"importer did not write {source}")
        target = TEXTURES / f"{name}.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        textures_written.append(target)
        print(f"wrote {target.relative_to(ROOT)}")

    cells, warnings = split_model(static, keep_seam_faces=True)
    if warnings:
        raise SystemExit(f"piano geometry crosses depth cells: {warnings}")
    written = list(textures_written)
    manifest = {"piano:depth_clamped": clamped}
    for (column, layer, row), elements in sorted(cells.items()):
        if row != 0:
            raise SystemExit(f"piano geometry leaked into depth row {row}")
        cell_model = copy.deepcopy(static)
        cell_model["elements"] = elements
        painted = {face["texture"] for element in elements for face in element["faces"].values()}
        for texture_key in list(cell_model["textures"]):
            if texture_key != "particle" and f"#{texture_key}" not in painted:
                cell_model["textures"].pop(texture_key, None)
        path = MODELS / f"piano_l{layer}_c{column}.json"
        save(path, cell_model)
        written.append(path)
        print(f"  piano_l{layer}_c{column}: {len(elements)} elements, bounds {cell_bounds(elements)}")
        manifest[f"piano:{layer}:{column}"] = {"elements": len(elements),
                                               "bounds": cell_bounds(elements)}

    white_model = standalone_key_model(white_sample, "white")
    black_model = standalone_key_model(black_sample, "black")
    save(MODELS / "piano_white_key_standalone.json", white_model)
    save(MODELS / "piano_black_key_standalone.json", black_model)
    written += [MODELS / "piano_white_key_standalone.json", MODELS / "piano_black_key_standalone.json"]
    save(GEOMETRY, {
        "pitch_px": pitch,
        "white_face_width_px": white_face,
        "black_width_px": params["black_width_px"],
        "key_gap_px": params["key_gap_px"],
        "white": {"pivot_y_px": WHITE_PIVOT_Y, "pivot_z_px": WHITE_PIVOT_Z,
                  "length_px": WHITE_LENGTH_PX, "thickness_px": WHITE_THICKNESS_PX,
                  "dip_px": 0.4334},
        "black": {"pivot_y_px": BLACK_PIVOT_Y, "pivot_z_px": BLACK_PIVOT_Z,
                  "length_px": BLACK_LENGTH_PX, "thickness_px": BLACK_THICKNESS_PX,
                  "dip_px": 0.4334},
        "well": {"floor_top_y_px": FLOOR_TOP_Y, "back_front_z_px": BACK_FRONT_Z,
                 "back_bottom_y_px": BACK_BOTTOM_Y},
    })

    item_model = copy.deepcopy(static)
    item_model["textures"]["bb_texture_3"] = "pastoral_home:block/piano_recolor_tex3"
    item_model["textures"]["bb_texture_4"] = "pastoral_home:block/piano_recolor_tex4"
    for index in range(int(constants["WHITE_KEYS"])):
        centre = constants["KEY_MIN_X"] + (index + 0.5) * pitch
        item_model["elements"].append(static_key_element(white_sample, "white", centre, constants, params))
    for boundary in black_key_boundaries(constants):
        centre = constants["KEY_MIN_X"] + boundary * pitch
        item_model["elements"].append(static_key_element(black_sample, "black", centre, constants, params))
    item_path = MODELS / "piano_item.json"
    save(item_path, block_item_model(item_model, label="piano"))
    written.append(item_path)
    save(ASSETS / "blockstates/piano.json", piano_blockstates())
    written.append(ASSETS / "blockstates/piano.json")
    save(ASSETS / "items/piano.json", {"model": {"type": "minecraft:select",
                                                 "property": "minecraft:display_context",
                                                 "cases": [{"when": "gui",
                                                            "model": {"type": "minecraft:model",
                                                                      "model": "pastoral_home:item_icons/piano/variant_0"}}],
                                                 "fallback": {"type": "minecraft:model",
                                                              "model": "pastoral_home:block/piano_item"}}})
    written.append(ASSETS / "items/piano.json")
    save(ROOT / "build/instrument_models/piano_manifest.json", manifest)
    for key, value in manifest.items():
        print(" ", key, value)

    if "--mirror" in sys.argv[1:]:
        mirror_to_build(written)


if __name__ == "__main__":
    main()
