import json
import tempfile
import unittest
from pathlib import Path

from item_icon_proxy import (
    VANILLA_BLOCK_GUI,
    collect_model_ids,
    geometry_bounds,
    normalize_to_block,
    replace_gui_case_model_ids,
    rotate_relative_to_vanilla_gui,
    unwrap_generated_gui_select,
    wrap_gui_only,
)


class ItemIconProxyTests(unittest.TestCase):
    def test_one_block_model_keeps_authored_scale_and_uses_vanilla_gui(self):
        model = {"elements": [{"from": [0, 0, 0], "to": [16, 16, 16]}]}
        result = normalize_to_block(model)
        self.assertEqual(result["scale"], 1.0)
        self.assertEqual(result["final_bounds"], (0.0, 0.0, 0.0, 16.0, 16.0, 16.0))
        self.assertEqual(result["model"]["display"]["gui"], VANILLA_BLOCK_GUI)

    def test_authored_gui_display_is_discarded_for_the_vanilla_camera(self):
        """A bbmodel's own GUI camera must never reach the generated proxy.

        Authored values in the sources used a 45 degree yaw (the model's back face)
        and translations up to a third of a slot, so the normalizer overrides them.
        """
        model = {
            "elements": [{"from": [0, 0, 0], "to": [16, 16, 16]}],
            "display": {"gui": {"rotation": [30, -135, 0], "translation": [0, 2.5, 0],
                                "scale": [0.3, 0.3, 0.3]}},
        }
        result = normalize_to_block(model)
        self.assertEqual(result["model"]["display"]["gui"], VANILLA_BLOCK_GUI)
        self.assertEqual(result["gui_scale"], [0.625, 0.625, 0.625])

    def test_small_objects_grow_to_block_size_and_rest_on_floor(self):
        model = {"elements": [{"from": [30, 10, 5], "to": [34, 14, 9]}]}
        result = normalize_to_block(model)
        self.assertEqual(result["scale"], 4.0)
        self.assertEqual(result["final_bounds"], (0.0, 0.0, 0.0, 16.0, 16.0, 16.0))

    def test_multiblock_geometry_shrinks_into_one_block(self):
        model = {"elements": [{"from": [-16, 0, 0], "to": [16, 12, 8]}]}
        result = normalize_to_block(model)
        self.assertAlmostEqual(result["scale"], 0.5)
        self.assertEqual(result["final_bounds"], (0.0, 0.0, 6.0, 16.0, 6.0, 10.0))

    def test_rotated_element_origins_follow_proxy_transform(self):
        model = {"elements": [{
            "from": [0, 0, 0], "to": [32, 8, 8],
            "rotation": {"origin": [16, 4, 4], "axis": "z", "angle": 22.5},
        }]}
        result = normalize_to_block(model)
        proxy_element = result["model"]["elements"][0]
        self.assertAlmostEqual(proxy_element["rotation"]["origin"][0], 8.0)
        self.assertAlmostEqual(proxy_element["rotation"]["origin"][2], 8.0)
        self.assertGreaterEqual(proxy_element["rotation"]["origin"][1], 0.0)
        bounds = geometry_bounds(result["model"])
        self.assertTrue(all(-1e-5 <= v <= 16.0 + 1e-5 for v in bounds))

    def test_generated_display_context_wrapper_is_idempotently_unwrapped(self):
        original = {"type": "minecraft:model", "model": "pastoral_home:block/teacup"}
        gui = {"type": "minecraft:model", "model": "pastoral_home:item_icons/teacup/variant_0"}
        wrapped = wrap_gui_only(gui, original)
        self.assertEqual(unwrap_generated_gui_select(wrapped, "pastoral_home"), original)
        self.assertEqual(wrapped["cases"][0]["when"], "gui")

    def test_normalizer_replaces_nested_gui_models_but_preserves_world_fallback(self):
        source = {
            "type": "minecraft:select", "property": "minecraft:display_context",
            "cases": [{"when": "gui", "model": {
                "type": "minecraft:model", "model": "pastoral_home:block/board"}}],
            "fallback": {"type": "minecraft:model", "model": "pastoral_home:block/board"},
        }
        updated = replace_gui_case_model_ids(source, {
            "pastoral_home:block/board": "pastoral_home:item_icons/board/variant_0"})
        self.assertEqual(collect_model_ids(updated["cases"][0]["model"]),
                         ["pastoral_home:item_icons/board/variant_0"])
        self.assertEqual(collect_model_ids(updated["fallback"]), ["pastoral_home:block/board"])
        self.assertEqual(unwrap_generated_gui_select(updated, "pastoral_home"), source["fallback"])


if __name__ == "__main__":
    unittest.main()
