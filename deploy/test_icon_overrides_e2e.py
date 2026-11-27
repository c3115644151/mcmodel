"""End-to-end checks that icon overrides flow through the generator unchanged."""
import json
import tempfile
import unittest
from pathlib import Path

from icon_overrides import effective_params, load_overrides, save_overrides
from item_icon_proxy import VANILLA_BLOCK_GUI


class IconOverrideE2ETests(unittest.TestCase):
    def test_offset_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            save_overrides(root, {"mug": {"offset_x": 1.2, "offset_y": -0.8,
                                          "target_px": 9.5, "anchor": "floor", "yaw": 10}})
            loaded = load_overrides(root)
            params = effective_params("mug", {"target_px": 15.7, "floor_anchor": False}, loaded)
            self.assertEqual(params["target_px"], 9.5)
            self.assertTrue(params["floor_anchor"])
            self.assertEqual(params["offset_x"], 1.2)
            self.assertEqual(params["offset_y"], -0.8)
            self.assertEqual(params["yaw"], 10.0)
            self.assertTrue(params["overridden"])

    def test_manifest_records_effective_params(self):
        # The generator writes offset/yaw/source into the manifest so the validator
        # can check the tuned target instead of assuming slot centre. Verify the
        # project manifest has these keys on every entry.
        root = Path(__file__).resolve().parents[2]
        manifest = json.loads((root / "item_icons_manifest.json").read_text(encoding="utf-8"))
        fresh = [e for e in manifest.get("items", {}).values() if "gui_target_px" in e]
        self.assertTrue(fresh, "no generator-owned manifest entries")
        for entry in fresh:
            for key in ("offset_x", "offset_y", "yaw", "source_override", "overridden"):
                self.assertIn(key, entry)

    def test_generator_preserves_vanilla_display(self):
        # Overrides translate geometry, never display.gui, so the shared camera gate
        # stays valid even on tuned items.
        root = Path(__file__).resolve().parents[2]
        assets = root / "src/main/resources/assets/pastoral_home"
        for path in sorted((assets / "models/item_icons").glob("*/variant_*.json")):
            model = json.loads(path.read_text(encoding="utf-8"))
            gui = model.get("display", {}).get("gui", {})
            self.assertEqual(gui.get("rotation"), VANILLA_BLOCK_GUI["rotation"], str(path))
            self.assertEqual(gui.get("translation"), VANILLA_BLOCK_GUI["translation"], str(path))


if __name__ == "__main__":
    unittest.main()
