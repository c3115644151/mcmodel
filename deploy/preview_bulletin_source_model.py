#!/usr/bin/env python3
"""Render the unfiltered BBModel so paper-plane variants can be reviewed in context."""
from __future__ import annotations

import json
from itertools import product
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "build/entryway_models/bulletin_board_authored_full.json"
ASSET_ROOT = ROOT / "src/main/resources/assets/pastoral_home"
OUTPUT = ROOT / "build/entryway_models/bulletin_board_source_model_preview.png"

from item_icon_preview import _project_view, render_projected_icon
from item_icon_proxy import geometry_bounds
from normalize_item_icons import resolve_texture


def main():
    model = json.loads(MODEL.read_text(encoding="utf-8"))
    views = (("isometric", "Iso"), ("front", "Front"), ("side", "Side"), ("top", "Top"))
    size = 480
    sheet = Image.new("RGBA", (size * 2, (size + 30) * 2), (42, 42, 42, 255))
    font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 18)
    bounds = geometry_bounds(model)
    corners = [(x, y, z) for x, y, z in product((bounds[0], bounds[3]),
                                                  (bounds[1], bounds[4]),
                                                  (bounds[2], bounds[5]))]
    for index, (view, label) in enumerate(views):
        projected = [_project_view(point, view)[0] for point in corners]
        lo_x, hi_x = min(p[0] for p in projected), max(p[0] for p in projected)
        lo_y, hi_y = min(p[1] for p in projected), max(p[1] for p in projected)
        ppu = min((size - 36) / max(1.0, hi_x - lo_x), (size - 36) / max(1.0, hi_y - lo_y))
        offset = (-(lo_x + hi_x) * 0.5, -(lo_y + hi_y) * 0.5)
        sprite = render_projected_icon(model, lambda ref: resolve_texture(ROOT, ref),
                                       gui_scale=(1.0, 1.0, 1.0), gui_rotation=(0.0, 0.0, 0.0),
                                       size=size, view=view, pixels_per_unit=ppu,
                                       projection_offset=offset)
        x, y = (index % 2) * size, (index // 2) * (size + 30)
        sheet.alpha_composite(sprite, (x, y))
        ImageDraw.Draw(sheet).text((x + 10, y + size + 3), label, font=font, fill="white")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(OUTPUT)
    print(f"Rendered unfiltered source board to {OUTPUT}")


if __name__ == "__main__":
    main()
