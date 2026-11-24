import unittest

from gui_measure import measure


class GuiMeasureTranslationTests(unittest.TestCase):
    def test_positive_translation_y_moves_icon_up_and_recommended_value_centers(self):
        model = {"elements": [{"from": [0, 0, 0], "to": [16, 16, 16]}]}
        baseline = measure(model)
        moved_up = measure(model, ty=1.0)
        self.assertAlmostEqual(moved_up["center"][1], baseline["center"][1] - 1.0)
        centered = measure(model, ty=baseline["recommended_ty"])
        self.assertAlmostEqual(centered["center"][1], 8.0, places=3)


if __name__ == "__main__":
    unittest.main()
