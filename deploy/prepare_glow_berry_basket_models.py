#!/usr/bin/env python3
"""Import the glow-berry hanging basket, keeping growth and rope geometry as separate states."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "tools/deploy/model_sources/glow_berry_basket"
WORK = ROOT / "build/glow_berry_basket_models"
ASSETS = ROOT / "src/main/resources/assets/pastoral_home"
IMPORTER = ROOT / "tools/deploy/import_java_block_bbmodel.py"
VARIANTS = {
    "short_unripe": ("glow_berry_hanging_basket_variant_1", "glow_berry_basket_unripe"),
    "short_ripe": ("glow_berry_hanging_basket_variant_2", "glow_berry_basket_ripe"),
}


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def import_model(source_name: str, texture_name: str):
    model_path = WORK / f"{source_name}.json"
    texture_path = ASSETS / f"textures/block/{texture_name}.png"
    texture_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        sys.executable, str(IMPORTER), str(SOURCE / f"{source_name}.bbmodel"),
        "--model-out", str(model_path), "--texture-out", str(texture_path),
        "--texture-name", texture_name,
    ], cwd=ROOT, check=True)
    return read(model_path)


def is_top_strap(element: dict) -> bool:
    start, end = element["from"], element["to"]
    rotation = element.get("rotation", {})
    return (abs(float(start[1]) - 15.0) < 0.01
            and abs(float(end[1]) - 32.0) < 0.01
            and abs(float(end[2]) - float(start[2])) < 0.01
            and abs(abs(float(rotation.get("angle", 0.0))) - 45.0) < 0.01)


def main():
    roots = {}
    for key, (source_name, texture_name) in VARIANTS.items():
        raw = import_model(source_name, texture_name)
        roots[key] = raw
        short_path = ASSETS / f"models/block/glow_berry_basket_{key}.json"
        save(short_path, raw)

        long_model = copy.deepcopy(raw)
        straps = [element for element in long_model["elements"] if is_top_strap(element)]
        if len(straps) != 2:
            raise ValueError(f"Expected the two authored top straps in {source_name}, found {len(straps)}")
        # The single-cell pose owns the authored A-frame. Extended states use
        # four slim vertical strands rendered using the established rope segment material.
        long_model["elements"] = [element for element in long_model["elements"] if not is_top_strap(element)]
        save(ASSETS / f"models/block/glow_berry_basket_{key.removeprefix('short_')}_parallel.json", long_model)

        # A slot icon has one block of room, so it must show the basket and not the
        # strands that carry it to the ceiling: normalizing the hanging pose (32 units
        # tall) shrinks the basket to a sixth of the slot. Keeping only the geometry of
        # the single-cell pose fits the basket itself to the slot, which is what the
        # item reads as in the inventory.
        icon_model = copy.deepcopy(raw)
        icon_model["elements"] = [element for element in raw["elements"]
                                  if float(element["to"][1]) <= 16.2]
        if not icon_model["elements"]:
            raise ValueError(f"No single-cell geometry left for the {key} basket icon")
        save(ASSETS / f"models/block/glow_berry_basket_icon_{key.removeprefix('short_')}.json", icon_model)

    # Retire generated cord tiles from the rejected atlas-based renderer.
    for name in (
        "glow_berry_basket_cord_left.png", "glow_berry_basket_cord_right.png",
        *(f"glow_berry_basket_cord_{index}_{side}.png"
          for index in (0, 1) for side in ("left", "right")),
    ):
        (ASSETS / "textures/block" / name).unlink(missing_ok=True)
    save(ASSETS / "blockstates/glow_berry_basket.json", {
        "multipart": [
            {"when": {"berries": "false", "length": "1"},
             "apply": {"model": "pastoral_home:block/glow_berry_basket_short_unripe"}},
            {"when": {"berries": "true", "length": "1"},
             "apply": {"model": "pastoral_home:block/glow_berry_basket_short_ripe"}},
            {"when": {"berries": "false", "length": "2|3|4|5|6|7|8|9|10|11|12|13|14|15|16"},
             "apply": {"model": "pastoral_home:block/glow_berry_basket_unripe_parallel"}},
            {"when": {"berries": "true", "length": "2|3|4|5|6|7|8|9|10|11|12|13|14|15|16"},
             "apply": {"model": "pastoral_home:block/glow_berry_basket_ripe_parallel"}},
        ]
    })
    # The GUI branch points at the cordless icon source; normalize_item_icons.py
    # replaces that reference with a generated proxy and keeps the hanging pose as the
    # held/world fallback.
    save(ASSETS / "items/glow_berry_basket.json", {
        "model": {
            "type": "minecraft:select",
            "property": "minecraft:display_context",
            "cases": [{"when": "gui",
                       "model": {"type": "minecraft:model",
                                 "model": "pastoral_home:block/glow_berry_basket_icon_ripe"}}],
            "fallback": {"type": "minecraft:model",
                         "model": "pastoral_home:block/glow_berry_basket_short_unripe"},
        }
    })
    save(WORK / "glow_berry_basket_asset_manifest.json", {
        "short_ripe_cubes": len(roots["short_ripe"]["elements"]),
        "short_unripe_cubes": len(roots["short_unripe"]["elements"]),
        "authored_roof_straps_replaced_by_art_derived_parallel_cords": 2,
        "parallel_rope_cords": 4,
        "length_stages": list(range(1, 17)),
    })
    print("Prepared both authored berry stages; extended cords reuse the hanging-rope segment mesh and texture.")


if __name__ == "__main__":
    main()
