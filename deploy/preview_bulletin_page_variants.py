#!/usr/bin/env python3
"""Contact sheet of the recentered, original BBModel paper-plane variants."""
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


def project_variant(model, view, panel=192):
    bounds = geometry_bounds(model)
    corners = [(x, y, z) for x in (bounds[0], bounds[3])
               for y in (bounds[1], bounds[4]) for z in (bounds[2], bounds[5])]
    pts = [_project_view(point, view)[0] for point in corners]
    min_x, max_x = min(p[0] for p in pts), max(p[0] for p in pts)
    min_y, max_y = min(p[1] for p in pts), max(p[1] for p in pts)
    scale = min((panel - 24) / max(max_x - min_x, 1),
                (panel - 24) / max(max_y - min_y, 1))
    return render_projected_icon(model, lambda ref: resolve_texture(ROOT, ref),
                                 gui_scale=(1, 1, 1), gui_rotation=(0, 0, 0),
                                 size=panel, view=view, pixels_per_unit=scale,
                                 projection_offset=(-(min_x + max_x) / 2, -(min_y + max_y) / 2))


def main():
    report = json.loads((STAGE / "bulletin_page_variants.json").read_text(encoding="utf-8"))
    panel, label_h = 192, 26
    columns = 5
    rows = (len(report["variants"]) + columns - 1) // columns
    image = Image.new("RGBA", (panel * columns, (panel + label_h) * rows), (48, 48, 48, 255))
    font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 12)
    for variant in report["variants"]:
        index = variant["variant"]
        model = json.loads((ASSETS / f"models/item/bulletin_page_variant_{index}_front.json").read_text(encoding="utf-8"))
        # The north view is the board's writing face; include south/back as a diagnostic.
        north = project_variant(model, "perspective_front", panel)
        x, y = (index % columns) * panel, (index // columns) * (panel + label_h)
        image.alpha_composite(north, (x, y))
        ImageDraw.Draw(image).text((x + 6, y + panel + 4),
                                   f"{index} ← BB element {variant['source_element']}  {variant['width']:.1f}×{variant['height']:.1f}",
                                   font=font, fill="white")
    output = STAGE / "bulletin_page_variants_preview.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)
    print(f"Rendered original bulletin paper variants to {output}")


if __name__ == "__main__":
    main()
