#!/usr/bin/env python3
"""Assemble MCP-exported Blockbench models for the interior-furniture batch.

Run after exporting the source projects with export_blockbench_assets.py:
    python tools/deploy/build_interior_furniture_assets.py

This keeps the art-authored .bbmodel files untouched while making the intentional
render variants (lamp on/off, wall portrait probability variants) reproducible.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

EXPORTS = ROOT / "tmp_furniture_exports"
ASSETS = ROOT / "src/main/resources/assets/pastoral_home"
BLOCK_MODELS = ASSETS / "models/block"
ITEMS = ASSETS / "items"
BLOCKSTATES = ASSETS / "blockstates"
TEXTURES = ASSETS / "textures/block"


def read_model(name: str) -> dict:
    return json.loads((EXPORTS / f"{name}.json").read_text(encoding="utf-8"))


def save_model(name: str, model: dict) -> None:
    model.setdefault("parent", "minecraft:block/block")
    model.setdefault("textures", {})
    textures = model["textures"]
    primary_texture = textures.get("bb_texture_0") or next(
        (value for key, value in textures.items() if key != "particle"), None)
    if primary_texture and textures.get("particle") in (None, "minecraft:block/oak_planks"):
        textures["particle"] = primary_texture
    (BLOCK_MODELS / f"{name}.json").write_text(
        json.dumps(model, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def rename_texture(model: dict, old: str, new: str) -> None:
    model["textures"][old] = f"pastoral_home:block/{new}"


def copy_texture(folder: str, source_name: str, target_name: str) -> None:
    source = EXPORTS / folder / f"{source_name}.png"
    shutil.copy2(source, TEXTURES / f"{target_name}.png")


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def variant(model: str, facing: str, y: int = 0) -> dict:
    result = {"model": f"pastoral_home:block/{model}"}
    if y:
        result["y"] = y
    return result


def main() -> None:
    for directory in (BLOCK_MODELS, ITEMS, BLOCKSTATES, TEXTURES):
        directory.mkdir(parents=True, exist_ok=True)

    # Fruit remains visible, but its fruit geometry is intentionally not used by
    # the collision builder; fruit_basket_collision.json is a separate filtered
    # export made from the six woven basket elements only.
    fruit = read_model("fruit_basket")
    rename_texture(fruit, "bb_texture_0", "fruit_basket")
    save_model("fruit_basket", fruit)
    copy_texture("fruit_basket_textures", "fruit_basket", "fruit_basket")

    # The cabinet art supplies independent closed/open texture atlases.
    for state in ("closed", "open"):
        cabinet = read_model(f"double_door_cabinet_{state}")
        rename_texture(cabinet, "bb_texture_0", f"double_door_cabinet_{state}")
        save_model(f"double_door_cabinet_{state}", cabinet)
        copy_texture(f"double_door_cabinet_{state}_textures", f"double_door_cabinet_{state}",
                     f"double_door_cabinet_{state}")

    # Artist-defined group elements (indices 9..12) are the unlit appearance.
    # Lit mode hides only this group, as requested; all other geometry remains.
    lamp = read_model("lamp")
    lit = json.loads(json.dumps(lamp))
    lit["elements"] = lamp["elements"][:9]
    rename_texture(lamp, "bb_texture_0", "lamp_base")
    rename_texture(lamp, "bb_texture_1", "lamp_unlit")
    rename_texture(lit, "bb_texture_0", "lamp_base")
    rename_texture(lit, "bb_texture_1", "lamp_unlit")
    save_model("lamp_off", lamp)
    save_model("lamp_on", lit)
    copy_texture("lamp_textures", "lamp_base", "lamp_base")
    copy_texture("lamp_textures", "lamp_unlit", "lamp_unlit")

    flowers = read_model("flower_bush")
    # These two top-level planes sit wholly outside the potted flower's authored
    # footprint (one at z=-16, the other at x>16,z=20); omit those stray helpers.
    flowers["elements"] = [e for i, e in enumerate(flowers["elements"]) if i not in (1, 3)]
    rename_texture(flowers, "bb_texture_0", "flower_bush")
    save_model("flower_bush", flowers)
    copy_texture("flower_bush_textures", "flower_bush", "flower_bush")

    sleeping_bag = read_model("sleeping_bag")
    rename_texture(sleeping_bag, "bb_texture_0", "sleeping_bag")
    save_model("sleeping_bag", sleeping_bag)
    copy_texture("sleeping_bag_textures", "sleeping_bag", "sleeping_bag")

    portrait_models = {
        "portrait_a": "wall_portrait_a",
        "portrait_b": "wall_portrait_b",
        "portrait_rare": "wall_portrait_rare",
    }
    for output_name, source_name in portrait_models.items():
        portrait = read_model(source_name)
        # This is a freestanding tabletop portrait, not a wall-hanging model.
        # The art starts 0.3 px below zero; lift it onto the support surface.
        for element in portrait.get("elements", []):
            element["from"][1] += 0.3
            element["to"][1] += 0.3
            if element.get("rotation"):
                element["rotation"]["origin"][1] += 0.3
        rename_texture(portrait, "bb_texture_0", output_name)
        save_model(output_name, portrait)
        copy_texture("wall_portrait_textures", source_name, output_name)

    for item, model in {
        "fruit_basket": "fruit_basket",
        "double_door_cabinet": "double_door_cabinet_closed",
        "lamp": "lamp_off",
        "flower_bush": "flower_bush",
        "sleeping_bag": "sleeping_bag",
        "wall_portrait": "portrait_a",
    }.items():
        write_json(ITEMS / f"{item}.json", {
            "model": {"type": "minecraft:model", "model": f"pastoral_home:block/{model}"}
        })

    rotations = {"north": 0, "east": 90, "south": 180, "west": 270}
    write_json(BLOCKSTATES / "fruit_basket.json", {
        "variants": {"": variant("fruit_basket", "north")}
    })
    write_json(BLOCKSTATES / "double_door_cabinet.json", {
        "variants": {
            f"facing={facing},open={str(opened).lower()}": variant(
                f"double_door_cabinet_{'open' if opened else 'closed'}", facing, y
            )
            for facing, y in rotations.items() for opened in (False, True)
        }
    })
    write_json(BLOCKSTATES / "lamp.json", {
        "variants": {
            "lit=false": variant("lamp_off", "north"),
            "lit=true": variant("lamp_on", "north"),
        }
    })
    write_json(BLOCKSTATES / "flower_bush.json", {
        "variants": {"": variant("flower_bush", "north")}
    })
    write_json(BLOCKSTATES / "sleeping_bag.json", {
        "variants": {f"facing={facing}": variant("sleeping_bag", facing, y)
                     for facing, y in rotations.items()}
    })
    write_json(BLOCKSTATES / "wall_portrait.json", {
        "variants": {
            f"facing={facing},variant={number}": variant(
                "portrait_rare" if number == 2 else ("portrait_a" if number == 0 else "portrait_b"),
                facing, y
            )
            for facing, y in rotations.items() for number in range(3)
        }
    })


if __name__ == "__main__":
    main()
