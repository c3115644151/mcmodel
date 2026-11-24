#!/usr/bin/env python3
"""Static asset and interaction-contract checks for the climbable hanging rope."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "src/main/resources/assets/pastoral_home"
WORK = ROOT / "build/bridge_rope_models"


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


for variant, source_name in (("segment", "bridge_rope_vertical_segment"),
                             ("end", "bridge_rope_vertical_end")):
    source = read(WORK / f"{source_name}.json")
    model = read(ASSETS / f"models/block/hanging_rope_{variant}.json")
    assert model["elements"] == source["elements"], f"{variant} model geometry diverged from the BBModel"
    texture = model["textures"]["bb_texture_0"]
    assert (ASSETS / "textures/block" / f"{texture.split('/', 1)[1]}.png").is_file()

blockstate = read(ASSETS / "blockstates/hanging_rope.json")
assert blockstate["variants"]["end=false"]["model"] == "pastoral_home:block/hanging_rope_segment"
assert blockstate["variants"]["end=true"]["model"] == "pastoral_home:block/hanging_rope_end"

block = (ROOT / "src/main/java/com/pastoralhome/block/HangingRopeBlock.java").read_text(encoding="utf-8")
item = (ROOT / "src/main/java/com/pastoralhome/item/BridgeRopeItem.java").read_text(encoding="utf-8")
tags = (ROOT / "src/main/java/com/pastoralhome/data/ModBlockTagsProvider.java").read_text(encoding="utf-8")
loot_provider = (ROOT / "src/main/java/com/pastoralhome/data/ModBlockLootProvider.java").read_text(encoding="utf-8")
assert "BlockTags.CLIMBABLE" in tags and "ModBlocks.HANGING_ROPE.get()" in tags
climbable = read(ROOT / "src/generated/resources/data/minecraft/tags/block/climbable.json")
assert "pastoral_home:hanging_rope" in climbable["values"]
assert "neighborState.is(this)" in block and "canSurvive" in block
assert "clickedFace() == Direction.DOWN" in item or "getClickedFace() == Direction.DOWN" in item
assert "HANGING_ROPE" in item and "isCrouching()" in item
assert "removeOtherEndpoint" in item or "removeFenceLink" in item
assert 'dropOther(output, ModBlocks.HANGING_ROPE.get(), ModItems.BRIDGE_ROPE.get())' in loot_provider
loot = read(ROOT / "src/generated/resources/data/pastoral_home/loot_table/blocks/hanging_rope.json")
assert loot["pools"][0]["entries"][0]["name"] == "pastoral_home:bridge_rope"
for locale, expected in (("zh_cn", "吊绳"), ("en_us", "Climbing Rope")):
    lang = read(ROOT / f"src/generated/resources/assets/pastoral_home/lang/{locale}.json")
    assert lang["item.pastoral_home.bridge_rope"] == expected
print("Hanging rope verified: authored segment/end meshes, climbable tag, support checks and two-mode interaction hooks.")
