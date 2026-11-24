"""Belief check: where do the source uvs actually land on the sheet?

Draws every 32x32 frame of both sheets at 8x, then overlays the uv window of each cube face so
the mismatch between the artist's uv layout and the stacked-frame sheets is visible instead of
inferred.
"""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "tools/deploy/model_sources/party_lights/party_lights.bbmodel"
OUT = ROOT / "build/party_lights_src"
ZOOM = 8
FRAME = 32


def sheets():
    data = json.loads(SRC.read_text(encoding="utf-8"))
    images = []
    for tex in data["textures"]:
        raw = base64.b64decode(tex["source"].split(",", 1)[1])
        images.append(Image.open(io.BytesIO(raw)).convert("RGBA"))
    return data, images


def main() -> None:
    data, images = sheets()
    OUT.mkdir(parents=True, exist_ok=True)
    tile = FRAME * ZOOM
    sheet = Image.new("RGBA", (tile * 4, tile * 2), (18, 18, 22, 255))
    for si, image in enumerate(images):
        for frame in range(4):
            crop = image.crop((0, frame * FRAME, FRAME, frame * FRAME + FRAME))
            crop = crop.resize((tile, tile), Image.NEAREST)
            canvas = Image.new("RGBA", (tile, tile), (30, 30, 36, 255))
            canvas.alpha_composite(crop)
            draw = ImageDraw.Draw(canvas)
            for unit in range(0, FRAME + 1, 4):
                x = unit * ZOOM
                draw.line([(x, 0), (x, tile)], fill=(255, 255, 255, 40))
                draw.line([(0, x), (tile, x)], fill=(255, 255, 255, 40))
            draw.rectangle([0, 0, tile - 1, tile - 1], outline=(255, 255, 255, 90))
            draw.text((6, 4), f"sheet {'ab'[si]} frame {frame}", fill=(255, 255, 255, 230))
            sheet.paste(canvas, (frame * tile, si * tile))
    sheet.save(OUT / "sheets_frames.png")
    print(f"wrote {(OUT / 'sheets_frames.png').relative_to(ROOT)} {sheet.size}")

    # Overlay the uv windows on frame 0 of sheet a: uv units equal pixels of the 32 px frame.
    base = Image.new("RGBA", (tile, tile), (18, 18, 22, 255))
    crop = images[0].crop((0, 0, FRAME, FRAME)).resize((tile, tile), Image.NEAREST)
    base.alpha_composite(crop)
    draw = ImageDraw.Draw(base)
    colours = {0: (255, 64, 64, 255), 1: (64, 200, 255, 255), 2: (120, 255, 120, 255)}
    for index, element in enumerate(data["elements"]):
        for face, spec in element["faces"].items():
            if spec.get("texture") is None:
                continue
            u0, v0, u1, v1 = spec["uv"]
            box = [min(u0, u1) * ZOOM, min(v0, v1) * ZOOM, max(u0, u1) * ZOOM, max(v0, v1) * ZOOM]
            draw.rectangle(box, outline=colours.get(index % 3, (255, 255, 0, 255)))
            draw.text((box[0] + 2, box[1] + 2), f"{index}{face[0]}", fill=colours.get(index % 3, (255, 255, 0, 255)))
    base.save(OUT / "uv_windows_frame0.png")
    print(f"wrote {(OUT / 'uv_windows_frame0.png').relative_to(ROOT)} {base.size}")


if __name__ == "__main__":
    main()
