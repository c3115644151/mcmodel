#!/usr/bin/env python3
"""Render item geometry with the current Java collision boxes overlaid in red.

This is a model-space QA view, not a Minecraft screenshot. It uses the same
source geometry normalization and GUI camera as the icon preview, so box/model
alignment can be inspected before loading the client.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "collision"))

from audit_java_shapes import read_shape
from item_icon_preview import render_projected_icon, _project_view
from item_icon_proxy import collect_model_ids, geometry_bounds, rotate_relative_to_vanilla_gui
from normalize_item_icons import load_model_with_parent, resolve_model, resolve_texture, source_model_id
from run import deploy_collision
from generate import merge_exact_union_boxes


MOD_ID = "pastoral_home"
ASSETS = ROOT / "src/main/resources/assets" / MOD_ID
PROFILE = ROOT / "tools/deploy/collision_profiles/recent_outdoor.json"
COLORS = ((255, 48, 62, 255), (255, 190, 55, 255), (55, 230, 255, 255))


def model_sources(item_id: str):
    item_path = ASSETS / f"items/{item_id}.json"
    item = json.loads(item_path.read_text(encoding="utf-8"))
    gui_case = next(case for case in item["model"].get("cases", []) if case.get("when") == "gui")
    model_ids = collect_model_ids(gui_case["model"])
    models = []
    for model_id in model_ids:
        path = resolve_model(model_id, ASSETS, MOD_ID)
        gui_model = load_model_with_parent(path, ASSETS, MOD_ID) if path else None
        source_id = source_model_id(model_id, ASSETS, MOD_ID)
        source_path = resolve_model(source_id, ASSETS, MOD_ID)
        source_model = load_model_with_parent(source_path, ASSETS, MOD_ID) if source_path else gui_model
        if gui_model and gui_model.get("elements") and source_model and source_model.get("elements"):
            models.append((model_id, gui_model, source_model))
    return models


def item_geometry_bounds(models):
    all_points = []
    for _model_id, _gui_model, source_model in models:
        bounds = geometry_bounds(source_model)
        if bounds:
            all_points.append(bounds)
    if not all_points:
        return None
    return (min(b[0] for b in all_points), min(b[1] for b in all_points), min(b[2] for b in all_points),
            max(b[3] for b in all_points), max(b[4] for b in all_points), max(b[5] for b in all_points))


def proxy_transform(bounds):
    minimum, maximum = bounds[:3], bounds[3:]
    span = [maximum[i] - minimum[i] for i in range(3)]
    largest = max(span)
    # Use a fixed world-space cell reference with a small margin. A model that
    # spans two blocks therefore renders twice as tall as a one-cell model.
    factor = min(1.0, 13.0 / largest) if largest else 1.0
    center_x = (minimum[0] + maximum[0]) / 2.0
    floor_y = minimum[1]
    center_z = (minimum[2] + maximum[2]) / 2.0

    def transform(point):
        return ((point[0] - center_x) * factor + 8.0,
                (point[1] - floor_y) * factor,
                (point[2] - center_z) * factor + 8.0)

    return transform


def transformed_world_model(model: dict, transform) -> dict:
    """Scale raw world geometry into preview coordinates, ignoring item GUI transforms."""
    result = copy.deepcopy(model)
    for element in result.get("elements", []):
        element["from"] = list(transform(element["from"]))
        element["to"] = list(transform(element["to"]))
        if element.get("origin"):
            element["origin"] = list(transform(element["origin"]))
    return result


def cell_grid_edges(transform, maximum_y: float):
    """Cell wireframes at y=0/16/32 make multi-block ownership visible."""
    top = max(16, int(math.ceil(maximum_y / 16.0) * 16))
    edges = set()
    for y in range(0, top, 16):
        x0, x1 = transform((0, y, 0))[0], transform((16, y, 0))[0]
        z0, z1 = transform((0, y, 0))[2], transform((0, y, 16))[2]
        low = min(x0, x1)
        high = max(x0, x1)
        near = min(z0, z1)
        far = max(z0, z1)
        corners = [(low, transform((0, y, 0))[1], near),
                   (high, transform((16, y, 0))[1], near),
                   (high, transform((16, y, 16))[1], far),
                   (low, transform((0, y, 16))[1], far),
                   (low, transform((0, y + 16, 0))[1], near),
                   (high, transform((16, y + 16, 0))[1], near),
                   (high, transform((16, y + 16, 16))[1], far),
                   (low, transform((0, y + 16, 16))[1], far)]
        for a, b in ((0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4),
                     (0, 4), (1, 5), (2, 6), (3, 7)):
            edges.add(tuple(sorted((corners[a], corners[b]))))
    return edges


def collision_layers(profile: dict, java_path: Path, candidate: bool = False):
    if profile["mode"] == "no_collision":
        return []
    if candidate and profile["mode"] == "single_block":
        generated = []
        for model_name in profile["models"]:
            result = deploy_collision(
                str(ASSETS / f"models/block/{model_name}"), res=4,
                include_indices=profile.get("include_indices"),
                collision_groups=profile.get("collision_groups"),
                single_block=True,
            )
            generated.extend(result["boxes"])
        return [("tool candidate", merge_exact_union_boxes(generated), COLORS[1], 0.0)]
    if profile["mode"] == "layers":
        if candidate:
            output = []
            for index, layer in enumerate(profile["layers"]):
                interval = tuple(layer["model_y"])
                groups = layer.get("collision_groups", profile.get("collision_groups"))
                generated = []
                for model_name in profile["models"]:
                    result = deploy_collision(
                        str(ASSETS / f"models/block/{model_name}"), res=4,
                        include_indices=profile.get("include_indices"),
                        collision_groups=groups,
                        clip_bounds={1: interval}, single_block=True,
                    )
                    generated.extend(result["boxes"])
                offset = float(layer["offset_y"])
                local = [(box[0], box[1] - offset, box[2], box[3], box[4] - offset, box[5])
                         for box in merge_exact_union_boxes(generated)]
                output.append((layer["shape"], local, COLORS[(index + 1) % len(COLORS)], offset))
            return output
        return [(layer["shape"], read_shape(java_path, layer["shape"]),
                 COLORS[index % len(COLORS)], float(layer["offset_y"]))
                for index, layer in enumerate(profile["layers"])]
    return [(profile["shape"], read_shape(java_path, profile["shape"]), COLORS[0], 0.0)]


def selection_layers(profile: dict, java_path: Path):
    """Use the physical shape for selection unless a profile declares an exception."""
    if profile.get("selection_layers"):
        return [(layer["shape"], read_shape(java_path, layer["shape"]), COLORS[1],
                 float(layer.get("offset_y", 0.0))) for layer in profile["selection_layers"]]
    selection_field = profile.get("selection_shape")
    if selection_field:
        return [(selection_field, read_shape(java_path, selection_field), COLORS[1], 0.0)]
    if profile["mode"] == "no_collision":
        return []
    return [(name, boxes, COLORS[1], offset)
            for name, boxes, _color, offset in collision_layers(profile, java_path)]


def box_corners(box):
    x0, y0, z0, x1, y1, z1 = box
    return [(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]


def union_boundary_edges(boxes):
    """Return only exposed edges of the box union, omitting internal box seams."""
    boxes = [tuple(float(value) for value in box) for box in boxes
             if all(float(box[axis + 3]) > float(box[axis]) for axis in range(3))]
    if not boxes:
        return set()
    coords = [sorted({round(box[index], 6) for box in boxes for index in (axis, axis + 3)})
              for axis in range(3)]
    occupied = set()
    for ix in range(len(coords[0]) - 1):
        for iy in range(len(coords[1]) - 1):
            for iz in range(len(coords[2]) - 1):
                center = ((coords[0][ix] + coords[0][ix + 1]) / 2,
                          (coords[1][iy] + coords[1][iy + 1]) / 2,
                          (coords[2][iz] + coords[2][iz + 1]) / 2)
                if any(box[0] <= center[0] <= box[3] and box[1] <= center[1] <= box[4]
                       and box[2] <= center[2] <= box[5] for box in boxes):
                    occupied.add((ix, iy, iz))

    # Each edge records the set of outward face normals around it. A shared
    # edge between coplanar faces has only one normal and is an internal seam.
    edge_normals = {}
    directions = ((-1, 0, 0, (-1, 0, 0)), (1, 0, 0, (1, 0, 0)),
                  (0, -1, 0, (0, -1, 0)), (0, 1, 0, (0, 1, 0)),
                  (0, 0, -1, (0, 0, -1)), (0, 0, 1, (0, 0, 1)))
    for cell in occupied:
        ix, iy, iz = cell
        for dx, dy, dz, normal in directions:
            neighbor = (ix + dx, iy + dy, iz + dz)
            if neighbor in occupied:
                continue
            if dx:
                x = coords[0][ix if dx < 0 else ix + 1]
                corners = [(x, coords[1][iy], coords[2][iz]),
                           (x, coords[1][iy + 1], coords[2][iz]),
                           (x, coords[1][iy + 1], coords[2][iz + 1]),
                           (x, coords[1][iy], coords[2][iz + 1])]
            elif dy:
                y = coords[1][iy if dy < 0 else iy + 1]
                corners = [(coords[0][ix], y, coords[2][iz]),
                           (coords[0][ix + 1], y, coords[2][iz]),
                           (coords[0][ix + 1], y, coords[2][iz + 1]),
                           (coords[0][ix], y, coords[2][iz + 1])]
            else:
                z = coords[2][iz if dz < 0 else iz + 1]
                corners = [(coords[0][ix], coords[1][iy], z),
                           (coords[0][ix + 1], coords[1][iy], z),
                           (coords[0][ix + 1], coords[1][iy + 1], z),
                           (coords[0][ix], coords[1][iy + 1], z)]
            for index in range(4):
                a, b = corners[index], corners[(index + 1) % 4]
                edge = tuple(sorted((a, b)))
                edge_normals.setdefault(edge, set()).add(normal)
    runs = {}
    for edge, normals in edge_normals.items():
        if len(normals) <= 1:
            continue
        first, second = edge
        axis = next((i for i in range(3) if abs(first[i] - second[i]) > 1e-8), None)
        if axis is None:
            continue
        fixed = tuple(round(first[i], 6) for i in range(3) if i != axis)
        key = (axis, fixed, tuple(sorted(normals)))
        runs.setdefault(key, []).append((min(first[axis], second[axis]), max(first[axis], second[axis])))

    merged_edges = set()
    for (axis, fixed, normals), intervals in runs.items():
        intervals.sort()
        merged = []
        for low, high in intervals:
            if merged and low <= merged[-1][1] + 1e-6:
                merged[-1] = (merged[-1][0], max(merged[-1][1], high))
            else:
                merged.append((low, high))
        fixed_index = [index for index in range(3) if index != axis]
        for low, high in merged:
            a = [0.0, 0.0, 0.0]
            b = [0.0, 0.0, 0.0]
            a[axis], b[axis] = low, high
            a[fixed_index[0]] = b[fixed_index[0]] = fixed[0]
            a[fixed_index[1]] = b[fixed_index[1]] = fixed[1]
            merged_edges.add(tuple(sorted((tuple(a), tuple(b)))))
    return merged_edges


def project_point(point, transform, rotation, scale, origin, size, view):
    normalized = transform(point)
    camera = rotate_relative_to_vanilla_gui(normalized, rotation)
    scaled = tuple(8.0 + (camera[i] - 8.0) * scale[i] for i in range(3))
    (x, y), _depth = _project_view(scaled, view)
    return (origin[0] + size / 2 + x * size / 16.0,
            origin[1] + size / 2 + y * size / 16.0)


def render_item(item_id: str, profile: dict, cell_size: int, candidate: bool = False):
    models = model_sources(profile.get("item_id", item_id))
    bounds = item_geometry_bounds(models)
    if bounds is None:
        raise ValueError(f"{item_id}: GUI item has no source geometry")
    transform = proxy_transform(bounds)
    world_models = [transformed_world_model(source_model, transform)
                    for _model_id, _gui_model, source_model in models]
    # The unrotated model is fitted to 13/16 of a cell. An additional common
    # camera scale keeps diagonal views and tall models inside the preview tile.
    world_scale = (0.72, 0.72, 0.72)
    resolver = lambda ref: resolve_texture(ROOT, ref)
    java_path = ROOT / profile["java"]
    layers = collision_layers(profile, java_path, candidate)
    selectors = selection_layers(profile, java_path)
    box_count = sum(len(entry[1]) for entry in layers)
    def combine_layers(shapes):
        all_boxes = []
        for _shape_name, boxes, _color, y_offset in shapes:
            all_boxes.extend(tuple(box[i] + (y_offset if i in (1, 4) else 0.0)
                                   for i in range(6)) for box in boxes)
        return all_boxes

    collision_edges = union_boundary_edges(combine_layers(layers))
    selection_edges = union_boundary_edges(combine_layers(selectors))
    selection_count = sum(len(entry[1]) for entry in selectors)
    views = {
        "isometric": (30.0, 45.0, 0.0),
        "front": (0.0, 0.0, 0.0),
        "side": (0.0, 90.0, 0.0),
        "top": (90.0, 0.0, 0.0),
    }
    maximum_y = max(bounds[4], 16.0)
    grid_edges = cell_grid_edges(transform, maximum_y)
    sprites = {}
    for view, rotation in views.items():
        grid = Image.new("RGBA", (cell_size, cell_size), (0, 0, 0, 0))
        grid_draw = ImageDraw.Draw(grid, "RGBA")
        for edge in grid_edges:
            screen = [project_point(point, transform, rotation, world_scale, (0, 0), cell_size, view)
                      for point in edge]
            grid_draw.line(screen, fill=(200, 200, 200, 100), width=1)
        sprite = grid
        for model in world_models:
            layer = render_projected_icon(model, resolver, world_scale, rotation,
                                          size=cell_size, view=view)
            sprite = Image.alpha_composite(sprite, layer)
        shape_overlay = Image.new("RGBA", (cell_size, cell_size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(shape_overlay, "RGBA")
        for edge in selection_edges:
            screen = [project_point(point, transform, rotation, world_scale, (0, 0), cell_size, view)
                      for point in edge]
            draw.line(screen, fill=COLORS[1], width=2)
        for edge in collision_edges:
            screen = [project_point(point, transform, rotation, world_scale, (0, 0), cell_size, view)
                      for point in edge]
            draw.line(screen, fill=COLORS[0], width=2)
        # Put textured geometry back over the wireframe. This coarse painter's
        # depth approximation prevents rear colliders from drawing across foliage.
        sprite = Image.alpha_composite(shape_overlay, sprite)
        sprites[view] = sprite
    return sprites, box_count, selection_count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--items", default="", help="comma-separated profile IDs; default is all recent models")
    parser.add_argument("--profile", type=Path, default=PROFILE,
                        help="collision profile JSON; may describe an experimental grouping")
    parser.add_argument("--candidate", action="store_true",
                        help="show grouped collision boxes generated by the collision tool")
    parser.add_argument("--output", type=Path, default=Path("build/recent_outdoor_collision_preview.png"))
    parser.add_argument("--cell", type=int, default=144)
    args = parser.parse_args()

    profile_path = args.profile if args.profile.is_absolute() else ROOT / args.profile
    profiles = json.loads(profile_path.read_text(encoding="utf-8"))["profiles"]
    requested = {value.strip() for value in args.items.split(",") if value.strip()}
    if requested:
        profiles = [profile for profile in profiles if profile["id"] in requested]
    view_names = ("isometric", "front", "side", "top")
    columns = len(view_names)
    label_height = 22
    row_height = args.cell + label_height
    sheet = Image.new("RGBA", (columns * args.cell, len(profiles) * row_height), (48, 48, 48, 255))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    metadata = []
    for index, profile in enumerate(profiles):
        sprites, box_count, selection_count = render_item(profile["id"], profile, args.cell, args.candidate)
        y = index * row_height
        for column, view in enumerate(view_names):
            x = column * args.cell
            draw.rectangle((x + 1, y + 1, x + args.cell - 2, y + args.cell - 2),
                           fill=(80, 80, 80, 255), outline=(170, 170, 170, 255))
            sheet.alpha_composite(sprites[view], (x, y))
            if index == 0:
                draw.text((x + 4, 3), view, fill=(225, 225, 225, 255), font=font)
        text = "NO COLLISION" if profile["mode"] == "no_collision" else f"{box_count} boxes"
        draw.text((4, y + args.cell + 3), f"{profile['id']} | {text}", fill=(255, 255, 255, 255), font=font)
        legend = "yellow=tool candidate" if args.candidate else "red=collision; yellow=selection; gray=block cells"
        draw.text((220, y + args.cell + 3), legend, fill=(235, 190, 160, 255), font=font)
        metadata.append({"item": profile["id"], "collision_boxes": box_count,
                         "selection_boxes": selection_count,
                         "mode": profile["mode"],
                         "views": list(view_names)})

    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)
    output.with_suffix(".json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
                                             encoding="utf-8")
    print(f"Rendered collision overlays for {len(metadata)} models -> {output}")


if __name__ == "__main__":
    main()
