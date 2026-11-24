import tempfile
import unittest
from pathlib import Path

from preview_item_icons import creative_tab_item_ids
from item_icon_preview import FACE_VERTICES


class CreativeTabPreviewFilterTests(unittest.TestCase):
    def test_preview_filter_uses_only_explicit_creative_tab_entries(self):
        with tempfile.TemporaryDirectory() as temp:
            registry = Path(temp) / "src/main/java/com/pastoralhome/registry/ModCreativeTabs.java"
            registry.parent.mkdir(parents=True)
            registry.write_text(
                "output.accept(ModItems.WEATHER_VANE.get());\n"
                "output.accept(ModItems.WHEELBARROW.get());\n",
                encoding="utf-8",
            )
            self.assertEqual(creative_tab_item_ids(Path(temp)), {"weather_vane", "wheelbarrow"})

    def test_underside_projects_from_low_y_plane(self):
        self.assertTrue(all(vertex[1] == 0 for vertex in FACE_VERTICES["down"]))
        self.assertTrue(all(vertex[1] == 1 for vertex in FACE_VERTICES["up"]))


if __name__ == "__main__":
    unittest.main()
