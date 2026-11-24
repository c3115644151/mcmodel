#!/usr/bin/env python3
"""Render four-view, texture-aware previews of Blockbench Java block models."""
from __future__ import annotations

import argparse
import base64
import copy
import json
import sys
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from gui_measure import corners
from item_icon_preview import _project_view, render_projected_icon
from item_icon_proxy import geometry_bounds


VIEWS = (("前上方透视", "perspective_front"), ("正面", "front"),
         ("侧面", "side"), ("顶面", "top"))
FACE_NAMES = {"north", "east", "south", "west", "up", "down"}


def load_project(path: Path, texture_root: Path) -> tuple[dict, dict, dict]:
    source = json.loads(path.read_text(encoding="utf-8"))
    if source.get("meta", {}).get("model_format") != "java_block":
        raise ValueError(f"{path.name}: expected Blockbench java_block format")

    resolution = source.get("resolution", {})
    width = float(resolution.get("width", 16))
    height = float(resolution.get("height", width))
    textures: dict[int, Path] = {}
    texture_names: dict[int, str] = {}
    for index, entry in enumerate(source.get("textures", [])):
        raw = entry.get("source", "")
        if raw.startswith("data:") and "," in raw:
            raw = raw.split(",", 1)[1]
        if not raw:
            continue
        image = Image.open(BytesIO(base64.b64decode(raw))).convert("RGBA")
        output = texture_root / f"texture_{index}.png"
        output.parent.mkdir(parents=True, exist_ok=True)
        image.save(output)
        textures[index] = output
        texture_names[index] = entry.get("name", f"texture_{index}")

    model = {"textures": {}, "elements": []}
    all_elements = []
    for index, path_out in textures.items():
        reference = f"preview:texture_{index}"
        model["textures"][f"bb_{index}"] = reference
    hidden_outliner_ids: set[str] = set()
    element_by_id = {element.get("uuid"): element for element in source.get("elements", [])}
    group_by_id = {group.get("uuid"): group for group in source.get("groups", []) or []}

    def collect_hidden(nodes, parent_visible=True):
        for node in nodes or []:
            if isinstance(node, str):
                element = element_by_id.get(node)
                if element is not None and (not parent_visible or element.get("visibility", True) is False):
                    hidden_outliner_ids.add(node)
            elif isinstance(node, dict):
                group = group_by_id.get(node.get("uuid"), node)
                visible = parent_visible and node.get("visibility", group.get("visibility", True)) is not False
                collect_hidden(node.get("children", []), visible)

    collect_hidden(source.get("outliner", []))
    hidden_indices = []
    group_transform_warnings = []
    for group in source.get("groups", []) or []:
        if any(abs(float(angle)) > 1e-6 for angle in group.get("rotation", [0, 0, 0])):
            group_transform_warnings.append({"name": group.get("name", ""), "rotation": group.get("rotation")})

    for index, element in enumerate(source.get("elements", [])):
        converted = {
            "from": copy.deepcopy(element["from"]),
            "to": copy.deepcopy(element["to"]),
            "faces": {},
        }
        if element.get("rotation"):
            converted["rotation"] = copy.deepcopy(element["rotation"])
            converted["origin"] = copy.deepcopy(element.get("origin", [8, 8, 8]))
        elif element.get("origin"):
            converted["origin"] = copy.deepcopy(element["origin"])
        for face_name, face in element.get("faces", {}).items():
            if face_name not in FACE_NAMES or face.get("texture") is None:
                continue
            texture_index = face.get("texture", 0)
            if isinstance(texture_index, str):
                texture_index = int(texture_index.lstrip("#")) if texture_index.lstrip("#").isdigit() else 0
            texture_index = int(texture_index)
            if texture_index not in textures:
                continue
            uv = face.get("uv")
            if not uv or len(uv) != 4:
                continue
            converted_face = {
                "uv": [float(uv[0]) * 16.0 / width, float(uv[1]) * 16.0 / height,
                       float(uv[2]) * 16.0 / width, float(uv[3]) * 16.0 / height],
                "texture": f"#bb_{texture_index}",
            }
            if face.get("rotation"):
                converted_face["rotation"] = face["rotation"]
            converted["faces"][face_name] = converted_face
        all_elements.append(converted)
        element_visible = element.get("visibility", True) is not False
        element_visible &= element.get("uuid") not in hidden_outliner_ids
        if not element_visible or not converted["faces"]:
            hidden_indices.append(index)
            continue
        model["elements"].append(converted)

    report = inspect_source(source, model, textures, all_elements, hidden_indices, group_transform_warnings)
    return model, {f"preview:texture_{i}": p for i, p in textures.items()}, report


def inspect_source(source: dict, model: dict, textures: dict[int, Path], all_elements: list[dict],
                   hidden_indices: list[int], group_transform_warnings: list[dict]) -> dict:
    bounds = geometry_bounds(model)
    authored_bounds = geometry_bounds({**model, "elements": all_elements})
    rotations = []
    reversed_axes = 0
    zero_axes = 0
    textured_faces = 0
    for i, element in enumerate(source.get("elements", [])):
        low, high = element["from"], element["to"]
        reversed_axes += sum(float(high[a]) < float(low[a]) for a in range(3))
        zero_axes += sum(abs(float(high[a]) - float(low[a])) < 1e-6 for a in range(3))
        rotation = element.get("rotation")
        if rotation and any(abs(float(value)) > 1e-6 for value in rotation):
            rotations.append({"index": i, "rotation": rotation, "origin": element.get("origin", [8, 8, 8])})
        textured_faces += sum(face.get("texture") is not None for face in element.get("faces", {}).values())
    groups = []
    for group in source.get("groups", []):
        groups.append({
            "name": group.get("name", ""), "rotation": group.get("rotation", [0, 0, 0]),
            "origin": group.get("origin"), "children": len(group.get("children", [])),
            "visible": group.get("visibility", True),
        })
    spans = [round(float(bounds[i + 3]) - float(bounds[i]), 3) for i in range(3)] if bounds else None
    return {
        "format": source.get("meta", {}).get("model_format"),
        "resolution": source.get("resolution"),
        "elements": len(model.get("elements", [])),
        "textures": len(textures),
        "bounds": [[round(float(v), 3) for v in bounds[:3]],
                   [round(float(v), 3) for v in bounds[3:]]] if bounds else None,
        "spans": spans,
        "authored_bounds_including_hidden": [[round(float(v), 3) for v in authored_bounds[:3]],
                                               [round(float(v), 3) for v in authored_bounds[3:]]]
        if authored_bounds else None,
        "hidden_or_nonrendering_element_indices": hidden_indices,
        "unsupported_group_transforms": group_transform_warnings,
        "zero_thickness_axes": zero_axes,
        "reversed_axes": reversed_axes,
        "rotated_elements": rotations,
        "groups": groups,
        "textured_faces": textured_faces,
    }


def font(size: int):
    for path in (Path("C:/Windows/Fonts/msyh.ttc"), Path("C:/Windows/Fonts/arial.ttf")):
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def center_model_without_scaling(model: dict) -> dict:
    """Translate the visible model to the preview origin while preserving its units and UV scale."""
    bounds = geometry_bounds(model)
    if bounds is None:
        return model
    offset = (8.0 - (bounds[0] + bounds[3]) * 0.5,
              8.0 - (bounds[1] + bounds[4]) * 0.5,
              8.0 - (bounds[2] + bounds[5]) * 0.5)
    centered = copy.deepcopy(model)
    for element in centered.get("elements", []):
        for key in ("from", "to", "origin"):
            if key in element:
                element[key] = [float(element[key][axis]) + offset[axis] for axis in range(3)]
    return centered


def fit_view(model: dict, view: str, panel_size: int) -> tuple[float, tuple[float, float], float]:
    bounds = geometry_bounds(model)
    spans = [bounds[axis + 3] - bounds[axis] for axis in range(3)]
    camera_distance = max(spans) * 2.5
    projected = [_project_view(point, view, camera_distance)[0] for point in corners(model)]
    min_x, max_x = min(p[0] for p in projected), max(p[0] for p in projected)
    min_y, max_y = min(p[1] for p in projected), max(p[1] for p in projected)
    width, height = max_x - min_x, max_y - min_y
    pixels_per_unit = (panel_size - 24) / max(width, height, 1e-6)
    offset = (-(min_x + max_x) * 0.5, -(min_y + max_y) * 0.5)
    return pixels_per_unit, offset, camera_distance


def make_preview(path: Path, output: Path, texture_root: Path, panel: int) -> dict:
    model, texture_paths, report = load_project(path, texture_root)
    if not model.get("elements"):
        raise ValueError(f"{path.name}: no renderable geometry")
    preview_model = center_model_without_scaling(model)

    header_h = 54
    label_h = 22
    gap = 8
    sheet = Image.new("RGBA", (panel * 2 + gap * 3, header_h + panel * 2 + gap * 3 + label_h * 2),
                      (42, 45, 48, 255))
    draw = ImageDraw.Draw(sheet)
    title = path.stem
    span_text = " × ".join(str(value) for value in report["spans"] or [])
    draw.text((gap, 5), f"{title}  |  visible bounds: {span_text}", fill=(250, 250, 250, 255), font=font(20))
    draw.text((gap, 31), f"{report['elements']} visible cubes · {report['textures']} textures · source geometry and UV scale retained",
              fill=(195, 202, 210, 255), font=font(13))

    texture_resolver = lambda ref: texture_paths.get(ref)
    gui_scale = (1.0, 1.0, 1.0)
    # item_icon_preview applies only the yaw delta from the vanilla GUI camera.
    # Pass the reference rotation to request an unrotated world-space view; zero
    # would rotate the model by -225 degrees instead of disabling the transform.
    gui_rotation = (30.0, 225.0, 0.0)
    for index, (label, view) in enumerate(VIEWS):
        col, row = index % 2, index // 2
        x, y = gap + col * (panel + gap), header_h + gap + row * (panel + label_h + gap)
        draw.rectangle((x, y, x + panel, y + panel), fill=(94, 98, 102, 255), outline=(200, 205, 210, 255))
        pixels_per_unit, projection_offset, camera_distance = fit_view(preview_model, view, panel - 12)
        sprite = render_projected_icon(preview_model, texture_resolver, gui_scale, gui_rotation,
                                      size=panel - 12, view=view, pixels_per_unit=pixels_per_unit,
                                      projection_offset=projection_offset, camera_distance=camera_distance,
                                      depth_buffer=(view in ("perspective_front", "front")))
        sheet.alpha_composite(sprite, (x + 6, y + 6))
        draw.text((x + 4, y + panel + 3), label, fill=(242, 244, 246, 255), font=font(14))

    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)
    report["preview_geometry"] = "Only a common translation is applied. Source dimensions, rotations, and UV scale are preserved; each view adjusts camera zoom only."
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("build/bbmodel_review"))
    parser.add_argument("--panel", type=int, default=256)
    args = parser.parse_args()
    output_dir = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    reports = {}
    for path in args.files:
        textures_dir = output_dir / f"{path.stem}_textures"
        preview = output_dir / f"{path.stem}_four_view.png"
        reports[path.name] = make_preview(path, preview, textures_dir, args.panel)
        print(f"{path.name}: {preview}")
    report_path = output_dir / "model_audit.json"
    report_path.write_text(json.dumps(reports, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Audit report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
