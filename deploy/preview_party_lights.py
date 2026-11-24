"""Render the party-lights source .bbmodel with the offline rasteriser.

The .bbmodel declares uv_width/uv_height = 32x32 but its PNG sheets are 32x128: four stacked
32 px frames. Blockbench reads the sheet as one 32x32 atlas, so uv units are 2 sheet pixels and
every uv window lands inside frame 0. Java block models speak the same 0..16 space, so the uvs
pass through unchanged - only the sheet has to be cut down to frame 0 to keep the sampling
identical. Scaling the uvs (or feeding the 128 px tall sheet directly) samples empty rows.
"""
from __future__ import annotations

import base64
import io
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "deploy"))

import preview_block_model as pbm  # noqa: E402

SRC = ROOT / "tools/deploy/model_sources/party_lights/party_lights.bbmodel"
OUT_DIR = ROOT / "build/party_lights_src"
# Blockbench stores these uvs in the 0..16 space (uv unit = 2 sheet pixels); drop the factor and
# every face samples the wrong quadrant.
UV_SCALE = 1.0


def read_source():
    data = json.loads(SRC.read_text(encoding="utf-8"))
    sheets = []
    for tex in data["textures"]:
        raw = base64.b64decode(tex["source"].split(",", 1)[1])
        sheet = Image.open(io.BytesIO(raw)).convert("RGBA")
        sheets.append(sheet.crop((0, 0, 32, 32)))
    return data, sheets


def to_java_model(data) -> dict:
    textures = {str(i): f"local:sheet_{chr(ord('a') + i)}" for i in range(len(data["textures"]))}
    elements = []
    for index, element in enumerate(data["elements"]):
        faces = {}
        for face, spec in element["faces"].items():
            tex = spec.get("texture")
            if tex is None:
                continue
            faces[face] = {
                "texture": f"#{tex}",
                "uv": [round(value * UV_SCALE, 6) for value in spec["uv"]],
            }
        elements.append({"name": f"{index}_{element['name']}", "from": element["from"],
                         "to": element["to"], "faces": faces})
    return {"textures": textures, "elements": elements}


def main() -> None:
    data, sheets = read_source()
    model = to_java_model(data)
    cache: dict = {}
    for index, image in enumerate(sheets):
        key = f"local:sheet_{chr(ord('a') + index)}"
        cache[key] = image
        cache[(key, "alpha")] = np.asarray(image, dtype=np.float64)[..., 3] / 255.0
    quads = pbm.collect_model(model, (0.0, 0.0), 1.0, cache)
    print(f"quads={len(quads)} elements={len(model['elements'])}")
    for quad in quads:
        print(f"  {quad['name']:10s} {quad['face']:6s} coverage={quad['coverage']:.2f}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pbm.contact_sheet(quads, OUT_DIR / "src_textured.png", ["front", "quarter", "iso"], None,
                      760, 560, background=(24, 26, 30, 255))
    pbm.contact_sheet(quads, OUT_DIR / "src_clay.png", ["front", "quarter", "iso"], None,
                      760, 560, background=(24, 26, 30, 255), clay=pbm.CLAY)


if __name__ == "__main__":
    main()
