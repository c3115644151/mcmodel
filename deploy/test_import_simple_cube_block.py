import base64
import io
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from import_simple_cube_block import import_simple_cube


class ImportSimpleCubeBlockTests(unittest.TestCase):
    def _source(self, texture_indices=(0, 0, 0, 0, 0, 0)):
        image = Image.new("RGBA", (64, 64), (120, 90, 60, 255))
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        encoded = base64.b64encode(stream.getvalue()).decode("ascii")
        textures = [
            {"name": f"texture_{i}", "source": f"data:image/png;base64,{encoded}"}
            for i in range(max(texture_indices) + 1)
        ]
        uvs = {
            "north": [0, 0, 16, 16], "east": [0, 17, 16, 33],
            "south": [17, 0, 33, 16], "west": [17, 17, 33, 33],
            "up": [16, 50, 0, 34], "down": [50, 0, 34, 16],
        }
        faces = {face: {"uv": uvs[face], "texture": index} for face, index in zip(uvs, texture_indices)}
        return {"textures": textures, "elements": [{"from": [0, 0, 0], "to": [16, 16, 16], "faces": faces}]}

    def test_emits_single_full_cube_with_face_uvs_and_block_assets(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.bbmodel"
            source.write_text(json.dumps(self._source()), encoding="utf-8")
            assets = root / "assets/pastoral_home"
            result = import_simple_cube(source, assets, "test_cube", namespace="pastoral_home")
            model = json.loads((assets / "models/block/test_cube.json").read_text(encoding="utf-8"))
            self.assertEqual(result["face_texture_slots"], {face: "all" for face in ("north", "east", "south", "west", "up", "down")})
            self.assertEqual(model["elements"][0]["from"], [0, 0, 0])
            self.assertEqual(model["elements"][0]["to"], [16, 16, 16])
            self.assertTrue((assets / "blockstates/test_cube.json").is_file())
            self.assertTrue((assets / "items/test_cube.json").is_file())
            with Image.open(assets / "textures/block/test_cube_all.png") as texture:
                self.assertEqual(texture.size, (16, 16))

    def test_pillar_mode_emits_vanilla_axis_rotations(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.bbmodel"
            source.write_text(json.dumps(self._source()), encoding="utf-8")
            assets = root / "assets/pastoral_home"
            import_simple_cube(source, assets, "test_pillar", pillar_axis=True, namespace="pastoral_home")
            blockstate = json.loads((assets / "blockstates/test_pillar.json").read_text(encoding="utf-8"))
            self.assertEqual(blockstate["variants"]["axis=x"]["x"], 90)
            self.assertEqual(blockstate["variants"]["axis=x"]["y"], 90)
            self.assertEqual(blockstate["variants"]["axis=z"]["x"], 90)

    def test_rejects_non_full_or_multi_material_models(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.bbmodel"
            bad = self._source((0, 0, 0, 0, 0, 1))
            source.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "one source texture"):
                import_simple_cube(source, root / "assets", "invalid")
            bad = self._source()
            bad["elements"][0]["from"][1] = 1
            source.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "span exactly"):
                import_simple_cube(source, root / "assets", "invalid")


if __name__ == "__main__":
    unittest.main()
