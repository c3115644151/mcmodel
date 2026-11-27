#!/usr/bin/env python3
"""Verify mature/unripe berry baskets, authored cord rendering, and ceiling placement assets."""
from __future__ import annotations

import json
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "src/main/resources/assets/pastoral_home"
WORK = ROOT / "build/glow_berry_basket_models"
SOURCE = ROOT / "tools/deploy/model_sources/glow_berry_basket"


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def authored_a_frame_strap(element: dict) -> bool:
    start, end = element["from"], element["to"]
    rotation = element.get("rotation", {})
    return (abs(float(start[1]) - 15.0) < 0.01 and abs(float(end[1]) - 32.0) < 0.01
            and abs(float(start[2]) - float(end[2])) < 0.01
            and abs(abs(float(rotation.get("angle", 0.0))) - 45.0) < 0.01)


for model_name, source_name, texture_name in (
        ("short_unripe", "glow_berry_hanging_basket_variant_1", "glow_berry_basket_unripe"),
        ("short_ripe", "glow_berry_hanging_basket_variant_2", "glow_berry_basket_ripe")):
    source = read(WORK / f"{source_name}.json")
    short = read(ASSETS / f"models/block/glow_berry_basket_{model_name}.json")
    assert short["elements"] == source["elements"], f"{model_name} no longer matches the authored model"
    assert short["textures"]["bb_texture_0"] == f"pastoral_home:block/{texture_name}"
    assert (ASSETS / f"textures/block/{texture_name}.png").is_file()
    long_name = model_name.replace("short_", "") + "_parallel"
    long_model = read(ASSETS / f"models/block/glow_berry_basket_{long_name}.json")
    expected_long = [element for element in short["elements"] if not authored_a_frame_strap(element)]
    assert len(short["elements"]) - len(expected_long) == 2
    assert long_model["elements"] == expected_long, \
        f"{long_name} should replace the short A-frame with its continuous parallel cord state"

for obsolete in ASSETS.joinpath("textures/block").glob("glow_berry_basket_cord_*.png"):
    assert not obsolete.exists(), f"rejected custom cord atlas image remains: {obsolete.name}"
blockstate = read(ASSETS / "blockstates/glow_berry_basket.json")
assert len(blockstate["multipart"]) == 4
renderer = (ROOT / "src/main/java/com/pastoralhome/client/renderer/GlowBerryBasketCordRenderer.java").read_text(
    encoding="utf-8")
assert '"models/block/hanging_rope_segment.json"' in renderer
assert '"block/hanging_rope_segment"' in renderer
assert "ROPE_THICKNESS_SCALE = 0.5F" in renderer
assert "2.5F, 2.5F" in renderer and "13.5F, 13.5F" in renderer, \
    "four cords should end on the pot rim, not inside the planter"
assert "length + 1.0F" in renderer and "shouldRenderOffScreen" in renderer
assert "LevelRenderer.getLightCoords" in renderer and "LightCoordsUtil.FULL_BRIGHT" not in renderer, \
    "rope segments must receive world light rather than emit fullbright light themselves"
blocks = (ROOT / "src/main/java/com/pastoralhome/registry/ModBlocks.java").read_text(encoding="utf-8")
assert ".lightLevel(state -> state.getValue(GlowBerryBasketBlock.BERRIES) ? 14 : 0)" in blocks, \
    "only ripe glow berries should make the basket a level-14 light source"
block_source = (ROOT / "src/main/java/com/pastoralhome/block/GlowBerryBasketBlock.java").read_text(encoding="utf-8")
assert "{{2.5,2.5}, {13.5,13.5}, {2.5,13.5}, {13.5,2.5}}" in block_source, \
    "selection outlines must track the four rendered cords at the rim corners"
assert "SpriteId" in renderer and "sprite.getU(" in renderer and "sprite.getV(" in renderer
assert "RenderTypes.cutoutMovingBlock()" in renderer and "sprite.wrap" not in renderer, \
    "rope segments should use the block model atlas with direct sprite UVs, without a second UV transform"
block_registry = (ROOT / "src/main/java/com/pastoralhome/registry/ModBlocks.java").read_text(encoding="utf-8")
assert "GLOW_BERRY_BASKET_ROPE" not in block_registry, "cord length must not create separate rope blocks"
assert not (ASSETS / "blockstates/glow_berry_basket_rope.json").exists()
assert not (ASSETS / "models/block/glow_berry_basket_rope_extension.json").exists()
bootstrap = (ROOT / "src/main/java/com/pastoralhome/PastoralHome.java").read_text(encoding="utf-8")
assert "GlowBerryBasketCordRenderer::new" in bootstrap
item = read(ASSETS / "items/glow_berry_basket.json")
assert item["model"]["type"] == "minecraft:select"
assert item["model"]["property"] == "minecraft:display_context"
assert item["model"]["cases"][0]["when"] == "gui"
assert item["model"]["cases"][0]["model"]["model"] == \
    "pastoral_home:item_icons/glow_berry_basket/variant_0"
assert item["model"]["fallback"]["model"] == "pastoral_home:block/glow_berry_basket_short_unripe"
icon_report = read(ROOT / "build/glow_berry_basket_models/item_icon_preview.json")[0]
assert icon_report["bounds_within_16px_cell"]
# The woven texture leaves the bottom edge of the basket transparent, so the visible
# silhouette is 1.4 icon pixels higher than the slot centre even though the model is
# centred. Every other furniture icon is a solid silhouette and holds 0.5px, so this
# tolerance is stated once, here, next to the reason instead of relaxing the shared gate.
assert abs(icon_report["projected_gui_center_offset"][0]) <= 0.5
assert icon_report["projected_gui_center_offset"][1] >= -1.5
assert icon_report["projected_gui_size"][0] >= 8 and icon_report["projected_gui_size"][1] >= 10
# The slot icon must come from the single-cell pose; a proxy built from the hanging
# pose shrinks the basket to a sixth of the slot (6.56x8.52 px), which is what made
# the item unreadable in the inventory.
assert item["model"]["cases"][0]["model"]["model"] != \
    "pastoral_home:block/glow_berry_basket_short_unripe"
# The unripe icon keeps the single-cell crop: no berries to show, so the A-frame
# hanger would only waste slot space. The ripe icon is the full plant - basket,
# side berries, glowing vine and A-frame hanger. normalize_item_icons.py fits the
# whole pose into one block, so the hanging geometry no longer shrinks the basket.
unripe_source = read(ASSETS / "models/block/glow_berry_basket_icon_unripe.json")
assert unripe_source["elements"], "unripe icon source has no geometry"
assert all(float(element["to"][1]) <= 16.2 for element in unripe_source["elements"]), \
    "unripe icon source still carries the hanging strands"
ripe_source = read(ASSETS / "models/block/glow_berry_basket_icon_ripe.json")
assert ripe_source["elements"], "ripe icon source has no geometry"
assert any(float(element["to"][1]) > 16.2 for element in ripe_source["elements"]), \
    "ripe icon must keep the vine + A-frame hanger, not a bare planter"

# The slot icon must show the ripe basket with its glowing berry strands, not the
# bare unripe pot. This is an art-direction choice: the ripe source keeps the fruit.
gui_proxy = read(ASSETS / "models/item_icons/glow_berry_basket/variant_0.json")
assert gui_proxy["parent"] == "pastoral_home:block/glow_berry_basket_icon_ripe", \
    "GUI proxy must source the ripe basket so the inventory icon keeps its berries"
assert len(ripe_source["elements"]) > len(unripe_source["elements"]), \
    "ripe icon source must carry more geometry than the bare unripe pot"

block = (ROOT / "src/main/java/com/pastoralhome/block/GlowBerryBasketBlock.java").read_text(encoding="utf-8")
assert "{{2.5,2.5}, {13.5,13.5}, {2.5,13.5}, {13.5,2.5}}" in block
item_code = (ROOT / "src/main/java/com/pastoralhome/item/GlowBerryBasketItem.java").read_text(encoding="utf-8")
assert "BonemealableBlock" in block and "randomTick" in block and "BERRIES" in block
assert "isFaceSturdy" in item_code and "Direction.DOWN" in item_code
assert "MAX_LENGTH" in block and "LENGTH" in block
loot = read(ROOT / "src/generated/resources/data/pastoral_home/loot_table/blocks/glow_berry_basket.json")
assert loot["pools"][0]["entries"][0]["name"] == "pastoral_home:glow_berry_basket"
print("Glow-berry basket assets verified: authored short pose, thin rim-mounted rope extensions, no rope blocks, item and loot.")
