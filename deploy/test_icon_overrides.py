import json
import math
import tempfile
import unittest
from pathlib import Path

from item_icon_proxy import GUI_ICON_TARGET_PX, VANILLA_BLOCK_GUI, geometry_bounds
from icon_overrides import (
    apply_screen_offset, apply_yaw_rotation, effective_params,
    load_overrides, save_overrides, screen_offset_to_geometry,
)


class IconOverridesTests(unittest.TestCase):
    def test_roundtrip_and_noop_pruning(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = {"a": {"offset_x": 1.5, "note": "too small"},
                    "b": {"offset_x": 0, "target_px": 0}}
            save_overrides(root, data)
            loaded = load_overrides(root)
            self.assertEqual(loaded["a"], {"offset_x": 1.5, "note": "too small"})
            self.assertNotIn("b", loaded)  # all values are no-ops

    def test_shade_field_roundtrip_and_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            save_overrides(root, {"a": {"shade": "flat"}, "b": {"shade": "game"}})
            loaded = load_overrides(root)
            self.assertEqual(loaded["a"]["shade"], "flat")
            self.assertEqual(loaded["b"]["shade"], "game")
            (root / "item_icon_overrides.json").write_text(
                json.dumps({"version": 1, "items": {"a": {"shade": "dark"}}}), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_overrides(root)

    def test_effective_params_shade_default(self):
        auto = {"target_px": 15.7, "floor_anchor": False}
        self.assertEqual(effective_params("a", auto, {})["shade"], "game")
        self.assertEqual(effective_params("a", auto, {"a": {"shade": "flat"}})["shade"], "flat")

    def test_effective_params_merge(self):
        auto = {"target_px": 15.7, "floor_anchor": True}
        out = effective_params("x", auto, {"x": {"target_px": 12.0, "anchor": "center", "yaw": 15}})
        self.assertEqual(out["target_px"], 12.0)
        self.assertFalse(out["floor_anchor"])
        self.assertEqual(out["yaw"], 15.0)
        self.assertTrue(out["overridden"])
        plain = effective_params("y", auto, {})
        self.assertEqual(plain["target_px"], 15.7)
        self.assertTrue(plain["floor_anchor"])
        self.assertFalse(plain["overridden"])

    def test_screen_offset_inverse_projection(self):
        # A geometry translation must land on the requested screen offset after
        # the vanilla GUI camera projects it. The yaw-225 camera puts screen x at
        # -(x+z)*cos45, so dx=dz yields sx=-2*cos45*dx; sy=-cos30*dy.
        scale = VANILLA_BLOCK_GUI["scale"][0]
        for ox, oy in [(2.0, 0.0), (0.0, 3.0), (-1.5, 2.5)]:
            dx, dy, dz = screen_offset_to_geometry(ox, oy, scale)
            sx = -math.cos(math.radians(45)) * (dx + dz) * scale
            sy = -(math.cos(math.radians(30)) * dy) * scale
            self.assertAlmostEqual(sx, ox, places=5)
            self.assertAlmostEqual(sy, oy, places=5)

    def test_apply_screen_offset_moves_visible_silhouette(self):
        # A cube is symmetric so its visible silhouette tracks the geometry exactly.
        from PIL import Image
        import numpy as np
        model = {
            "textures": {"t": "test"},
            "elements": [{"from": [0, 0, 0], "to": [16, 16, 16],
                          "faces": {f: {"uv": [0, 0, 16, 16], "texture": "#t"}
                                    for f in ("north", "east", "up")}}],
            "display": {"gui": VANILLA_BLOCK_GUI},
        }
        tex = Image.new("RGBA", (16, 16), (255, 0, 0, 255))
        def resolver(ref):
            return None  # no texture -> flat 160 grey face; enough for bounds
        from item_icon_preview import visible_projected_measurements
        scale = VANILLA_BLOCK_GUI["scale"][0]
        before = visible_projected_measurements(model, resolver, pixels_per_unit=16)
        moved = apply_screen_offset(model, resolver, 2.0, 1.5, scale)
        after = visible_projected_measurements(moved, resolver, pixels_per_unit=16)
        # Bounds are in pre-scale projected units; expected delta = pixels/scale.
        self.assertAlmostEqual(((after["bounds"][0] + after["bounds"][2]) -
                                (before["bounds"][0] + before["bounds"][2])) / 2 * scale, 2.0, delta=0.15)
        self.assertAlmostEqual(((after["bounds"][1] + after["bounds"][3]) -
                                (before["bounds"][1] + before["bounds"][3])) / 2 * scale, 1.5, delta=0.15)

    def test_apply_yaw_rotates_geometry_without_mutating_source(self):
        # An axis-aligned cube rotated 15 deg must have a different corner, and a
        # larger AABB (rotated cubes do not keep their axis-aligned size). The
        # important contract is that the source model is not mutated.
        model = {"elements": [{"from": [0, 0, 0], "to": [16, 16, 16]}]}
        rotated = apply_yaw_rotation(model, 15.0)
        a, b = geometry_bounds(model), geometry_bounds(rotated)
        self.assertIsNotNone(b)
        self.assertNotEqual(a, b)
        self.assertGreater(b[3] - b[0], a[3] - a[0])
        self.assertEqual(model["elements"][0]["from"], [0, 0, 0])  # no mutation
        self.assertEqual(apply_yaw_rotation(model, 0.0)["elements"][0]["from"], [0, 0, 0])


if __name__ == "__main__":
    unittest.main()
