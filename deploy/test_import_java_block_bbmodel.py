import base64
from io import BytesIO
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image

from import_java_block_bbmodel import main


def texture_png() -> bytes:
    stream = BytesIO()
    Image.new("RGBA", (16, 16), (125, 82, 46, 255)).save(stream, format="PNG")
    return stream.getvalue()


class ImportJavaBlockDisplayTests(unittest.TestCase):
    def test_import_preserves_artist_authored_display_transforms(self):
        display = {
            "gui": {"rotation": [-150.05, -34.34, -179.37], "translation": [0, 0.75, 0], "scale": [0.7] * 3},
            "firstperson_righthand": {"rotation": [6.88, 8.58, 9.57], "translation": [0, 2.75, 0], "scale": [0.3] * 3},
        }
        texture = base64.b64encode(texture_png()).decode("ascii")
        faces = {face: {"uv": [0, 0, 16, 16], "texture": 0}
                 for face in ("north", "south", "east", "west", "up", "down")}
        source_model = {
            "meta": {"model_format": "java_block"},
            "resolution": {"width": 16, "height": 16},
            "textures": [{"source": f"data:image/png;base64,{texture}"}],
            "display": display,
            "elements": [{"from": [0, 0, 0], "to": [16, 16, 16], "faces": faces}],
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.bbmodel"
            model_out = root / "model.json"
            texture_out = root / "texture.png"
            source.write_text(json.dumps(source_model), encoding="utf-8")
            argv = ["import_java_block_bbmodel.py", str(source), "--model-out", str(model_out),
                    "--texture-out", str(texture_out), "--texture-name", "test"]
            with patch.object(sys, "argv", argv):
                main()
            imported = json.loads(model_out.read_text(encoding="utf-8"))
            self.assertIs(imported["ambientocclusion"], True)
            self.assertEqual(imported["textures"]["particle"], "pastoral_home:block/test_particle")
            self.assertNotIn("shade", imported["elements"][0])
            self.assertEqual(imported["display"], display)
            self.assertEqual(imported["elements"][0]["faces"]["north"]["texture"], "#bb_texture_0")
            with Image.open(root / "texture_particle.png") as particle:
                self.assertEqual(particle.size, (16, 16))

    def test_import_applies_positive_negative_and_reversed_axis_inflate(self):
        texture = base64.b64encode(texture_png()).decode("ascii")
        faces = {face: {"uv": [0, 0, 16, 16], "texture": 0}
                 for face in ("north", "south", "east", "west", "up", "down")}
        source_model = {
            "meta": {"model_format": "java_block"},
            "resolution": {"width": 16, "height": 16},
            "textures": [{"source": f"data:image/png;base64,{texture}"}],
            "elements": [
                {"from": [1, 2, 3], "to": [5, 6, 7], "inflate": 0.25, "faces": faces},
                {"from": [1, 2, 3], "to": [5, 6, 7], "inflate": -0.25, "faces": faces},
                {"from": [5, 6, 7], "to": [1, 2, 3], "inflate": 0.25, "faces": faces},
            ],
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, model_out, texture_out = root / "source.bbmodel", root / "model.json", root / "texture.png"
            source.write_text(json.dumps(source_model), encoding="utf-8")
            argv = ["import_java_block_bbmodel.py", str(source), "--model-out", str(model_out),
                    "--texture-out", str(texture_out), "--texture-name", "test"]
            with patch.object(sys, "argv", argv):
                main()
            elements = json.loads(model_out.read_text(encoding="utf-8"))["elements"]
            self.assertEqual(elements[0]["from"], [0.75, 1.75, 2.75])
            self.assertEqual(elements[0]["to"], [5.25, 6.25, 7.25])
            self.assertEqual(elements[1]["from"], [1.25, 2.25, 3.25])
            self.assertEqual(elements[1]["to"], [4.75, 5.75, 6.75])
            self.assertEqual(elements[2]["from"], [5.25, 6.25, 7.25])
            self.assertEqual(elements[2]["to"], [0.75, 1.75, 2.75])


if __name__ == "__main__":
    unittest.main()
