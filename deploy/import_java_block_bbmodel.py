#!/usr/bin/env python3
"""Import a Java-block .bbmodel's native cube geometry/UVs and embedded texture.

This intentionally handles only the simple java_block format used by the bridge
deck: axis-aligned cubes, one or more embedded textures, and per-face UV bounds.
It writes the unassembled source model outside runtime resources so the split /
placement tool can derive game variants without losing the artist's full model.
"""

from __future__ import annotations

import argparse
import base64
from io import BytesIO
import json
from pathlib import Path
from PIL import Image


def create_particle_tile(image_bytes: bytes, model_data: dict, texture_index: int = 0) -> Image.Image:
    """Extract the largest art-authored face, not the entire packed UV atlas."""
    image = Image.open(BytesIO(image_bytes)).convert("RGBA")
    resolution = model_data.get("resolution", {})
    source_width = float(resolution.get("width", image.width))
    source_height = float(resolution.get("height", image.height))
    largest = None
    face_priority = {"south": 6, "east": 5, "west": 4, "north": 3, "up": 2, "down": 1}
    for element in model_data.get("elements", []):
        for face_name, face in element.get("faces", {}).items():
            if face.get("texture") != texture_index:
                continue
            uv = face.get("uv")
            if not isinstance(uv, list) or len(uv) != 4:
                continue
            area = abs(float(uv[2]) - float(uv[0])) * abs(float(uv[3]) - float(uv[1]))
            score = (area, face_priority.get(face_name, 0))
            if area > 0 and (largest is None or score > largest[0]):
                largest = (score, uv)

    if largest is None:
        crop = image
    else:
        uv = largest[1]
        x0 = round(min(float(uv[0]), float(uv[2])) * image.width / source_width)
        x1 = round(max(float(uv[0]), float(uv[2])) * image.width / source_width)
        y0 = round(min(float(uv[1]), float(uv[3])) * image.height / source_height)
        y1 = round(max(float(uv[1]), float(uv[3])) * image.height / source_height)
        x0, x1 = max(0, x0), min(image.width, x1)
        y0, y1 = max(0, y0), min(image.height, y1)
        crop = image.crop((x0, y0, x1, y1)) if x1 > x0 and y1 > y0 else image
    return crop.resize((16, 16), Image.Resampling.NEAREST)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--model-out", type=Path, required=True)
    parser.add_argument("--texture-out", type=Path, required=True)
    parser.add_argument("--parts-out", type=Path,
                        help="Optional grouped-part manifest output (bridge-specific; omit for ordinary models)")
    parser.add_argument("--mod-id", default="pastoral_home")
    parser.add_argument("--texture-name", default="bridge_deck")
    parser.add_argument("--texture-dir", type=Path,
                        help="Directory for additional embedded textures; enables safe multi-texture import")
    parser.add_argument("--texture-prefix", default=None,
                        help="Filename prefix for additional textures; defaults to --texture-name")
    args = parser.parse_args()

    data = json.loads(args.source.read_text(encoding="utf-8"))
    if data.get("meta", {}).get("model_format") != "java_block":
        raise SystemExit("Source Blockbench model is not java_block format")
    resolution = data.get("resolution", {})
    width = float(resolution.get("width", 16))
    height = float(resolution.get("height", width))
    if width <= 0 or height <= 0:
        raise SystemExit("Invalid texture resolution")

    textures = data.get("textures", [])
    if not textures or any(not texture.get("source") for texture in textures):
        raise SystemExit("Every referenced texture must have an embedded source")
    if len(textures) > 1 and args.texture_dir is None:
        raise SystemExit("This model has multiple embedded textures; pass --texture-dir to avoid merging them")
    texture_prefix = args.texture_prefix or args.texture_name
    texture_ids = {
        i: (args.texture_name if i == 0 else f"{texture_prefix}_tex{i}")
        for i in range(len(textures))
    }

    model = {
        "parent": "minecraft:block/block",
        # Preserve artist intent; the import tool and global pipeline both
        # leave vanilla AO and element shading enabled by default.
        "ambientocclusion": bool(data.get("ambientocclusion", True)),
        "textures": {f"bb_texture_{i}": f"{args.mod_id}:block/{texture_ids[i]}"
                     for i in range(len(textures))},
        "elements": [],
    }
    # Display transforms are authored separately from world geometry but are
    # essential for held and GUI item views. Keep the complete Blockbench
    # transform table in the Java model JSON instead of silently dropping it.
    display = data.get("display")
    if isinstance(display, dict):
        model["display"] = display
    particle_name = f"{texture_ids[0]}_particle"
    model["textures"]["particle"] = f"{args.mod_id}:block/{particle_name}"
    for index, element in enumerate(data.get("elements", [])):
        if element.get("type", "cube") not in ("cube", None):
            raise SystemExit(f"Unsupported element type at index {index}: {element.get('type')}")
        # Blockbench's inflate is a real geometric offset. Dropping it makes
        # intentionally inset/outset shell layers become coplanar duplicates
        # in Minecraft, which produces texture flicker on layered garments.
        inflate = float(element.get("inflate", 0.0) or 0.0)
        source_from = list(element["from"])
        source_to = list(element["to"])
        if abs(inflate) > 1.0e-9:
            for axis, (low, high) in enumerate(zip(source_from, source_to)):
                direction = 1.0 if float(high) >= float(low) else -1.0
                source_from[axis] = float(low) - direction * inflate
                source_to[axis] = float(high) + direction * inflate
        converted = {
            # Keep Blockbench's original direction. Reversed axes are accepted
            # by the vanilla cuboid baker and can carry intentional UV winding.
            "from": source_from,
            "to": source_to,
            "faces": {},
        }
        if "shade" in element:
            converted["shade"] = bool(element["shade"])
        rotation = element.get("rotation")
        if rotation:
            if not isinstance(rotation, list) or len(rotation) != 3:
                raise SystemExit(f"Unsupported rotation at element {index}: {rotation!r}")
            nonzero_axes = [axis for axis, angle in zip("xyz", rotation) if abs(float(angle)) > 1.0e-6]
            if len(nonzero_axes) > 1:
                raise SystemExit(f"Minecraft cube rotation supports one axis; element {index} rotates {rotation!r}")
            if nonzero_axes:
                converted["rotation"] = {
                    "origin": element.get("origin", [8, 8, 8]),
                    "axis": nonzero_axes[0],
                    "angle": float(rotation["xyz".index(nonzero_axes[0])]),
                }
                if element.get("rescale"):
                    converted["rotation"]["rescale"] = True
        for face_name, face in element.get("faces", {}).items():
            uv = face.get("uv")
            if uv is None or len(uv) != 4:
                continue
            texture_index = face.get("texture", 0)
            # Blockbench stores untextured/disabled faces as texture=null (often
            # with a zero-area UV rectangle). They must not be rebound to tex0.
            if texture_index is None:
                continue
            if isinstance(texture_index, str) and texture_index.startswith("#"):
                texture_key = f"bb_texture_{texture_index[1:]}"
            else:
                texture_key = f"bb_texture_{int(texture_index)}"
            out_face = {
                "uv": [uv[0] * 16.0 / width, uv[1] * 16.0 / height,
                       uv[2] * 16.0 / width, uv[3] * 16.0 / height],
                "texture": f"#{texture_key}",
            }
            if face.get("rotation"):
                out_face["rotation"] = face["rotation"]
            if face.get("cullface"):
                out_face["cullface"] = face["cullface"]
            converted["faces"][face_name] = out_face
        model["elements"].append(converted)

    if args.parts_out:
        # Preserve and classify explicitly grouped bridge parts only when asked.
        # Ordinary models with flat outliners are imported without bridge rules.
        element_by_uuid = {element.get("uuid"): i for i, element in enumerate(data.get("elements", []))}
        group_by_uuid = {group.get("uuid"): group for group in data.get("groups", []) or []}
        lane_names = {"下": 0, "中": 1, "上": 2}
        groups = []
        for outline_group in data.get("outliner", []):
            if not isinstance(outline_group, dict):
                continue
            group = group_by_uuid.get(outline_group.get("uuid"), outline_group)
            group_name = group.get("name", "")
            lane = next((index for key, index in lane_names.items() if key in group_name), None)
            if lane is None:
                continue
            parts = {}
            for uuid in outline_group.get("children", []):
                index = element_by_uuid.get(uuid)
                if index is None:
                    continue
                element = data["elements"][index]
                x0, x1 = float(element["from"][0]), float(element["to"][0])
                if abs(x0) < 0.001 and abs(x1 - 16.0) < 0.001:
                    parts["base"] = index
                    continue
                if x1 <= 0.001:
                    side, role = "west", "connector"
                elif x0 >= 15.999:
                    side, role = "east", "connector"
                elif abs(x1 - 3.0) < 0.001 and abs(x0) < 0.001:
                    side, role = "west", "edge"
                elif abs(x0 - 13.0) < 0.001 and abs(x1 - 16.0) < 0.001:
                    side, role = "east", "edge"
                else:
                    raise SystemExit(f"Unexpected cube bounds in group {group_name!r}: {x0}..{x1}")
                part_key = {"edge": "edges", "connector": "connectors"}[role]
                parts.setdefault(part_key, {})[side] = index
            if set(parts.get("edges", {})) != {"west", "east"} \
                    or set(parts.get("connectors", {})) != {"west", "east"} or "base" not in parts:
                raise SystemExit(f"Group {group_name!r} must contain base + both edges + both connectors")
            groups.append({"name": group_name, "lane": lane, **parts})
        if {group["lane"] for group in groups} != {0, 1, 2}:
            raise SystemExit("Expected the model groups 板（下）/板（中）/板（上）")

    args.model_out.parent.mkdir(parents=True, exist_ok=True)
    args.texture_out.parent.mkdir(parents=True, exist_ok=True)
    args.model_out.write_text(json.dumps(model, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    exported = []
    for index, texture_data in enumerate(textures):
        image_source = texture_data["source"]
        if "," in image_source and image_source.startswith("data:"):
            image_source = image_source.split(",", 1)[1]
        image = base64.b64decode(image_source)
        output = args.texture_out if index == 0 else (args.texture_dir / f"{texture_prefix}_tex{index}.png")
        if index > 0 and args.texture_dir is None:
            continue
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(image)
        if index == 0:
            particle_output = output.with_name(f"{output.stem}_particle.png")
            create_particle_tile(image, data, index).save(particle_output)
            exported.append(str(particle_output))
        exported.append(str(output))
    if args.parts_out:
        args.parts_out.parent.mkdir(parents=True, exist_ok=True)
        args.parts_out.write_text(json.dumps({"lanes": sorted(groups, key=lambda entry: entry["lane"])},
                                              indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Imported {len(model['elements'])} cubes and {len(exported)} textures -> {', '.join(exported)}")


if __name__ == "__main__":
    main()
