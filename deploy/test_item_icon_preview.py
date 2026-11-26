import tempfile
import unittest
from pathlib import Path

from preview_item_icons import creative_tab_item_ids
from item_icon_preview import (FACE_VERTICES, face_is_front_facing,
                               apply_alpha_cutout)
from PIL import Image


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

    def test_alpha_cutout_is_binary(self):
        # Minecraft 的 ALPHA_CUTOUT 0.5：alpha>=128 全显、其余全隐，
        # 没有半透明过渡，否则预览会在镂空纹理边缘混出白边。
        img = Image.new("RGBA", (3, 1), (0, 0, 0, 0))
        img.putpixel((0, 0), (255, 255, 255, 127))
        img.putpixel((1, 0), (255, 255, 255, 128))
        img.putpixel((2, 0), (255, 255, 255, 255))
        out = apply_alpha_cutout(img)
        self.assertEqual([out.getpixel((i, 0))[3] for i in range(3)], [0, 255, 255])


if __name__ == "__main__":
    unittest.main()
