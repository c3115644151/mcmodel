import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/deploy"))
import preview_rider_placement as preview


def profile(name):
    path = preview.PROFILE_DIR / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8-sig"))


class RiderPlacementPreviewTests(unittest.TestCase):
    def test_telescope_seat_is_outside_model_and_at_eyepiece_height(self):
        cfg = profile("telescope")
        model = json.loads((ROOT / cfg["model"]).read_text(encoding="utf-8-sig"))
        self.assertAlmostEqual(preview.rider_anchors(cfg, "north")[0][1], 0.16)
        self.assertAlmostEqual(preview.rider_anchors(cfg, "north")[0][2] / 16, 1.48)
        for facing in preview.FACINGS:
            model_parts = preview.model_meshes(model, facing)
            rider_parts, eyes = preview.player_boxes(cfg, facing)
            self.assertFalse(any(preview.model_mesh_intersects_aabb(model_mesh, player_box)
                                 for player_box, _part in rider_parts for model_mesh in model_parts),
                             msg=f"player entity AABB overlaps the telescope in {facing} facing")
            eye_point = tuple(eyes[0])
            point_box = eye_point + eye_point
            self.assertFalse(any(preview.model_mesh_intersects_aabb(model_mesh, point_box)
                                 for model_mesh in model_parts),
                             msg=f"player eye point is inside the telescope in {facing} facing")
            if facing == "north":
                self.assertAlmostEqual(eyes[0][1], 26.08)

    def test_player_view_ray_points_toward_the_telescope(self):
        cfg = profile("telescope")
        model = json.loads((ROOT / cfg["model"]).read_text(encoding="utf-8-sig"))
        for facing in preview.FACINGS:
            dx, dz = preview.VECTORS[facing]
            self.assertEqual(preview.player_look_vector(cfg, facing), (dx, dz))
        lens_by_facing = {facing: preview.telescope_camera_origin(cfg,
                         preview.player_boxes(cfg, facing)[1][0], facing) for facing in preview.FACINGS}
        self.assertAlmostEqual(lens_by_facing["north"][2] / 16.0, 1.05)
        model_bounds = {facing: preview.model_boxes(model, facing) for facing in preview.FACINGS}
        for facing in preview.FACINGS:
            mins = [min(box[axis] for box in model_bounds[facing]) / 16.0 for axis in range(3)]
            maxs = [max(box[axis + 3] for box in model_bounds[facing]) / 16.0 for axis in range(3)]
            lens = lens_by_facing[facing]
            if facing == "north": self.assertGreater(lens[2] / 16.0, maxs[2] + 0.03)
            if facing == "south": self.assertLess(lens[2] / 16.0, mins[2] - 0.03)
            if facing == "east": self.assertLess(lens[0] / 16.0, mins[0] - 0.03)
            if facing == "west": self.assertGreater(lens[0] / 16.0, maxs[0] + 0.03)

    def test_telescope_rear_seat_rotates_with_all_four_facings(self):
        cfg = profile("telescope")
        anchors = {facing: preview.rider_anchors(cfg, facing)[0] for facing in preview.FACINGS}
        self.assertGreater(anchors["north"][2], 16)
        self.assertLess(anchors["east"][0], 0)
        self.assertLess(anchors["south"][2], 0)
        self.assertGreater(anchors["west"][0], 16)

    def test_supported_furniture_profiles_render_riders(self):
        for name in ("oak_high_back_chair", "sofa", "wooden_stool", "bed"):
            with self.subTest(profile=name):
                cfg = profile(name)
                boxes, eyes = preview.player_boxes(cfg, "north")
                self.assertTrue(boxes)
                self.assertTrue(eyes)

    def test_chair_sofa_and_stool_profiles_match_java_seat_heights(self):
        cases = {
            "oak_high_back_chair": ("OakHighBackChairBlock.java", 10.0 / 16.0),
            "sofa": ("SofaBlock.java", 8.0 / 16.0),
            "wooden_stool": ("WoodenStoolBlock.java", 8.0 / 16.0),
        }
        for name, (java_name, expected) in cases.items():
            with self.subTest(profile=name):
                source = (ROOT / "src/main/java/com/pastoralhome/block" / java_name).read_text(encoding="utf-8")
                match = re.search(r"SeatEntity\.sit\(level,\s*pos,\s*player,\s*([0-9.]+)\s*/\s*16\.0\)", source)
                self.assertIsNotNone(match)
                self.assertAlmostEqual(float(match.group(1)) / 16.0,
                                       profile(name)["seat_height_blocks"])
                self.assertAlmostEqual(expected, profile(name)["seat_height_blocks"])

    def test_bed_preview_matches_the_java_sleep_anchor_and_both_spots(self):
        source = (ROOT / "src/main/java/com/pastoralhome/block/BedBlock.java").read_text(encoding="utf-8")
        match = re.search(r"SLEEPING_Y\s*=\s*([0-9.]+)\s*/\s*16\.0", source)
        self.assertIsNotNone(match)
        cfg = profile("bed")
        self.assertEqual(len(cfg["sleep_spots_px"]), 2)
        self.assertEqual(cfg["sleep_spots_px"][0][1], float(match.group(1)))

    def test_telescope_profile_matches_java_rear_offset_and_seat_height(self):
        source = (ROOT / "src/main/java/com/pastoralhome/entity/SeatEntity.java").read_text(encoding="utf-8")
        self.assertIn("TELESCOPE_REAR_OFFSET_BLOCKS = 0.98", source)
        self.assertAlmostEqual(profile("telescope")["behind_offset_blocks"], 0.98)
        self.assertIn("TELESCOPE_CAMERA_FORWARD_OFFSET_BLOCKS = 0.43", source)
        self.assertAlmostEqual(profile("telescope")["camera_forward_offset_blocks"], 0.43)
        mod_entities = (ROOT / "src/main/java/com/pastoralhome/registry/ModEntities.java").read_text(encoding="utf-8")
        self.assertIn(".sized(0.01f, 0.01f)", mod_entities)
        seat_source = (ROOT / "src/main/java/com/pastoralhome/entity/SeatEntity.java").read_text(encoding="utf-8")
        self.assertIn("add(passenger.getVehicleAttachmentPoint(this))", seat_source)

    def test_telescope_renderer_restores_centered_item_model_to_block_coordinates(self):
        cfg = profile("telescope")
        model = json.loads((ROOT / cfg["model"]).read_text(encoding="utf-8-sig"))
        min_model_y = min(box[1] for box in preview.model_boxes(model, "north"))
        renderer = (ROOT / "src/main/java/com/pastoralhome/client/TelescopeBlockEntityRenderer.java")\
            .read_text(encoding="utf-8")
        self.assertIn("poseStack.translate(0.5F, 0.5F, 0.5F)", renderer)
        self.assertIn("23.46821F / 16.0F - 0.5F", renderer)
        # ItemModelResolver's centered coordinates lose half a block; root
        # translation restores raw block-model Y, where the authored legs are >0.
        restored_min_y = min_model_y / 16.0
        self.assertGreater(restored_min_y, 0.0)

    def test_vanilla_player_metrics_are_explicit(self):
        dimensions = preview.VANILLA_PLAYER["entity_dimensions_blocks"]
        self.assertEqual(dimensions["standing"]["aabb"], [0.6, 1.8])
        self.assertEqual(dimensions["standing"]["eye_height"], 1.62)
        self.assertEqual(dimensions["sleeping"]["aabb"], [0.2, 0.2])
        self.assertEqual(preview.VANILLA_PLAYER["player_model_parts_px"]["leg"], [4, 12, 4])
        self.assertEqual(preview.VANILLA_PLAYER["player_model_parts_px"]["arm_classic_skin"], [4, 12, 4])
        self.assertEqual(preview.VANILLA_PLAYER["player_model_parts_px"]["arm_slim_skin"], [3, 12, 4])
        self.assertAlmostEqual(preview.VANILLA_PLAYER["avatar_render_scale"], 0.9375)
        client_jar = ROOT / ".gradle/caches/minecraft/versions/26.1.2/client.jar"

        def disassemble(class_name):
            return subprocess.run(["javap", "-classpath", str(client_jar), "-c", "-p", class_name],
                                  check=True, capture_output=True, text=True).stdout

        entity_types = disassemble("net.minecraft.world.entity.EntityType")
        player_start = entity_types.index("// String player")
        player_section = entity_types[player_start:player_start + 1400]
        avatar = disassemble("net.minecraft.world.entity.Avatar")
        living = disassemble("net.minecraft.world.entity.LivingEntity")
        renderer = disassemble("net.minecraft.client.renderer.entity.player.AvatarRenderer")
        humanoid = disassemble("net.minecraft.client.model.HumanoidModel")
        player_model = disassemble("net.minecraft.client.model.player.PlayerModel")
        for literal in ("float 0.6f", "float 1.8f", "float 1.62f"):
            self.assertIn(literal, player_section)
        self.assertIn("double 0.6d", avatar)  # default player VEHICLE attachment
        self.assertIn("float 0.2f", living)   # vanilla sleeping pose dimensions
        self.assertIn("float 0.9375f", renderer)
        for literal in ("float -1.4137167f", "float -0.62831855f", "float 0.31415927f"):
            self.assertIn(literal, humanoid)
        self.assertIn("float 3.0f", player_model)  # slim skin arm width

        client_jar = ROOT / ".gradle/caches/minecraft/versions/26.1.2/client.jar"
        def disassemble(class_name):
            return subprocess.run(["javap", "-classpath", str(client_jar), "-c", "-p", class_name],
                                  check=True, capture_output=True, text=True).stdout

        player_type = disassemble("net.minecraft.world.entity.EntityType")
        avatar = disassemble("net.minecraft.world.entity.Avatar")
        living = disassemble("net.minecraft.world.entity.LivingEntity")
        renderer = disassemble("net.minecraft.client.renderer.entity.player.AvatarRenderer")
        humanoid = disassemble("net.minecraft.client.model.HumanoidModel")
        self.assertIn("float 0.6f", player_type)
        self.assertIn("float 1.8f", player_type)
        self.assertIn("float 1.62f", player_type)
        self.assertIn("double 0.6d", avatar)
        self.assertIn("float 0.2f", living)
        self.assertIn("float 0.9375f", renderer)
        self.assertIn("float -1.4137167f", humanoid)
        self.assertIn("float -0.62831855f", humanoid)


if __name__ == "__main__":
    unittest.main()
