#!/usr/bin/env python3
"""Compare one Java VoxelShape field with an exported Minecraft model JSON.

Example:
  python tools/collision/audit_java_shapes.py model.json FurnitureBlock.java --shape SHAPE
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from parse_model import load_cubes, cube_aabb, filter_collision_cubes
from run import measure_collision


BOX_RE = re.compile(r"\bbox\(\s*([^)]*?)\s*\)")


def read_shape(java_file: Path, field: str):
    source = java_file.read_text(encoding="utf-8")
    # Ignore semicolons inside explanatory comments when locating the field body.
    source = re.sub(r"/\*.*?\*/|//[^\n]*", "", source, flags=re.DOTALL)
    declaration = re.compile(
        rf"(?:VoxelShape)\s+{re.escape(field)}\s*=\s*(.*?);", re.DOTALL
    )
    match = declaration.search(source)
    if not match:
        raise SystemExit(f"No VoxelShape field named {field!r} in {java_file}")
    boxes = []
    for found in BOX_RE.finditer(match.group(1)):
        try:
            values = tuple(float(value.strip()) for value in found.group(1).split(","))
        except ValueError as exc:
            raise SystemExit(f"Non-numeric box in {field}: {found.group(0)}") from exc
        if len(values) != 6:
            raise SystemExit(f"Expected six coordinates in {field}: {found.group(0)}")
        boxes.append(values)
    if not boxes:
        raise SystemExit(f"No box(...) calls found in shape {field!r}")
    return boxes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", type=Path)
    parser.add_argument("java", type=Path)
    parser.add_argument("--shape", required=True, help="static VoxelShape field name")
    parser.add_argument("--res", type=int, default=16)
    parser.add_argument("--include-indices", default=None,
                        help="comma-separated source element indices to include (e.g. only a planter base)")
    parser.add_argument("--exclude-indices", default="",
                        help="comma-separated source element indices to ignore")
    parser.add_argument("--model-y-range", default=None,
                        help="optional source-space layer interval, e.g. 0:16 or 16:32 for a multiblock part")
    parser.add_argument("--model-y-offset", type=float, default=0.0,
                        help="subtract this source Y from the selected model layer before comparing local boxes")
    parser.add_argument("--include-thin", action="store_true",
                        help="include planar visual elements; omitted by default like the deployment tool")
    args = parser.parse_args()

    boxes = read_shape(args.java, args.shape)
    degenerate = sum(any(box[axis + 3] <= box[axis] for axis in range(3)) for box in boxes)
    cubes = load_cubes(str(args.model))
    include = None if args.include_indices is None else {
        int(value.strip()) for value in args.include_indices.split(",") if value.strip()
    }
    exclude = {int(value.strip()) for value in args.exclude_indices.split(",") if value.strip()}
    cubes = [cube for cube in cubes if cube.get("index") not in exclude
             and (include is None or cube.get("index") in include)]
    cubes, skipped = filter_collision_cubes(cubes, include_thin=args.include_thin)
    if args.model_y_range:
        low, high = (float(value) for value in args.model_y_range.split(":"))
        clipped = []
        for cube in cubes:
            x0, y0, z0, x1, y1, z1 = cube_aabb(cube)
            y0, y1 = max(y0, low), min(y1, high)
            if y1 <= y0:
                continue
            clipped.append({**cube,
                            "from": [x0, y0 - args.model_y_offset, z0],
                            "to": [x1, y1 - args.model_y_offset, z1],
                            "rotation": None})
        cubes = clipped
    metrics = measure_collision(cubes, boxes, args.res)
    print(f"shape={args.shape}; boxes={len(boxes)}; degenerate={degenerate}; elements={len(cubes)}; skipped={len(skipped)}")
    planar = sum(any(abs(cube["to"][i] - cube["from"][i]) < 1e-7 for i in range(3)) for cube in cubes)
    print("geometry check: air {:.2f}% ({}), missed {:.2f}% ({}), coverage {:.2f}%".format(
        metrics["air_percent"], metrics["air_voxels"], metrics["miss_percent"],
        metrics["miss_voxels"], metrics["coverage_percent"]))
    if planar:
        print(f"note: {planar}/{len(cubes)} source elements are planar; volumetric air percentage is not a valid precision verdict for this model")


if __name__ == "__main__":
    main()
