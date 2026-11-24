import unittest

from split_model_cells import split_element


class SplitModelCellsTests(unittest.TestCase):
    def test_large_front_face_is_split_and_uvs_are_cropped(self):
        faces = {name: {"uv": [0, 0, 16, 16], "texture": "#wood"}
                 for name in ("north", "south", "east", "west", "up", "down")}
        element = {"from": [-8, 2, 4], "to": [24, 10, 6], "faces": faces}
        parts = split_element(element)
        self.assertEqual([p[0] for p in parts], [(-1, 0, 0), (0, 0, 0), (1, 0, 0)])
        self.assertEqual([p[1]["faces"]["north"]["uv"] for p in parts],
                         [[12.0, 0.0, 16.0, 16.0], [4.0, 0.0, 12.0, 16.0], [0.0, 0.0, 4.0, 16.0]])
        self.assertIn("west", parts[0][1]["faces"])
        self.assertNotIn("east", parts[0][1]["faces"])
        self.assertNotIn("west", parts[1][1]["faces"])
        self.assertNotIn("east", parts[1][1]["faces"])
        self.assertIn("east", parts[2][1]["faces"])
        for _cell, fragment, _warnings in parts:
            self.assertTrue(all(0 <= value <= 16 for value in fragment["from"]))
            self.assertTrue(all(0 <= value <= 16 for value in fragment["to"]))

    def test_rotated_element_splits_on_its_rotation_axis_without_dropping_transform(self):
        faces = {name: {"uv": [0, 0, 16, 16], "texture": "#roof"}
                 for name in ("north", "south", "east", "west", "up", "down")}
        element = {"from": [-8, 20, 4], "to": [24, 24, 8], "faces": faces,
                   "rotation": {"origin": [8, 22, 6], "axis": "x", "angle": 30}}
        parts = split_element(element)
        self.assertEqual(len(parts), 3)
        self.assertTrue(all(fragment["rotation"]["axis"] == "x" for _, fragment, _ in parts))
        self.assertTrue(all("west" not in fragment["faces"] for _, fragment, _ in parts[1:]))
        self.assertTrue(all("east" not in fragment["faces"] for _, fragment, _ in parts[:-1]))

    def test_rotated_sheet_crossing_a_row_boundary_is_tessellated_into_both_owner_cells(self):
        faces = {name: {"uv": [0, 0, 16, 16], "texture": "#roof"}
                 for name in ("north", "south", "east", "west", "up", "down")}
        element = {"from": [-16, 44, -3], "to": [32, 46, 8], "faces": faces,
                   "rotation": {"origin": [8, 46, 2.5], "axis": "x", "angle": -30}}
        parts = split_element(element)
        self.assertLess(len(parts), 150)
        self.assertEqual({cell[0] for cell, _fragment, _warnings in parts}, {-1, 0, 1})
        self.assertEqual({cell[2] for cell, _fragment, _warnings in parts}, {-1, 0})
        self.assertTrue(all(max((issue["overhang_px"] for issue in warnings), default=0.0) <= 1.0
                            for _cell, _fragment, warnings in parts))


if __name__ == "__main__":
    unittest.main()
