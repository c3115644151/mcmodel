#!/usr/bin/env python3
"""Static resource contract for the two-pose six-cell wardrobe."""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "src/main/resources/assets/pastoral_home"


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


state = read(ASSETS / "blockstates/wardrobe.json")
parts = state["multipart"]
assert len(parts) == 48, f"expected 48 pose/facing/cell models, got {len(parts)}"
seen = set()
for part in parts:
    condition = part["when"]
    key = (condition["facing"], condition["open"], int(condition["layer"]), int(condition["column"]))
    assert key not in seen, f"duplicate model state {key}"
    seen.add(key)
    model_name = part["apply"]["model"].split(":", 1)[1].replace(":", "/")
    model_path = ASSETS / "models" / f"{model_name}.json"
    model = read(model_path)
    assert model.get("parent") == "minecraft:block/block", model_path
    assert model.get("textures", {}).get("particle") in {
        "pastoral_home:block/wardrobe_closed_particle",
        "pastoral_home:block/wardrobe_open_particle",
    }, model_path
    for texture in model["textures"].values():
        if texture.startswith("pastoral_home:block/"):
            texture_path = ASSETS / "textures/block" / f"{texture.split('/', 1)[1]}.png"
            assert texture_path.is_file(), f"missing texture {texture_path}"

for name in ("wardrobe_closed.png", "wardrobe_open.png"):
    with Image.open(ASSETS / "textures/block" / name) as image:
        assert image.width > 0 and image.height > 0
with Image.open(ASSETS / "textures/gui/wardrobe_inventory.png") as image:
    assert image.size == (176, 222), f"wardrobe screen must use the fixed vanilla container footprint, got {image.size}"
assert not list((ASSETS / "textures/block").glob("wardrobe_*_l*_c*_particle.png"))
assert not (ASSETS / "textures/block/wardrobe_item_particle.png").exists()
screen_source = (ROOT / "src/main/java/com/pastoralhome/client/WardrobeScreen.java").read_text(encoding="utf-8")
menu_source = (ROOT / "src/main/java/com/pastoralhome/inventory/WardrobeMenu.java").read_text(encoding="utf-8")
block_entity_source = (ROOT / "src/main/java/com/pastoralhome/blockentity/WardrobeBlockEntity.java").read_text(encoding="utf-8")
assert "textures/gui/wardrobe_inventory.png" in screen_source
assert "generic_54.png" not in screen_source, "wardrobe should use its complete custom interface"
assert "drawScrollbar(graphics)" in screen_source and "SCROLLBAR_THUMB_HEIGHT" in screen_source
assert "scrollToMouse(event.y())" in screen_source, "scrollbar thumb should support dragging"
assert "ContainerHelper.saveAllItems(output, items, true)" in block_entity_source
assert "ContainerHelper.loadAllItems(input, items)" in block_entity_source
assert "saveAdditional(ValueOutput output)" in block_entity_source
assert "loadAdditional(ValueInput input)" in block_entity_source
assert "drawSlotGrid" in screen_source, "custom linen background requires aligned visible slot wells"
assert "this.leftPos + WardrobeMenu.STORAGE_X" in screen_source
assert "this.topPos + WardrobeMenu.STORAGE_Y" in screen_source, "slot wells must align with menu slots"
for fixed_layout in ("SCREEN_WIDTH = 176", "SCREEN_HEIGHT = 222", "STORAGE_X = 8", "STORAGE_Y = 18",
                     "PLAYER_X = 8", "PLAYER_Y = 140", "PLAYER_HOTBAR_Y = 198"):
    assert fixed_layout in screen_source + menu_source, f"wardrobe layout must keep vanilla's {fixed_layout}"
assert "WardrobeMenu.STORAGE_COLUMNS, 3" in screen_source
assert "WardrobeMenu.PLAYER_HOTBAR_Y" in screen_source, "hotbar needs the vanilla 4px visual gap"

item = read(ASSETS / "items/wardrobe.json")
assert item["model"]["fallback"]["model"] == "pastoral_home:block/wardrobe_item"
assert (ASSETS / "models/item_icons/wardrobe/variant_0.json").is_file()
lang = read(ROOT / "src/generated/resources/assets/pastoral_home/lang/zh_cn.json")
assert lang["block.pastoral_home.wardrobe"] == "衣橱"
assert lang["container.pastoral_home.wardrobe"] == "衣橱"
assert (ROOT / "src/generated/resources/data/pastoral_home/loot_table/blocks/wardrobe.json").is_file()
preview = read(ROOT / "build/requested_models/wardrobe_item_preview.json")
wardrobe_preview = next(item for item in preview if item["item"] == "wardrobe")
assert wardrobe_preview["centered_within_half_pixel"], "wardrobe GUI icon must be centered"
assert wardrobe_preview["bounds_within_16px_cell"], "wardrobe GUI icon must stay inside the vanilla item cell"
print("Wardrobe static assets: 48 model-state mappings, dedicated GUI art, texture, localization, icon and loot verified.")
