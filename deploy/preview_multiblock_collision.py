#!/usr/bin/env python3
"""Render world-space multiblock geometry, block cells and per-cell collision boxes."""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
from item_icon_preview import _project_view, render_projected_icon
from item_icon_proxy import rotate_relative_to_vanilla_gui
from gui_measure import corners
from normalize_item_icons import resolve_texture


PALETTE = [
    (245, 76, 61, 235), (255, 169, 54, 235), (63, 192, 220, 235),
    (174, 100, 214, 235), (107, 198, 100, 235), (238, 95, 161, 235),
]
SELECTION_COLOR = (53, 220, 238, 235)
PHYSICAL_COLOR = (255, 83, 65, 245)
GRID_COLOR = (82, 91, 95, 115)


def _project(point, view):
    return _project_view(rotate_relative_to_vanilla_gui(point, (30.0, 225.0, 0.0)), view)[0]


def _bounds(points):
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def _edge_pairs():
    corners8 = list(range(8))
    return [(a, b) for a in corners8 for b in corners8 if a < b and bin(a ^ b).count("1") == 1]


def _box_corners(box):
    return [(x, y, z) for x in (box[0], box[3])
            for y in (box[1], box[4]) for z in (box[2], box[5])]


def _draw_line(draw, p0, p1, view, offset, ppu, canvas_size, color, width=1):
    a, b = _project(p0, view), _project(p1, view)
    points = [(canvas_size / 2 + (p[0] + offset[0]) * ppu,
               canvas_size / 2 + (p[1] + offset[1]) * ppu) for p in (a, b)]
    draw.line(points, fill=color, width=width)


def _draw_wire_box(draw, box, view, offset, ppu, canvas_size, color):
    points = _box_corners(box)
    for a, b in _edge_pairs():
        _draw_line(draw, points[a], points[b], view, offset, ppu, canvas_size, color, 1)


def render(model: dict, report: dict, root: Path, output: Path, cell_size: int = 320):
    selection_cells = report.get("selection_boxes", report.get("cell_boxes", {}))
    physical_cells = report.get("collision_boxes", report.get("cell_boxes", {}))
    model_points = corners(model)
    views = (("isometric", "Iso"), ("front", "Front"), ("side", "Side"), ("top", "Top"))
    label_h = 24
    sheet = Image.new("RGBA", (cell_size * 2, (cell_size + label_h) * 2), (39, 39, 39, 255))
    font_path = Path("C:/Windows/Fonts/msyh.ttc")
    label_font = ImageFont.truetype(str(font_path), 13) if font_path.exists() else ImageFont.load_default()

    for index, (view, title) in enumerate(views):
        sx, sy = (index % 2) * cell_size, (index // 2) * (cell_size + label_h)
        viewport = Image.new("RGBA", (cell_size, cell_size), (87, 87, 87, 255))
        draw = ImageDraw.Draw(viewport, "RGBA")
        projected_model = [_project(point, view) for point in model_points]
        b = _bounds(projected_model)
        extent_x, extent_y = max(1.0, b[2] - b[0]), max(1.0, b[3] - b[1])
        ppu = min((cell_size - 44) / extent_x, (cell_size - 44) / extent_y)
        center = ((b[0] + b[2]) * 0.5, (b[1] + b[3]) * 0.5)
        offset = (-center[0], -center[1])
        model_sprite = render_projected_icon(model, lambda ref: resolve_texture(root, ref),
                                             (1.0, 1.0, 1.0), (30.0, 225.0, 0.0),
                                             size=cell_size, view=view,
                                             projection_offset=offset, pixels_per_unit=ppu)
        viewport.alpha_composite(model_sprite)
        draw = ImageDraw.Draw(viewport, "RGBA")

        # Draw block-cell wireframes through the visible model bounds.
        cell_x = [-16.0, 0.0, 16.0, 32.0]
        cell_y = [0.0, 16.0, 32.0, 48.0]
        cell_z = [-16.0, 0.0, 16.0, 32.0]
        for y in cell_y:
            for z in cell_z:
                _draw_line(draw, (cell_x[0], y, z), (cell_x[-1], y, z), view, offset, ppu, cell_size, GRID_COLOR)
        for x in cell_x:
            for z in cell_z:
                _draw_line(draw, (x, cell_y[0], z), (x, cell_y[-1], z), view, offset, ppu, cell_size, GRID_COLOR)
        for x in cell_x:
            for y in cell_y:
                _draw_line(draw, (x, y, cell_z[0]), (x, y, cell_z[-1]), view, offset, ppu, cell_size, GRID_COLOR)

        for key, boxes in selection_cells.items():
            layer_s, column_s, row_s = key.split(",")
            layer, column, row = int(layer_s), int(column_s), int(row_s)
            origin = ((column - 1) * 16.0, layer * 16.0, (row - 1) * 16.0)
            for local in boxes:
                world = (local[0] + origin[0], local[1] + origin[1], local[2] + origin[2],
                         local[3] + origin[0], local[4] + origin[1], local[5] + origin[2])
                _draw_wire_box(draw, world, view, offset, ppu, cell_size, SELECTION_COLOR)

        # Physical collision is drawn last so a divergence from the selectable
        # outline stays visible in the local preview rather than merging into
        # one ambiguous red union.
        for key, boxes in physical_cells.items():
            layer_s, column_s, row_s = key.split(",")
            layer, column, row = int(layer_s), int(column_s), int(row_s)
            origin = ((column - 1) * 16.0, layer * 16.0, (row - 1) * 16.0)
            for local in boxes:
                world = (local[0] + origin[0], local[1] + origin[1], local[2] + origin[2],
                         local[3] + origin[0], local[4] + origin[1], local[5] + origin[2])
                _draw_wire_box(draw, world, view, offset, ppu, cell_size, PHYSICAL_COLOR)

        sheet.alpha_composite(viewport, (sx, sy))
        panel_label = Image.new("RGBA", (cell_size, label_h), (25, 25, 25, 255))
        label_draw = ImageDraw.Draw(panel_label)
        label_draw.text((8, 4), f"{title}  |  cyan selection · red physical collision", fill="white", font=label_font)
        sheet.alpha_composite(panel_label, (sx, sy + cell_size))

    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cell-size", type=int, default=320)
    args = parser.parse_args()
    model = json.loads(args.model.read_text(encoding="utf-8"))
    report = json.loads(args.report.read_text(encoding="utf-8"))
    render(model, report, ROOT, args.output, args.cell_size)
    print(f"Rendered per-cell multiblock collision preview to {args.output}")


if __name__ == "__main__":
    main()
