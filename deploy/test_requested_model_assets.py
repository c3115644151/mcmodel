#!/usr/bin/env python3
"""Regression checks for the randomized wall-painting and potted-spruce imports."""
from __future__ import annotations

import base64
import json
import math
import sys
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "src/main/resources/assets/pastoral_home"
SOURCES = ROOT / "tools/deploy/model_sources"
BUILD = ROOT / "build/requested_models"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
from item_icon_proxy import geometry_bounds, unwrap_generated_gui_select
from item_icon_preview import visible_projected_measurements
from normalize_item_icons import resolve_texture
import prepare_wall_painting_variants as paintings


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def close(a, b, tolerance=1e-6):
    return abs(float(a) - float(b)) <= tolerance


class RequestedModelAssetTests(unittest.TestCase):
    def test_all_four_paintings_have_front_back_and_facing_coverage(self):
        state = read(ASSETS / "blockstates/wall_painting.json")
        multipart = state["multipart"]
        self.assertEqual(len(multipart), 4 * 2 * 4)
        art_models = {
            0: "wall_painting",
            1: "wall_painting_overworld",
            2: "wall_painting_nether",
            3: "wall_painting_end",
        }
        for art, model_name in art_models.items():
            front = read(ASSETS / f"models/block/{model_name}.json")
            back = read(ASSETS / f"models/block/{model_name}_back.json")
            self.assertEqual(len(front["elements"]), 2, model_name)
            self.assertEqual(len(back["elements"]), 2, model_name)
            for front_element, back_element in zip(front["elements"], back["elements"]):
                self.assertEqual(front_element["from"], back_element["from"])
                self.assertEqual(front_element["to"], back_element["to"])
                self.assertEqual(back_element["faces"]["north"], front_element["faces"]["south"])
                self.assertEqual(back_element["faces"]["south"], front_element["faces"]["north"])
            for facing, angle in (("north", 0), ("east", 90), ("south", 180), ("west", 270)):
                for flipped in (False, True):
                    entry = next(part for part in multipart if part["when"] == {
                        "artwork": str(art), "facing": facing, "flipped": str(flipped).lower(),
                    })
                    variant = entry["apply"]
                    expected_suffix = "_back" if flipped else ""
                    self.assertEqual(variant["model"], f"pastoral_home:block/{model_name}{expected_suffix}")
                    self.assertEqual(variant.get("y", 0), angle)

        for slug, source_name in (
            ("overworld", "painting_overworld.bbmodel"),
            ("nether", "painting_nether.bbmodel"),
            ("end", "painting_end.bbmodel"),
        ):
            source_path = SOURCES / "wall_painting_variants" / source_name
            source = read(source_path)
            raw = read(BUILD / "wall_paintings" / f"{slug}.json")
            expected = paintings.fit_existing_anchor(raw, slug)
            actual = read(ASSETS / f"models/block/wall_painting_{slug}.json")
            # normalize_block_model_particles.py runs after every prepare stage and
            # swaps the source silhouette tile for a dedicated slice of this painting,
            # so the expected fingerprint has to account for it separately.
            self.assertEqual(actual["textures"].pop("particle", None),
                             f"pastoral_home:block/wall_painting_{slug}_particle", slug)
            expected["textures"].pop("particle", None)
            self.assertEqual(actual, expected, slug)
            self.assertTrue(
                (ASSETS / f"textures/block/wall_painting_{slug}_particle.png").is_file(),
                f"{slug}: particle tile must ship as a real texture")
            texture = ASSETS / f"textures/block/wall_painting_{slug}.png"
            self.assertTrue(texture.is_file())
            with Image.open(texture) as image:
                self.assertGreater(image.width, 0)
                self.assertGreater(image.height, 0)
            embedded = source["textures"][0]["source"].split(",", 1)[-1]
            self.assertEqual(texture.read_bytes(), base64.b64decode(embedded), slug)

    def test_wall_painting_java_state_randomizes_from_four_values(self):
        source = (ROOT / "src/main/java/com/pastoralhome/block/WallPaintingBlock.java").read_text(encoding="utf-8")
        self.assertIn('IntegerProperty.create("artwork", 0, 3)', source)
        self.assertIn("chooseArtwork(level.getRandom())", source)
        self.assertIn("builder.add(FLIPPED, ARTWORK)", source)
        self.assertIn("partState.setValue(FLIPPED, flipped)", source)
        item = read(ASSETS / "items/wall_painting.json")["model"]
        self.assertEqual(item["cases"][0]["model"]["model"],
                         "pastoral_home:item_icons/wall_painting/variant_0")
        self.assertEqual(item["fallback"]["model"], "pastoral_home:block/wall_painting")
        unwrapped = unwrap_generated_gui_select(item, "pastoral_home")
        self.assertEqual(unwrapped["cases"][0]["model"]["model"],
                         "pastoral_home:block/wall_painting_overworld")
        self.assertEqual(unwrapped["fallback"], item["fallback"])

    def test_spruce_geometry_is_faithfully_partitioned_across_three_cells(self):
        raw = read(BUILD / "spruce_planter" / "spruce_planter_raw.json")
        placed = read(BUILD / "spruce_planter" / "spruce_planter_placed_world.json")
        manifest = read(BUILD / "spruce_planter" / "spruce_planter_split_manifest.json")
        self.assertEqual(len(raw["elements"]), 19)
        self.assertEqual(len(placed["elements"]), 19)
        self.assertEqual(sorted(int(i) for values in manifest.values() for i in values), list(range(19)))
        self.assertEqual(set(manifest), {"0", "1", "2"})
        self.assertTrue(all(manifest[str(layer)] for layer in range(3)))

        for layer in range(3):
            model = read(ASSETS / f"models/block/spruce_planter_l{layer}.json")
            self.assertEqual(len(model["elements"]), len(manifest[str(layer)]))
            for local, source_index in zip(model["elements"], manifest[str(layer)]):
                world = dict(local)
                world["from"] = list(local["from"])
                world["to"] = list(local["to"])
                world["from"][1] += 16 * layer
                world["to"][1] += 16 * layer
                if "rotation" in local:
                    world["rotation"] = dict(local["rotation"])
                    world["rotation"]["origin"] = list(local["rotation"]["origin"])
                    world["rotation"]["origin"][1] += 16 * layer
                expected = placed["elements"][source_index]
                for point in ("from", "to"):
                    for axis in range(3):
                        self.assertTrue(close(world[point][axis], expected[point][axis]),
                                        (layer, source_index, point, axis, world[point], expected[point]))
                self.assertEqual(world["faces"], expected["faces"])
                self.assertEqual(bool(world.get("rotation")), bool(expected.get("rotation")))
                if world.get("rotation"):
                    self.assertEqual(world["rotation"]["axis"], expected["rotation"]["axis"])
                    self.assertTrue(close(world["rotation"]["angle"], expected["rotation"]["angle"]))
                    for axis in range(3):
                        self.assertTrue(close(world["rotation"]["origin"][axis],
                                              expected["rotation"]["origin"][axis]))
                coords = [value for point in ("from", "to") for value in local[point]]
                self.assertTrue(all(-16.0001 <= value <= 32.0001 for value in coords), (layer, coords))

        item_model = read(ASSETS / "models/block/spruce_planter_item.json")
        self.assertEqual(item_model["elements"], raw["elements"])
        item_definition = read(ASSETS / "items/spruce_planter.json")["model"]
        gui_tree = item_definition["cases"][0]["model"]["model"]
        self.assertEqual(gui_tree, "pastoral_home:item_icons/spruce_planter/variant_0")
        proxy = read(ASSETS / "models/item_icons/spruce_planter/variant_0.json")
        bounds = geometry_bounds(proxy)
        self.assertIsNotNone(bounds)
        self.assertTrue(all(-1e-4 <= value <= 16.0001 for value in bounds), bounds)
        visible = visible_projected_measurements(proxy, lambda ref: resolve_texture(ROOT, ref), pixels_per_unit=8)
        self.assertIsNotNone(visible)
        gui_scale = proxy["display"]["gui"]["scale"]
        visible_width = (visible["bounds"][2] - visible["bounds"][0]) * gui_scale[0]
        visible_height = (visible["bounds"][3] - visible["bounds"][1]) * gui_scale[1]
        # The tallest AABB side fills one block, so this slender tree is thin in
        # projection by geometry, not by transform: a 7.75x16 world span reads as
        # ~4.8x9.1 px under the vanilla 30/225/0.625 camera, the same order as a
        # vanilla block item (a full cube lands around 10x11 px).
        self.assertGreaterEqual(visible_width, 4.0, f"spruce planter GUI icon too small: {visible_width:.2f}px")
        self.assertGreaterEqual(visible_height, 8.5, f"spruce planter GUI icon too small: {visible_height:.2f}px")

        blockstates = read(ASSETS / "blockstates/spruce_planter.json")["multipart"]
        self.assertEqual(len(blockstates), 12)
        self.assertEqual({entry["apply"]["model"] for entry in blockstates}, {
            f"pastoral_home:block/spruce_planter_l{layer}" for layer in range(3)
        })
        self.assertTrue((ASSETS / "textures/block/spruce_planter.png").is_file())

        loot = read(ROOT / "src/generated/resources/data/pastoral_home/loot_table/blocks/spruce_planter.json")
        self.assertEqual(loot["pools"][0]["conditions"][0]["properties"], {
            "column": "0", "layer": "0", "row": "0",
        })
        axe_tag = read(ROOT / "src/generated/resources/data/minecraft/tags/block/mineable/axe.json")
        self.assertIn("pastoral_home:spruce_planter", axe_tag["values"])
        for locale, expected in (("en_us", "Small Potted Spruce"), ("zh_cn", "小云杉盆栽")):
            language = read(ROOT / f"src/generated/resources/assets/pastoral_home/lang/{locale}.json")
            self.assertEqual(language["block.pastoral_home.spruce_planter"], expected)
        blocks = (ROOT / "src/main/java/com/pastoralhome/registry/ModBlocks.java").read_text(encoding="utf-8")
        items = (ROOT / "src/main/java/com/pastoralhome/registry/ModItems.java").read_text(encoding="utf-8")
        creative = (ROOT / "src/main/java/com/pastoralhome/registry/ModCreativeTabs.java").read_text(encoding="utf-8")
        self.assertIn('registerBlock("spruce_planter"', blocks)
        self.assertIn('registerSimpleBlockItem("spruce_planter"', items)
        self.assertIn("output.accept(ModItems.SPRUCE_PLANTER.get())", creative)


if __name__ == "__main__":
    unittest.main(verbosity=2)
