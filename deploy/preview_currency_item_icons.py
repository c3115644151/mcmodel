#!/usr/bin/env python3
"""Preview the authored 16x16 currency PNGs as flat generated item icons."""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "src/main/resources/assets/pastoral_home"
OUTPUT = ROOT / "build/requested_models/currency/coin_icons.png"
REPORT = ROOT / "build/requested_models/currency/coin_icons.json"
KINDS = ("copper", "gold", "silver")
SCALE = 8
TILE_W, TILE_H = 144, 176

canvas = Image.new("RGBA", (TILE_W * len(KINDS), TILE_H), (45, 45, 49, 255))
draw = ImageDraw.Draw(canvas)
results = []
for index, kind in enumerate(KINDS):
    source = ASSETS / f"textures/item/coin_{kind}.png"
    with Image.open(source) as opened:
        icon = opened.convert("RGBA")
    if icon.size != (16, 16):
        raise ValueError(f"{source.name} must be native 16x16, got {icon.size}")
    bbox = icon.getchannel("A").getbbox()
    if bbox is None:
        raise ValueError(f"{source.name} is completely transparent")
    zoomed = icon.resize((16 * SCALE, 16 * SCALE), Image.Resampling.NEAREST)
    cell_x = index * TILE_W
    draw.rectangle((cell_x + 31, 22, cell_x + 31 + 16 * SCALE, 22 + 16 * SCALE),
                   fill=(66, 66, 70, 255))
    canvas.alpha_composite(zoomed, (cell_x + 31, 22))
    draw.text((cell_x + 12, 156), f"{kind.title()} coin · 16×16 PNG", fill=(238, 238, 238, 255))
    center_offset = [round((bbox[0] + bbox[2]) / 2 - 8, 4), round((bbox[1] + bbox[3]) / 2 - 8, 4)]
    alpha = icon.getchannel("A")
    results.append({
        "item": f"coin_{kind}", "mode": icon.mode, "size": list(icon.size),
        "visible_bbox": list(bbox), "center_offset": center_offset,
        "alpha_coverage": round(sum(1 for value in alpha.getdata() if value) / 256, 4),
        "pure_2d_item": True,
    })

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
canvas.save(OUTPUT)
REPORT.write_text(json.dumps({"coins": results}, indent=2) + "\n", encoding="utf-8")
print(f"Rendered three native 16x16 2D coin textures to {OUTPUT}")
