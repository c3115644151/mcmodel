#!/usr/bin/env python3
"""Verify the authored-template coin-pile presentation contract."""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "src/main/resources/assets/pastoral_home"
WORK = ROOT / "build/requested_models/currency"
SOURCE = ROOT / "tools/deploy/model_sources/currency"
LAYOUTS = (
    "stack_gold_a", "stack_gold_b", "stack_silver_a", "stack_silver_b",
    "stack_copper_a", "stack_copper_b", "mixed_gold_silver", "mixed_silver_copper",
)
SHAPES = ("a", "b")
STYLE_VALUES = ("stack_gold_a", "stack_gold_b", "stack_silver_a", "stack_silver_b",
                "stack_copper_a", "stack_copper_b", "mixed_gold_silver", "mixed_silver_copper")
COMPOSITIONS = (
    "gold", "silver", "copper", "gold_silver", "gold_copper", "silver_copper", "all_three",
)


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


assert len(list(SOURCE.glob("*.bbmodel"))) == 11
state = read(ASSETS / "blockstates/coin_pile.json")
assert len(state["multipart"]) == len(STYLE_VALUES) * len(COMPOSITIONS) * 17 + 3 * 4
for style, source_name in (("a", "stack_gold_a"), ("b", "stack_gold_b")):
    previous = {composition: 0.0 for composition in COMPOSITIONS}
    source = read(WORK / f"{source_name}.json")
    for composition in COMPOSITIONS:
        expected_colors = set()
        if composition == "gold": expected_colors = {"gold"}
        elif composition == "silver": expected_colors = {"silver"}
        elif composition == "copper": expected_colors = {"copper"}
        elif composition == "gold_silver": expected_colors = {"gold", "silver"}
        elif composition == "gold_copper": expected_colors = {"gold", "copper"}
        elif composition == "silver_copper": expected_colors = {"silver", "copper"}
        else: expected_colors = {"gold", "silver", "copper"}
        for stage in range(17):
            path = ASSETS / f"models/block/coin_pile/{style}_{composition}_stage_{stage}.json"
            model = read(path)
            visible_height = sum(abs(float(element["to"][1]) - float(element["from"][1]))
                                 for element in model["elements"])
            assert visible_height >= previous[composition], f"{style}/{composition} stage {stage} regressed in visible stack height"
            previous[composition] = visible_height
            assert model.get("ambientocclusion", True) is True, \
                f"{style}/{composition} stage {stage} should retain vanilla ambient occlusion"
            assert all(element.get("shade", True) is True for element in model["elements"]), \
                f"{style}/{composition} stage {stage} should retain vanilla face shading"
            assert set(model["textures"]) >= {"coin_gold", "coin_silver", "coin_copper", "particle"}
            for texture in model["textures"].values():
                if texture.startswith("pastoral_home:block/"):
                    name = texture.split(":", 1)[1].split("/", 1)[1]
                    assert (ASSETS / "textures" / "block" / f"{name}.png").is_file(), (style, name)
            colors = {face.get("texture", "").removeprefix("#coin_")
                      for element in model["elements"] for face in element.get("faces", {}).values()}
            assert colors <= {"gold", "silver", "copper"}, (style, composition, colors)
            if stage == 16:
                assert len(model["elements"]) == len(source["elements"]), f"{style}/{composition} final stage lost BBModel pieces"
                assert expected_colors <= colors, f"{style}/{composition} did not render every present denomination"

model_refs = {part["apply"]["model"] for part in state["multipart"]}
for style in SHAPES:
    for composition in COMPOSITIONS:
        for stage in range(17):
            assert f"pastoral_home:block/coin_pile/{style}_{composition}_stage_{stage}" in model_refs
assert (ASSETS / "models/block/coin_pile_empty.json").is_file() is False

for kind in ("gold", "silver", "copper"):
    item_model = read(ASSETS / f"models/item/coin_{kind}.json")
    pouch = read(ASSETS / f"models/block/coin_pouch_{kind}.json")
    item = read(ASSETS / f"items/coin_{kind}.json")
    assert item_model["parent"] == "minecraft:item/generated"
    assert item_model["textures"]["layer0"] == f"pastoral_home:item/coin_{kind}"
    assert item["model"] == {"type": "minecraft:model", "model": f"pastoral_home:item/coin_{kind}"}
    assert len(pouch["elements"]) == 12
    assert not (ASSETS / f"items/coin_{kind}_render.json").exists()
    with Image.open(ASSETS / f"textures/item/coin_{kind}.png") as image:
        assert image.size == (16, 16) and image.mode == "RGBA"

manifest = read(WORK / "currency_asset_manifest.json")
assert len([entry for entry in manifest if "layout" in entry]) == 8
icon_report = read(WORK / "coin_icons.json")
for kind in ("coin_gold", "coin_silver", "coin_copper"):
    item = next(value for value in icon_report["coins"] if value["item"] == kind)
    assert item["pure_2d_item"] and item["size"] == [16, 16]

lang = read(ROOT / "src/generated/resources/assets/pastoral_home/lang/zh_cn.json")
for key in ("item.pastoral_home.coin_gold", "item.pastoral_home.coin_silver",
            "item.pastoral_home.coin_copper", "block.pastoral_home.coin_pile",
            "container.pastoral_home.coin_pile"):
    assert lang.get(key), f"missing localization: {key}"
print("Currency assets verified: 2D icons, persistent A/B geometry, stable mixed palettes, and 238 BBModel stages.")
