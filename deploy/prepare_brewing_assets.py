#!/usr/bin/env python3
"""Import the authored drinkware and derive empty/filled vessel presentation layers."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "tools" / "deploy" / "model_sources" / "brewing"
IMPORTER = ROOT / "tools" / "deploy" / "import_java_block_bbmodel.py"
WORK = ROOT / "build" / "brewing_import"
ASSETS = ROOT / "src" / "main" / "resources" / "assets" / "pastoral_home"
ITEM_MODELS = ASSETS / "models" / "item" / "brewing"
ITEM_TEXTURES = ASSETS / "textures" / "item" / "brewing"
ITEM_DEFINITIONS = ASSETS / "items"

MARKS = ("grain", "honey", "berry", "herb", "citrus", "sparkling")
DEFAULT_COLOR = 0xD89332
# Stable Blockbench element UUIDs identify semantic roles; array order and
# equal bounding boxes are deliberately irrelevant to model cleanup.
SOURCE_LIQUID_UUIDS = {
    "glass_cup": ("61864984-72b3-e6b7-980b-77e7200edbcd", "02b914e0-264d-43df-e6b3-27996f86de80"),
    "wooden_mug": ("0ababaeb-75bd-0b8a-66ce-f74afc4cb4d1",),
}
EMPTY_CONTENT_UUIDS = {
    "glass_cup": ("e36cc5bf-3ed4-1570-2790-9e3c9f105157", "61864984-72b3-e6b7-980b-77e7200edbcd",
                  "46102de7-ba5e-d821-383f-63a3d3ecb226", "02b914e0-264d-43df-e6b3-27996f86de80"),
    "wooden_mug": ("0ababaeb-75bd-0b8a-66ce-f74afc4cb4d1", "e36cc5bf-3ed4-1570-2790-9e3c9f105157",
                   "46102de7-ba5e-d821-383f-63a3d3ecb226"),
}
AUTHORED_FOAM_UUIDS = {
    "glass_cup": ("e36cc5bf-3ed4-1570-2790-9e3c9f105157", "46102de7-ba5e-d821-383f-63a3d3ecb226"),
    "wooden_mug": ("e36cc5bf-3ed4-1570-2790-9e3c9f105157", "46102de7-ba5e-d821-383f-63a3d3ecb226"),
    "beer_bottle": (),
}

ITEM_DISPLAY = {
    "thirdperson_righthand": {"rotation": [0, 90, 0], "translation": [0, 1.5, -1], "scale": [0.5, 0.5, 0.5]},
    "thirdperson_lefthand": {"rotation": [0, -90, 0], "translation": [0, 1.5, -1], "scale": [0.5, 0.5, 0.5]},
    "firstperson_righthand": {"rotation": [0, 90, 0], "translation": [1.1, 2.8, 1.1], "scale": [0.62, 0.62, 0.62]},
    "firstperson_lefthand": {"rotation": [0, -90, 0], "translation": [1.1, 2.8, 1.1], "scale": [0.62, 0.62, 0.62]},
    # Same facing-aware view the block-item icons use: yaw 45 with a 30-degree tilt. The earlier
    # 225/25 pairing put the whole drinks set a quarter-turn away from the barrels beside it.
    "gui": {"rotation": [30, 45, 0], "translation": [0, 0, 0], "scale": [0.72, 0.72, 0.72]},
    "ground": {"translation": [0, 2.5, 0], "scale": [0.32, 0.32, 0.32]},
    "fixed": {"rotation": [0, 180, 0], "translation": [0, 0, 0], "scale": [0.58, 0.58, 0.58]},
}


def run_import(name: str) -> tuple[dict, Path]:
    source = SOURCE / f"{name}.bbmodel"
    model_path = WORK / f"{name}.json"
    texture_path = WORK / f"{name}.png"
    subprocess.run([
        sys.executable, str(IMPORTER), str(source),
        "--model-out", str(model_path),
        "--texture-out", str(texture_path),
        "--mod-id", "pastoral_home", "--texture-name", name,
    ], check=True)
    model = json.loads(model_path.read_text(encoding="utf-8"))
    return model, texture_path


def box_key(element: dict) -> tuple[float, ...]:
    a, b = element["from"], element["to"]
    return tuple(round(v, 4) for v in (*[min(float(x), float(y)) for x, y in zip(a, b)],
                                       *[max(float(x), float(y)) for x, y in zip(a, b)]))


def source_elements(name: str) -> list[dict]:
    authored = json.loads((SOURCE / f"{name}.bbmodel").read_text(encoding="utf-8"))
    return authored.get("elements", [])


def source_indices(name: str, uuids: tuple[str, ...]) -> set[int]:
    if not uuids:
        return set()
    elements = source_elements(name)
    matches = {index for index, element in enumerate(elements) if element.get("uuid") in uuids}
    if len(matches) != len(set(uuids)):
        raise ValueError(f"{name}: one or more semantic Blockbench UUIDs are missing or duplicated")
    return matches


def authored_visible_elements(name: str, elements: list[dict], include_contents: bool = True) -> list[dict]:
    """Keep all artist-authored visible geometry, including overlapping foam layers.

    Equal bounds are intentional in these models: separately textured cubes can
    compose a single foam cap. Only Blockbench's explicit visibility flag may
    mark an element as a hidden helper; geometric heuristics are not used.
    """
    source_elements_list = source_elements(name)
    if len(source_elements_list) != len(elements):
        raise ValueError(
            f"{name}: importer changed element count ({len(source_elements_list)} authored, "
            f"{len(elements)} imported); refusing to guess which geometry is disposable"
        )
    excluded_content = set() if include_contents else source_indices(name, EMPTY_CONTENT_UUIDS.get(name, ()))
    return [element for index, (original, element) in enumerate(zip(source_elements_list, elements))
            if original.get("visibility", True) is not False and index not in excluded_content]


def tint_authored_liquid(name: str, elements: list[dict]) -> None:
    for index in source_indices(name, SOURCE_LIQUID_UUIDS.get(name, ())):
        if index >= len(elements):
            raise ValueError(f"{name}: authored liquid element index {index} is missing")
        for face in elements[index].get("faces", {}).values():
            if isinstance(face, dict) and face.get("texture") is not None:
                face["tintindex"] = 0


def source_geometry_report(name: str) -> dict[str, int]:
    elements = source_elements(name)
    visible = [element for element in elements
               if element.get("type") == "cube" and element.get("visibility", True) is not False]
    foam_indices = source_indices(name, AUTHORED_FOAM_UUIDS.get(name, ()))
    foam_layers = [element for index, element in enumerate(elements)
                   if index in foam_indices and element.get("visibility", True) is not False]
    if len(foam_layers) != len(foam_indices):
        raise ValueError(f"{name}: an authored foam layer is missing or hidden")
    return {"visible_cubes": len(visible), "authored_foam_layers": len(foam_layers)}


def update_texture_namespace(model: dict, name: str) -> None:
    # Item models must inherit the item atlas; minecraft:block/block forces the block atlas in 26.1.
    model["parent"] = "minecraft:item/generated"
    model["ambientocclusion"] = False
    model["display"] = ITEM_DISPLAY
    for key, value in list(model.get("textures", {}).items()):
        if value.startswith("pastoral_home:block/"):
            model["textures"][key] = value.replace("pastoral_home:block/", "pastoral_home:item/brewing/")
    model["textures"]["particle"] = f"pastoral_home:item/brewing/{name}"


def texture_face(texture: str, tint: int | None = None, face: str = "up") -> dict:
    data = {"uv": [0, 0, 16, 16], "texture": texture}
    if tint is not None:
        data["tintindex"] = tint
    return {face: data}


def top_surface(y: float, texture: str, tint: int | None = None) -> dict:
    return {
        "from": [5.2, y, 5.2], "to": [10.8, y + 0.07, 10.8], "shade": False,
        "faces": texture_face(texture, tint, "up"),
    }


def make_interior_textures() -> None:
    """Bake the two empty-interior fills the empty vessel models reference."""
    ITEM_TEXTURES.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (16, 16), (165, 183, 194, 255)).save(ITEM_TEXTURES / "empty_glass_interior.png")
    Image.new("RGBA", (16, 16), (68, 43, 27, 255)).save(ITEM_TEXTURES / "empty_mug_interior.png")


def add_display(model: dict) -> None:
    model["display"] = ITEM_DISPLAY
    model["gui_light"] = "front"
    model["ambientocclusion"] = False


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def make_model(name: str, source: dict, include_fill: bool) -> dict:
    model = json.loads(json.dumps(source))
    if include_fill and name in SOURCE_LIQUID_UUIDS:
        tint_authored_liquid(name, model.get("elements", []))
    model["elements"] = authored_visible_elements(name, model.get("elements", []), include_contents=include_fill)
    update_texture_namespace(model, name)
    if name == "beer_bottle":
        add_display(model)
        return model

    if name == "glass_cup":
        # Beer is already authored as inner cubes. The filled path tints those
        # source faces above; empty cups omit them and keep only the inner well.
        if not include_fill:
            model["textures"]["empty_interior"] = "pastoral_home:item/brewing/empty_glass_interior"
            model["elements"].append(top_surface(9.92, "#empty_interior"))
    elif name == "wooden_mug":
        if not include_fill:
            model["textures"]["empty_interior"] = "pastoral_home:item/brewing/empty_mug_interior"
            model["elements"].append(top_surface(9.92, "#empty_interior"))
    add_display(model)
    return model


def make_item_definition(base_model: str, vessel: str | None, tinted: bool) -> dict:
    """One authored mesh for every context; the drink colour rides the tint, not the model.

    Per-mark meshes and per-context flat icons are deliberately absent: the vessel shape
    plus the tinted liquid already distinguish the drinks, and every extra branch is a
    second asset that can drift from the authored mesh.
    """
    if not tinted:
        return {"model": {"type": "minecraft:model", "model": f"pastoral_home:item/brewing/{base_model}"}}
    return {"model": {
        "type": "minecraft:model",
        "model": f"pastoral_home:item/brewing/{base_model}",
        "tints": [{"type": "pastoral_home:beverage_color", "default": DEFAULT_COLOR}],
    }}


def main() -> None:
    names = ("glass_cup", "wooden_mug", "beer_bottle")
    WORK.mkdir(parents=True, exist_ok=True)
    ITEM_MODELS.mkdir(parents=True, exist_ok=True)
    ITEM_TEXTURES.mkdir(parents=True, exist_ok=True)
    ITEM_DEFINITIONS.mkdir(parents=True, exist_ok=True)
    for obsolete_texture in ("glass_fill.png", "liquid_surface.png", "label_mask.png"):
        (ITEM_TEXTURES / obsolete_texture).unlink(missing_ok=True)

    for name in names:
        imported, texture_path = run_import(name)
        shutil.copy2(texture_path, ITEM_TEXTURES / f"{name}.png")

        empty = make_model(name, imported, include_fill=False)
        filled = make_model(name, imported, include_fill=True)
        base_name = f"{name}_base" if name != "beer_bottle" else "beer_bottle_base"
        write_json(ITEM_MODELS / f"{base_name}.json", filled)
        if name != "beer_bottle":
            write_json(ITEM_MODELS / f"empty_{name}.json", empty)

        # Retire the per-mark meshes and their overlay ancestors: the vessel is one mesh.
        for mark in MARKS:
            (ITEM_MODELS / f"{base_name}_{mark}.json").unlink(missing_ok=True)
            (ITEM_MODELS / f"{name}_mark_{mark}.json").unlink(missing_ok=True)

    for item, model in (("beer_bottle", "beer_bottle_base"),
                        ("beer_glass", "glass_cup_base"),
                        ("beer_mug", "wooden_mug_base")):
        vessel = {"beer_bottle": "beer_bottle", "beer_glass": "glass_cup", "beer_mug": "wooden_mug"}[item]
        write_json(ITEM_DEFINITIONS / f"{item}.json", make_item_definition(model, vessel, True))
    write_json(ITEM_DEFINITIONS / "empty_glass_cup.json", make_item_definition("empty_glass_cup", None, False))
    write_json(ITEM_DEFINITIONS / "empty_wooden_mug.json", make_item_definition("empty_wooden_mug", None, False))

    make_interior_textures()
    for mark in MARKS:
        (ITEM_TEXTURES / f"mark_{mark}.png").unlink(missing_ok=True)
    audit = {
        "models": list(names),
        "model_variant_strategy": "one vessel mesh per container; drink colour comes from the tint",
        "authored_geometry": {name: source_geometry_report(name) for name in names},
        "marks": list(MARKS),
        "recipe_item_identity": "pastoral_home:beverage_contents",
        "visible_source_geometry_preserved": True,
        "source_element_coordinates_preserved": True,
        "overlapping_authored_cubes_preserved": True,
        "hidden_helpers_removed_by_source_visibility": True,
        "tinted_surfaces": {"glass_cup": ["authored inner drink cubes"],
                            "wooden_mug": ["authored inner drink cube"],
                            "beer_bottle": ["no authored liquid surface; label texture is the only body detail"]},
    }
    (WORK / "brewing_assets_audit.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print("Prepared empty and filled drinkware with tintable beverage surfaces; one mesh per container.")


if __name__ == "__main__":
    main()
