#!/usr/bin/env python3
"""Render a local 3D check of the board surface with dynamically placed sample sheets."""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "src/main/resources/assets/pastoral_home"
STAGE = ROOT / "build/entryway_models"

from item_icon_preview import _project_view, render_projected_icon
from item_icon_proxy import geometry_bounds
from normalize_item_icons import resolve_texture


def placed_authored_element(model: dict, center_x: float, center_y: float, depth: float):
    element = json.loads(json.dumps(model["elements"][0]))
    offset = [center_x - 8.0, center_y - 8.0, depth - 8.0]
    for point in ("from", "to"):
        element[point] = [float(value) + offset[axis] for axis, value in enumerate(element[point])]
    if element.get("rotation"):
        element["rotation"]["origin"] = [float(value) + offset[axis]
                                            for axis, value in enumerate(element["rotation"]["origin"])]
    return element


def render_view(model, view, size=512):
    bounds = geometry_bounds(model)
    corners = [(x, y, z) for x in (bounds[0], bounds[3])
               for y in (bounds[1], bounds[4]) for z in (bounds[2], bounds[5])]
    points = [_project_view(point, view)[0] for point in corners]
    low_x, high_x = min(p[0] for p in points), max(p[0] for p in points)
    low_y, high_y = min(p[1] for p in points), max(p[1] for p in points)
    scale = min((size - 40) / max(1.0, high_x - low_x),
                (size - 40) / max(1.0, high_y - low_y))
    offset = (-(low_x + high_x) / 2, -(low_y + high_y) / 2)
    return render_projected_icon(model, lambda ref: resolve_texture(ROOT, ref),
                                gui_scale=(1.0, 1.0, 1.0), gui_rotation=(0.0, 0.0, 0.0),
                                size=size, view=view, pixels_per_unit=scale,
                                projection_offset=offset)


def main():
    model = json.loads((STAGE / "bulletin_board_world.json").read_text(encoding="utf-8"))
    variants = json.loads((STAGE / "bulletin_page_variants.json").read_text(encoding="utf-8"))["variants"]
    # A front and back sheet deliberately share an x/y center to exercise both faces.
    placements = ((6, 8.0, 30.0, 0), (7, 18.0, 23.0, 0), (0, 8.0, 30.0, 1))
    for variant, center_x, center_y, side in placements:
        metadata = variants[variant]
        model_id = f"bulletin_page_variant_{variant}_{'front' if side == 0 else 'back'}"
        authored_page = json.loads((ASSETS / f"models/item/{model_id}.json").read_text(encoding="utf-8"))
        depth = metadata["depth"] if side == 0 else 7.05 + 9.05 - metadata["depth"]
        shadow_id = f"bulletin_shadow_variant_{variant}_{'front' if side == 0 else 'back'}"
        authored_shadow = json.loads((ASSETS / f"models/item/{shadow_id}.json").read_text(encoding="utf-8"))
        if authored_shadow.get("elements"):
            model["elements"].append(placed_authored_element(authored_shadow, center_x, center_y, depth))
        placed = placed_authored_element(authored_page, center_x, center_y, depth)
        model["elements"].append(placed)
    views = (("isometric", "3D"), ("perspective_front", "Front"), ("front", "Back"), ("top", "Top"))
    sheet = Image.new("RGBA", (1024, 1040), (43, 43, 43, 255))
    font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 18)
    for index, (view, title) in enumerate(views):
        sprite = render_view(model, view)
        x, y = (index % 2) * 512, (index // 2) * 520
        sheet.alpha_composite(sprite, (x, y))
        ImageDraw.Draw(sheet).text((x + 12, y + 488), f"{title}  |  sample posted papers", font=font, fill="white")
    output = STAGE / "bulletin_board_posted_pages_preview.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)
    print(f"Rendered posted-page board preview to {output}")


if __name__ == "__main__":
    main()
