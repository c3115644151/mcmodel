import math
import tempfile
import unittest
from pathlib import Path

from preview_item_icons import preview_model_ids, registered_item_ids
from item_icon_proxy import VANILLA_BLOCK_GUI
from item_icon_preview import (FACE_VERTICES, SHADE_FLAT, SHADE_GAME, _mat_apply,
                               apply_alpha_cutout, apply_root_transform,
                               face_is_front_facing, gui_rotation_matrix,
                               gui_screen_point, load_sprite, render_projected_icon,
                               root_origin, shade_profile, shade_strength_profile,
                               tinted_water_sprite)
from PIL import Image


class RegisteredItemPreviewFilterTests(unittest.TestCase):
    def test_preview_filter_keeps_only_creative_tab_items(self):
        with tempfile.TemporaryDirectory() as temp:
            registry = Path(temp) / "src/main/java/com/pastoralhome/registry/ModItems.java"
            registry.parent.mkdir(parents=True)
            registry.write_text(
                'public static final DeferredItem<BlockItem> WEATHER_VANE = '
                'ITEMS.registerSimpleBlockItem("weather_vane", ModBlocks.WEATHER_VANE);\n'
                'public static final DeferredItem<BlockItem> WHEELBARROW = '
                'ITEMS.registerItem("wheelbarrow", WheelbarrowItem::new);\n'
                'public static final DeferredItem<Item> WHEELBARROW_WHEEL = '
                'ITEMS.registerSimpleItem("wheelbarrow_wheel");\n',
                encoding="utf-8",
            )
            tabs = Path(temp) / "src/main/java/com/pastoralhome/registry/ModCreativeTabs.java"
            tabs.write_text(
                'output.accept(ModItems.WEATHER_VANE.get());\n'
                'output.accept(ModItems.WHEELBARROW.get());\n',
                encoding="utf-8",
            )
            # A registered component that the tab never offers must stay out: the tab
            # list, not the registry, decides what counts as an inventory icon.
            self.assertEqual(registered_item_ids(Path(temp)), {"weather_vane", "wheelbarrow"})

    def test_underside_projects_from_low_y_plane(self):
        self.assertTrue(all(vertex[1] == 0 for vertex in FACE_VERTICES["down"]))
        self.assertTrue(all(vertex[1] == 1 for vertex in FACE_VERTICES["up"]))

    def test_backface_culling_hides_far_faces(self):
        # GUI 相机 (30,225,0) 从 north(-Z)/east(+X) 侧看，正面 cube 的
        # up/north/east 可见，down/south/west 是背面必须剔除。家具正面
        # 画在 north 面，所以 north 必须可见（否则图标显示背面）。
        cube = {"from": [0, 0, 0], "to": [16, 16, 16]}
        rot = (30.0, 225.0, 0.0)
        self.assertTrue(face_is_front_facing(cube, "up", rot))
        self.assertFalse(face_is_front_facing(cube, "down", rot))
        self.assertTrue(face_is_front_facing(cube, "north", rot))
        self.assertFalse(face_is_front_facing(cube, "south", rot))
        self.assertFalse(face_is_front_facing(cube, "west", rot))
        self.assertTrue(face_is_front_facing(cube, "east", rot))

    def test_negative_size_cube_inverts_facing(self):
        # 负尺寸灯罩（z: from>to）绕序翻转，内面成为正面：
        # 同一面名在负尺寸 cube 上可见性必须反转。
        neg = {"from": [0, 0, 16], "to": [16, 16, 0]}
        pos = {"from": [0, 0, 0], "to": [16, 16, 16]}
        rot = (30.0, 225.0, 0.0)
        # z 镜像只翻转顶点顺序含 z 轴的面；north/south 是 z 常数面不翻转。
        for face in ("up", "down", "east", "west"):
            self.assertNotEqual(face_is_front_facing(neg, face, rot),
                                face_is_front_facing(pos, face, rot), face)
        for face in ("north", "south"):
            self.assertEqual(face_is_front_facing(neg, face, rot),
                             face_is_front_facing(pos, face, rot), face)

    def test_alpha_cutout_is_binary_at_the_shader_threshold(self):
        # 原版 cutout 片元着色器是 "if (color.a < 0.1) discard;"，保留的像素以原色
        # 直接写入（不开混合）。阈值是 26，不是 128 —— 用 128 会把 0.1–0.5 的像素
        # 整片丢掉，镂空边缘比游戏里窄一圈。
        img = Image.new("RGBA", (3, 1), (0, 0, 0, 0))
        img.putpixel((0, 0), (255, 255, 255, 25))
        img.putpixel((1, 0), (255, 255, 255, 26))
        img.putpixel((2, 0), (255, 255, 255, 255))
        out = apply_alpha_cutout(img)
        self.assertEqual([out.getpixel((i, 0))[3] for i in range(3)], [0, 255, 255])


class WaterRenderingTests(unittest.TestCase):
    def test_water_sprite_is_tinted_blue(self):
        grey = Image.new("RGBA", (16, 16), (194, 194, 194, 180))
        out = tinted_water_sprite(grey, "minecraft:block/water_still")
        r, g, b, a = out.getpixel((0, 0))
        self.assertGreater(b, g)
        self.assertGreater(g, r)
        self.assertEqual(a, 180)

    def test_non_water_sprite_untouched(self):
        stone = Image.new("RGBA", (16, 16), (128, 128, 128, 255))
        out = tinted_water_sprite(stone, "minecraft:block/stone")
        self.assertEqual(out.getpixel((0, 0)), (128, 128, 128, 255))

    def test_component_select_preview_uses_single_fallback(self):
        node = {"type": "minecraft:select", "property": "minecraft:component",
                "cases": [{"when": 1, "model": {"type": "minecraft:model", "model": "ns:full"}}],
                "fallback": {"type": "minecraft:model", "model": "ns:empty"}}
        self.assertEqual(preview_model_ids(node), ["ns:empty"])




class GuiProjectionTests(unittest.TestCase):
    """The GUI icon camera has to be Minecraft's chain, not a hand-built basis."""

    def test_yaw_225_puts_positive_x_and_z_on_the_left(self):
        # ItemTransform rotates the model by yaw 225 and the item camera looks down
        # -Z with +Y up, so screen x = (R*p).x = -cos45*(x+z). Building that basis by
        # hand once gave +(x+z), which mirrored every asymmetric icon.
        left_of_center, _ = gui_screen_point((12.0, 8.0, 8.0), (30.0, 225.0, 0.0))
        self.assertLess(left_of_center[0], -1.0)
        also_left, _ = gui_screen_point((8.0, 8.0, 12.0), (30.0, 225.0, 0.0))
        self.assertLess(also_left[0], -1.0)

    def test_up_is_negative_screen_y(self):
        above, _ = gui_screen_point((8.0, 14.0, 8.0), (30.0, 225.0, 0.0))
        self.assertLess(above[1], -1.0)

    def test_rotation_matrix_matches_the_display_chain(self):
        matrix = gui_rotation_matrix((0.0, 225.0, 0.0))
        east = _mat_apply(matrix, (0.5, 0.0, 0.5))
        self.assertAlmostEqual(east[0], -math.cos(math.radians(45)), places=6)

    def test_root_transform_translation_is_in_blocks(self):
        # A root transform's translation uses blocks, so [0, 1, 0] raises the model by
        # a full 16 units; reading it as 1/16 blocks left such icons 16 units off.
        moved = apply_root_transform((8.0, 0.0, 8.0), {"translation": [0, 1, 0]})
        self.assertAlmostEqual(moved[1], 16.0, places=6)

    def test_root_transform_origin_defaults_to_opposing_corner(self):
        self.assertEqual(root_origin({}), (16.0, 16.0, 16.0))
        self.assertEqual(root_origin({"origin": "center"}), (8.0, 8.0, 8.0))


class RasterizerSamplingTests(unittest.TestCase):
    def test_flat_panel_with_degenerate_uv_still_draws(self):
        # Foliage and lattice panels export as zero-thickness planes whose UV rectangle
        # collapses to one texel column. A per-quad perspective transform cannot invert
        # that and dropped the face; barycentric sampling has no such singularity.
        with tempfile.TemporaryDirectory() as temp:
            sprite_path = Path(temp) / "panel.png"
            Image.new("RGBA", (16, 16), (40, 160, 60, 255)).save(sprite_path)
            model = {
                "textures": {"panel": "pastoral_home:block/panel"},
                "elements": [{
                    "from": [8.0, 1.0, 1.0], "to": [8.0, 15.0, 15.0],
                    "faces": {
                        "east": {"uv": [4.0, 0.0, 4.0, 16.0], "texture": "#panel"},
                        "west": {"uv": [4.0, 0.0, 4.0, 16.0], "texture": "#panel"},
                    },
                }],
                "display": {"gui": dict(VANILLA_BLOCK_GUI)},
            }
            icon = render_projected_icon(model, lambda _ref: sprite_path,
                                         tuple(VANILLA_BLOCK_GUI["scale"]),
                                         tuple(VANILLA_BLOCK_GUI["rotation"]), size=64)
            painted = sum(1 for value in icon.getchannel("A").get_flattened_data() if value)
            self.assertGreater(painted, 0)


class ShadeProfileTests(unittest.TestCase):
    def test_game_profile_matches_the_measured_capture(self):
        # Fitted by diag_gui_shading.py from a real container capture: horizontal
        # faces come out at 0.40 of their flat colour, east 0.65, up/down 1.0. If
        # someone "fixes" this table back to FaceBakery's 0.8 constants, the icons
        # stop matching the game again, so pin it.
        self.assertEqual(SHADE_GAME["north"], 0.40)
        self.assertEqual(SHADE_GAME["south"], 0.40)
        self.assertEqual(SHADE_GAME["east"], 0.65)
        self.assertEqual(SHADE_GAME["up"], 1.0)
        self.assertEqual(shade_profile("flat"), SHADE_FLAT)
        self.assertEqual(shade_profile(None), SHADE_GAME)
        self.assertEqual(shade_profile("nonsense"), SHADE_GAME)

    def test_game_shading_darkens_side_faces_only(self):
        with tempfile.TemporaryDirectory() as temp:
            sprite_path = Path(temp) / "sprite.png"
            Image.new("RGBA", (16, 16), (200, 200, 200, 255)).save(sprite_path)
            model = {
                "textures": {"t": "pastoral_home:block/cube"},
                "elements": [{"from": [0, 0, 0], "to": [16, 16, 16],
                              "faces": {name: {"uv": [0, 0, 16, 16], "texture": "#t"}
                                        for name in ("north", "east", "up")}}],
                "display": {"gui": dict(VANILLA_BLOCK_GUI)},
            }
            scale = tuple(VANILLA_BLOCK_GUI["scale"])
            rotation = tuple(VANILLA_BLOCK_GUI["rotation"])
            game = render_projected_icon(model, lambda _ref: sprite_path, scale, rotation,
                                        size=64, face_shade=shade_profile("game"))
            flat = render_projected_icon(model, lambda _ref: sprite_path, scale, rotation,
                                        size=64, face_shade=shade_profile("flat"))
            # The north face occupies the left half of the cube silhouette; sampling it
            # in both renders shows the measured factor 0.40 and leaves up at 1.0.
            import numpy as np
            ids = None
            _, ids = render_projected_icon(model, lambda _ref: sprite_path, scale, rotation,
                                           size=64, face_shade=shade_profile("flat"),
                                           return_face_ids=True)
            north = (ids % 8) == 3
            up = (ids % 8) == 2
            game_px = np.asarray(game)[:, :, :3]
            flat_px = np.asarray(flat)[:, :, :3]
            self.assertAlmostEqual(float(game_px[north].mean() / flat_px[north].mean()), 0.40, places=2)
            self.assertAlmostEqual(float(game_px[up].mean() / flat_px[up].mean()), 1.0, places=2)

    def test_strength_is_a_continuous_dial(self):
        # 0 = flat, 1 = 实测值, 1.5 = 更狠；中间值按线性插值，且显式强度优先于档位名。
        self.assertEqual(shade_strength_profile(0.0), SHADE_FLAT)
        self.assertEqual(shade_strength_profile(1.0), SHADE_GAME)
        self.assertEqual(shade_strength_profile(0.5)["north"], 0.70)
        self.assertEqual(shade_strength_profile(0.5)["east"], 0.825)
        self.assertEqual(shade_strength_profile(0.5)["up"], 1.0)
        self.assertEqual(shade_strength_profile(1.5)["north"], 0.10)
        self.assertEqual(shade_profile("flat", 1.0), SHADE_GAME)
        self.assertEqual(shade_profile("game", 0.0), SHADE_FLAT)
        # 越界钳制，非法值退回默认强度。
        self.assertEqual(shade_strength_profile(9.0), shade_strength_profile(1.5))
        self.assertEqual(shade_strength_profile(-3.0), SHADE_FLAT)
        self.assertEqual(shade_strength_profile("nonsense"), SHADE_GAME)
        # 强度越低整体越亮：亮面恒定，侧面单调。
        ladder = [shade_strength_profile(s)["north"] for s in (0.0, 0.25, 0.5, 0.75, 1.0)]
        self.assertEqual(ladder, sorted(ladder, reverse=True))


if __name__ == "__main__":
    unittest.main()
