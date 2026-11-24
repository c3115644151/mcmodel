"""Regression tests for collision parts that must remain visual-only by default."""
import json
import tempfile
import unittest
from pathlib import Path

from generate import compress_adaptive, merge_exact_union_boxes, segment_rotated
from parse_model import cube_aabb, filter_collision_cubes
from run import clip_cubes_to_bounds, deploy_collision, select_collision_elements, single_collision_envelope


def cube(name, size=(4, 4, 4), faces=6, rotation=None):
    texture = {"texture": "#0", "uv": [0, 0, 1, 1]}
    directions = ("north", "east", "south", "west", "up", "down")
    return {
        "name": name,
        "index": 0,
        "from": [0, 0, 0],
        "to": list(size),
        "rotation": rotation,
        "faces": {direction: texture for direction in directions[:faces]},
    }


class CollisionFilterTests(unittest.TestCase):
    def test_a_thin_tilted_plate_stays_one_box_instead_of_a_staircase(self):
        plate = cube("horn_petal", (17, 6, 0), rotation={
            "angles": [25.0, -25.0, 11.0], "origin": [0, 11.64, -0.34],
        })
        plate["to"] = [17, 6, 0]
        boxes = segment_rotated(plate, seg_count=6, res=8)
        self.assertEqual(len(boxes), 1)
        self.assertEqual(boxes[0], cube_aabb(plate))

    def test_a_thick_tilted_bar_is_still_segmented(self):
        bar = cube("ladder_rail", (2, 32, 2), rotation={
            "angles": [10, 0, 0], "origin": [1, 0, 1],
        })
        bar["to"] = [2, 32, 2]
        self.assertGreater(len(segment_rotated(bar, seg_count=6, res=8)), 1)

    def test_exact_union_merge_deduplicates_identical_state_boxes_without_dropping_them(self):
        box = (1, 2, 3, 4, 5, 6)
        self.assertEqual(merge_exact_union_boxes([box, box, box]), [box])

    def test_clipping_rotated_cubes_discards_stale_corner_cache(self):
        rotated = cube("ladder_rail", (2, 32, 2), rotation={
            "angles": [10, 0, 0], "origin": [1, 0, 1],
        })
        rotated["corners"] = [[0, -0.2, 0], [2, 32.2, 3]]
        clipped = clip_cubes_to_bounds([rotated], {1: (0.0, 16.0)})
        self.assertEqual(len(clipped), 1)
        self.assertNotIn("rotation", clipped[0])
        self.assertNotIn("corners", clipped[0])
        self.assertEqual(cube_aabb(clipped[0])[1], 0.0)
        self.assertEqual(cube_aabb(clipped[0])[4], 16.0)

    def test_tall_single_block_collision_is_not_split_into_fake_cells(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "tall_prop.json"
            faces = {name: {"uv": [0, 0, 16, 16], "texture": "#all"}
                     for name in ("north", "east", "south", "west", "up", "down")}
            path.write_text(json.dumps({
                "textures": {"all": "minecraft:block/oak_planks"},
                "elements": [{"from": [6, 0, 6], "to": [10, 32, 10], "faces": faces}],
            }), encoding="utf-8")
            result = deploy_collision(str(path), res=2, single_block=True)
            self.assertIsNone(result["grid"])
            self.assertEqual(result["cells"], None)
            self.assertEqual(result["boxes"], [(6, 0, 6, 10, 32, 10)])

    def test_component_group_envelope_reduces_rotated_part_outline_boxes(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "tripod.json"
            faces = {name: {"uv": [0, 0, 16, 16], "texture": "#all"}
                     for name in ("north", "east", "south", "west", "up", "down")}
            path.write_text(json.dumps({
                "textures": {"all": "minecraft:block/oak_planks"},
                "elements": [
                    {"from": [1, 0, 1], "to": [3, 16, 3], "faces": faces},
                    {"from": [13, 0, 13], "to": [15, 16, 15], "faces": faces},
                ],
            }), encoding="utf-8")
            result = deploy_collision(str(path), res=2, single_block=True,
                                      collision_groups=[[0, 1]])
            self.assertEqual(result["boxes"], [(1, 0, 1, 15, 16, 15)])

    def test_zero_thickness_plane_is_visual_only_unless_opted_in(self):
        plane = cube("flame_plane", (2, 4, 0))
        kept, skipped = filter_collision_cubes([plane])
        self.assertEqual(kept, [])
        self.assertIn("zero-thickness plane", skipped[0][1])
        kept, skipped = filter_collision_cubes([plane], include_thin=True)
        self.assertEqual(kept, [plane])
        self.assertEqual(skipped, [])

    def test_positive_thickness_bar_keeps_its_real_thin_aabb(self):
        thin = cube("thin_bar", (4, 0.5, 4))
        kept, skipped = filter_collision_cubes([thin])
        self.assertEqual(kept, [thin])
        self.assertEqual(skipped, [])
        boxes, rotated = compress_adaptive(kept)
        self.assertEqual(boxes, [cube_aabb(thin)])
        self.assertEqual(rotated, [])

    def test_oblique_volume_uses_one_full_rotated_aabb_by_default(self):
        oblique = cube("tilted_book", rotation={"angles": [22.5, 0, 0], "origin": [8, 8, 8]})
        kept, skipped = filter_collision_cubes([oblique])
        self.assertEqual(kept, [oblique])
        self.assertEqual(skipped, [])
        boxes, rotated = compress_adaptive(kept)
        self.assertEqual(boxes, [cube_aabb(oblique)])
        self.assertEqual(len(boxes), 1)
        self.assertEqual(rotated, [])

    def test_selected_easel_can_use_one_visual_quiet_envelope(self):
        portrait = cube("portrait_panel", (12, 15, 2))
        easel = cube("portrait_easel", (4, 8, 2), rotation={"angles": [-35, 0, 0], "origin": [8, 0, 10]})
        portrait["index"] = 0
        easel["index"] = 1
        selected = select_collision_elements([portrait, easel], include_indices=[1])
        self.assertEqual(selected, [easel])
        self.assertEqual(single_collision_envelope(selected), [cube_aabb(easel)])

    def test_element_index_filter_keeps_original_indices_after_exclusion(self):
        panel = cube("panel")
        stand = cube("stand")
        ribbon = cube("ribbon")
        panel["index"], stand["index"], ribbon["index"] = 0, 1, 2
        selected = select_collision_elements([panel, stand, ribbon], exclude_indices=[0], include_indices=[1, 2])
        self.assertEqual(selected, [stand, ribbon])

    def test_collision_groups_still_split_a_multiblock_envelope_by_cell(self):
        # Grouped collision used to bypass grid detection entirely and return
        # one model-wide envelope. Component grouping must not disable cell splitting.
        model = {
            "textures": {"tex": "test:block/test"},
            "elements": [{
                "from": [-8, 0, 0], "to": [24, 4, 4],
                "faces": {"north": {"uv": [0, 0, 16, 16], "texture": "#tex"}},
            }],
        }
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "multiblock.json"
            path.write_text(json.dumps(model), encoding="utf-8")
            result = deploy_collision(str(path), res=4, collision_groups=[[0]])
        self.assertEqual(result["grid"]["x"], [0.0, 16.0])
        self.assertIsNotNone(result["cells"])
        self.assertEqual(set(result["cells"]), {(0, 0, 0), (1, 0, 0), (2, 0, 0)})
        self.assertEqual([len(result["cells"][cell]) for cell in sorted(result["cells"])], [1, 1, 1])
        for boxes in result["cells"].values():
            self.assertTrue(all(0.0 <= value <= 16.0 for box in boxes for value in box))
        self.assertEqual(set(result["cell_metrics"]), set(result["cells"]))
        for metrics in result["cell_metrics"].values():
            self.assertEqual(metrics["air_percent"], 0.0)
            self.assertEqual(metrics["miss_percent"], 0.0)

    def test_positive_volume_open_shell_uses_full_box_by_default(self):
        shell = cube("glass_cage", faces=4)
        kept, skipped = filter_collision_cubes([shell])
        self.assertEqual(kept, [shell])
        self.assertEqual(skipped, [])
        boxes, _ = compress_adaptive(kept)
        self.assertEqual(boxes, [cube_aabb(shell)])
        self.assertEqual(filter_collision_cubes([shell], include_shells=False)[0], [])

    def test_group_cover_planes_expand_one_object_envelope_but_not_distant_decor(self):
        core = cube("book_core", (4, 4, 4))
        core["from"] = [2, 2, 2]
        core["to"] = [4, 6, 4]
        core["group"] = "book"
        cover = cube("book_cover", (0, 4, 4))
        cover["from"] = [1, 2, 1]
        cover["to"] = [1, 6, 5]
        cover["group"] = "book"
        distant_plane = cube("decorative_ribbon", (2, 6, 0))
        distant_plane["from"] = [2, 6, 2]
        distant_plane["to"] = [4, 12, 2]
        distant_plane["group"] = "book"
        kept, skipped = filter_collision_cubes([core, cover, distant_plane])
        self.assertEqual(skipped, [])
        boxes, _ = compress_adaptive(kept)
        self.assertEqual(boxes, [(1, 2, 1, 4, 6, 5)])

    def test_volumetric_cube_is_kept(self):
        solid = cube("base")
        self.assertEqual(filter_collision_cubes([solid]), ([solid], []))


if __name__ == "__main__":
    unittest.main()
