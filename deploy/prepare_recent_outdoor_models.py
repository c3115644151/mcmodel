#!/usr/bin/env python3
"""Stage the seven reviewed outdoor .bbmodel imports for blockstates and item proxies."""

from __future__ import annotations

import copy
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "src/main/resources/assets/pastoral_home"
MODEL_DIR = ASSETS / "models/block"
STATE_DIR = ASSETS / "blockstates"
ITEM_DIR = ASSETS / "items"
LANG_DIR = ROOT / "src/generated/resources/assets/pastoral_home/lang"
RAW_DIR = ROOT / "build/recent_models"
SOURCE_DIR = ROOT / "tools/deploy/model_sources/recent_outdoor"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def shift_y(model: dict, amount: float) -> dict:
    result = copy.deepcopy(model)
    for element in result.get("elements", []):
        element["from"][1] += amount
        element["to"][1] += amount
        if element.get("rotation") and element["rotation"].get("origin"):
            element["rotation"]["origin"][1] += amount
    return result


def fit_axis(model: dict, axis: int, target_extent: float) -> dict:
    """Uniformly fit one source axis around the model center, keeping a small margin."""
    result = copy.deepcopy(model)
    coords = [float(value) for element in result.get("elements", [])
              for point in (element["from"], element["to"]) for value in (point[axis],)]
    if not coords:
        return result
    low, high = min(coords), max(coords)
    extent = high - low
    if extent <= target_extent or extent == 0:
        return result
    center = (low + high) / 2.0
    scale = target_extent / extent

    def project(value: float) -> float:
        return 8.0 + (float(value) - center) * scale

    for element in result.get("elements", []):
        element["from"][axis] = project(element["from"][axis])
        element["to"][axis] = project(element["to"][axis])
        rotation = element.get("rotation")
        if rotation and rotation.get("origin"):
            rotation["origin"][axis] = project(rotation["origin"][axis])
    return result


def fit_axis_bounds(model: dict, axis: int, target_low: float, target_high: float) -> dict:
    """Fit one axis inside explicit model limits while preserving its low end."""
    result = copy.deepcopy(model)
    coords = [float(value) for element in result.get("elements", [])
              for point in (element["from"], element["to"]) for value in (point[axis],)]
    if not coords:
        return result
    low, high = min(coords), max(coords)
    extent = high - low
    allowed = target_high - target_low
    if extent <= allowed or extent == 0:
        return result
    scale = allowed / extent

    def project(value: float) -> float:
        return target_low + (float(value) - low) * scale

    for element in result.get("elements", []):
        element["from"][axis] = project(element["from"][axis])
        element["to"][axis] = project(element["to"][axis])
        rotation = element.get("rotation")
        if rotation and rotation.get("origin"):
            rotation["origin"][axis] = project(rotation["origin"][axis])
    return result


def facing_variants(model_id: str, states: tuple[str, ...] = ("facing",)) -> dict:
    variants = {}
    for facing, angle in (("north", 0), ("east", 90), ("south", 180), ("west", 270)):
        for state in states:
            key = f"facing={facing},{state}" if state else f"facing={facing}"
            variant = {"model": f"pastoral_home:block/{model_id}"}
            if angle:
                variant["y"] = angle
            variants[key] = variant
    return {"variants": variants}


def main() -> None:
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)

    def source_model(model_id: str) -> dict:
        raw_path = RAW_DIR / model_id / "model.json"
        path = raw_path if raw_path.is_file() else MODEL_DIR / f"{model_id}.json"
        model = load(path)
        save(SOURCE_DIR / f"{model_id}.json", model)
        return model

    # The lamp export contains an alternate lampshade group with the same bounds
    # and a different material. Keep one material set per visual state to prevent
    # coplanar overlap while the block's LIT state controls actual world light.
    lamp = source_model("floor_lamp")
    common = [2, 3, 4, 7, 8]
    off = copy.deepcopy(lamp)
    off["elements"] = [copy.deepcopy(lamp["elements"][i]) for i in [0, 1, 5, 6, *common]]
    on = copy.deepcopy(lamp)
    on["elements"] = [copy.deepcopy(lamp["elements"][i]) for i in [9, 10, 11, 12, *common]]
    off = shift_y(off, 2.0)
    on = shift_y(on, 2.0)
    # The source's 2px lift seats the feet on the floor but moves the shade to
    # y=34, beyond Minecraft's block-model coordinate limit of 32. Keep its
    # ground contact and compress the vertical span slightly into y=0..32.
    off = fit_axis_bounds(off, 1, 0.0, 32.0)
    on = fit_axis_bounds(on, 1, 0.0, 32.0)
    save(MODEL_DIR / "floor_lamp.json", off)
    save(MODEL_DIR / "floor_lamp_on.json", on)

    # The tripod feet in the source dip one pixel below the ground plane.
    # Raising the assembled telescope by 1.5px seats its feet on the block surface.
    telescope = shift_y(source_model("telescope"), 1.5)
    telescope = fit_axis(telescope, 2, 15.5)
    save(MODEL_DIR / "telescope.json", telescope)
    # The authored negative ladder-foot pixels intentionally sink into the floor;
    # keep the top platform at exactly the two-cell boundary.
    ladder = source_model("a_frame_ladder")
    save(MODEL_DIR / "a_frame_ladder.json", ladder)

    for model_id in ("greenery_2", "sunflower_planter", "one_cell_canopy", "globe"):
        save(MODEL_DIR / f"{model_id}.json", source_model(model_id))

    save(STATE_DIR / "greenery_2.json", facing_variants("greenery_2", ("",)))
    save(STATE_DIR / "sunflower_planter.json", facing_variants("sunflower_planter", ("",)))
    save(STATE_DIR / "one_cell_canopy.json", facing_variants("one_cell_canopy", ("",)))
    save(STATE_DIR / "globe.json", facing_variants("globe", ("",)))
    lamp_variants = {}
    for facing, angle in (("north", 0), ("east", 90), ("south", 180), ("west", 270)):
        for lit, model_id in (("false", "floor_lamp"), ("true", "floor_lamp_on")):
            for half in ("lower", "upper"):
                key = f"facing={facing},lit={lit},half={half}"
                value = {"model": f"pastoral_home:block/{model_id}"}
                if angle:
                    value["y"] = angle
                lamp_variants[key] = value
    save(STATE_DIR / "floor_lamp.json", {"variants": lamp_variants})

    telescope_variants = {}
    for facing, angle in (("north", 0), ("east", 90), ("south", 180), ("west", 270)):
        for half in ("lower", "upper"):
            key = f"facing={facing},half={half}"
            value = {"model": "pastoral_home:block/telescope"}
            if angle:
                value["y"] = angle
            telescope_variants[key] = value
    save(STATE_DIR / "telescope.json", {"variants": telescope_variants})

    ladder_variants = {}
    for facing, angle in (("north", 0), ("east", 90), ("south", 180), ("west", 270)):
        for half in ("lower", "upper"):
            key = f"facing={facing},half={half}"
            value = {"model": "pastoral_home:block/a_frame_ladder"}
            if angle:
                value["y"] = angle
            ladder_variants[key] = value
    save(STATE_DIR / "a_frame_ladder.json", {"variants": ladder_variants})

    model_for_item = {
        "greenery_2": "greenery_2", "floor_lamp": "floor_lamp", "sunflower_planter": "sunflower_planter",
        "one_cell_canopy": "one_cell_canopy", "globe": "globe", "telescope": "telescope",
        "a_frame_ladder": "a_frame_ladder",
    }
    for item, model_id in model_for_item.items():
        save(ITEM_DIR / f"{item}.json", {"model": {
            "type": "minecraft:select",
            "property": "minecraft:display_context",
            "cases": [{"when": "gui", "model": {"type": "minecraft:model",
                       "model": f"pastoral_home:block/{model_id}"}}],
            "fallback": {"type": "minecraft:model", "model": f"pastoral_home:block/{model_id}"},
        }})

    translations = {
        "en_us": {
            "greenery_2": "Wooden Planter", "floor_lamp": "Floor Lamp",
            "sunflower_planter": "Sunflower Planter", "one_cell_canopy": "Canvas Shade Panel",
            "globe": "Table Globe", "telescope": "Telescope", "a_frame_ladder": "A-Frame Ladder",
        },
        "zh_cn": {
            "greenery_2": "木箱绿植", "floor_lamp": "落地灯",
            "sunflower_planter": "向日葵花盆", "one_cell_canopy": "单格帆布遮阳棚",
            "globe": "地球仪", "telescope": "望远镜", "a_frame_ladder": "人字梯",
        },
    }
    for locale, names in translations.items():
        path = LANG_DIR / f"{locale}.json"
        document = load(path)
        for item, name in names.items():
            document[f"block.pastoral_home.{item}"] = name
        document["message.pastoral_home.globe.location"] = {
            "en_us": "Biome: %s | Position: %s, %s, %s | Dimension: %s",
            "zh_cn": "生物群系：%s | 坐标：%s, %s, %s | 维度：%s",
        }[locale]
        save(path, document)

    print("Staged seven model resources, facing states, light states, item selectors, and language entries.")


if __name__ == "__main__":
    main()
