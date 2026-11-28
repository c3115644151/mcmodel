import copy
import json
import math
import tempfile
import unittest
from pathlib import Path

from item_icon_proxy import (GUI_ICON_TARGET_PX, VANILLA_BLOCK_GUI, fit_gui_projection,
                             geometry_bounds, screen_jacobian)
from icon_overrides import (
    apply_screen_offset, effective_params, yaw_gui_rotation,
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
        self.assertEqual(effective_params("a", auto, {})["shade_strength"], 1.0)

    def test_shade_strength_is_first_class_and_legacy_shade_still_reads(self):
        auto = {"target_px": 15.7, "floor_anchor": False}
        # 连续强度是当前写法；旧档位映射成 0/1，显式强度优先。
        self.assertEqual(effective_params("a", auto, {"a": {"shade_strength": 0.45}})["shade_strength"], 0.45)
        self.assertEqual(effective_params("a", auto, {"a": {"shade": "flat"}})["shade_strength"], 0.0)
        self.assertEqual(effective_params("a", auto, {"a": {"shade": "flat",
                                                             "shade_strength": 0.6}})["shade_strength"], 0.6)
        self.assertEqual(effective_params("a", auto, {"a": {"shade_strength": 0.0}})["shade"], "flat")

    def test_shade_strength_range_and_noop_pruning(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            # 0 是有效值（等于关阴影），不能被当成"没改"丢掉；默认 1.0 与旧档 game 要丢。
            save_overrides(root, {"a": {"shade_strength": 0.0},
                                  "b": {"shade_strength": 1.0, "target_px": 9},
                                  "c": {"shade": "game"}})
            loaded = load_overrides(root)
            self.assertEqual(loaded["a"], {"shade_strength": 0.0})
            self.assertEqual(loaded["b"], {"target_px": 9})
            # 旧档位原样留存（不做迁移改写），新版界面不再写它。
            self.assertEqual(loaded["c"], {"shade": "game"})
            (root / "item_icon_overrides.json").write_text(
                json.dumps({"version": 1, "items": {"x": {"shade_strength": 2.0}}}), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_overrides(root)

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
        # 平移必须精确落在请求的屏幕偏移上。这里用相机自身的雅可比验算，而不是
        # 手推的 sx=-(x+z)cos45：那个公式在 yaw 225 只是特例，而且忽略了俯仰把
        # x/z 也混进屏幕 y 的耦合（换 yaw 后旧公式就不成立）。
        scale = VANILLA_BLOCK_GUI["scale"][0]
        rotation = tuple(VANILLA_BLOCK_GUI["rotation"])
        jacobian = screen_jacobian(rotation)
        for ox, oy in [(2.0, 0.0), (0.0, 3.0), (-1.5, 2.5)]:
            translation = screen_offset_to_geometry(ox, oy, scale, rotation)
            screen = [sum(jacobian[axis][i] * translation[axis] for axis in range(3))
                      for i in (0, 1)]
            self.assertAlmostEqual(screen[0] * scale, ox, places=5)
            self.assertAlmostEqual(screen[1] * scale, oy, places=5)

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

    def test_yaw_is_a_camera_rotation_not_a_geometry_rotation(self):
        # 额外朝向只改 display.gui.rotation。几何一旦被旋转，轴对齐 box 就不再是它自己：
        # 转角点会让 model 被压扁/翻倒/解体——这是 2026-11-28 报上来的现象。
        self.assertEqual(yaw_gui_rotation(0.0, VANILLA_BLOCK_GUI["rotation"]), [30.0, 225.0, 0.0])
        self.assertEqual(yaw_gui_rotation(45.0, VANILLA_BLOCK_GUI["rotation"]), [30.0, 270.0, 0.0])
        self.assertEqual(yaw_gui_rotation(-45.0, VANILLA_BLOCK_GUI["rotation"]), [30.0, 180.0, 0.0])
        self.assertEqual(yaw_gui_rotation(200.0, VANILLA_BLOCK_GUI["rotation"]), [30.0, 65.0, 0.0])
        model = {
            "textures": {"t": "pastoral_home:block/cube"},
            "elements": [{"from": [13, 2, 13], "to": [16, 14, 16],
                          "faces": {name: {"uv": [0, 0, 16, 16], "texture": "#t"}
                                    for name in ("north", "south", "east", "west", "up", "down")}}],
        }
        original = [copy.deepcopy(element) for element in model["elements"]]
        radius = tuple(VANILLA_BLOCK_GUI["rotation"])
        for yaw in (15.0, 45.0, 130.0):
            fitted = fit_gui_projection(model, lambda _ref: None, target_px=12.0,
                                        gui_rotation=yaw_gui_rotation(yaw, radius))
            self.assertIsNotNone(fitted)
            rotation = fitted["model"]["display"]["gui"]["rotation"]
            self.assertEqual(rotation, yaw_gui_rotation(yaw, radius))
            element = fitted["model"]["elements"][0]
            # 轴对齐仍然成立：from<=to 没被打乱；fit 只等比缩放，长宽比必须保持 3:12:3。
            extents = [element["to"][axis] - element["from"][axis] for axis in range(3)]
            for axis in range(3):
                self.assertLessEqual(element["from"][axis], element["to"][axis],
                                     f"yaw {yaw} 把 box 转坏了: {element}")
            self.assertAlmostEqual(extents[0], extents[2], places=6)
            self.assertAlmostEqual(extents[1] / extents[0], 4.0, places=6)
            self.assertEqual([copy.deepcopy(e) for e in model["elements"]], original)
            # 换相机后仍居中，且长边落在目标尺寸上。
            bounds = fitted["fit_projected_bounds"]
            scale = VANILLA_BLOCK_GUI["scale"][0]
            self.assertLess(abs((bounds[0] + bounds[2]) * 0.5 * scale), 0.25)
            self.assertLess(abs((bounds[1] + bounds[3]) * 0.5 * scale), 0.25)
            self.assertAlmostEqual(max(fitted["fit_projected_size"]), 12.0, delta=0.6)


if __name__ == "__main__":
    unittest.main()
