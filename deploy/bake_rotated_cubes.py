#!/usr/bin/env python3
"""Flatten free-format Blockbench cubes into single-axis java_block geometry.

Minecraft cuboid rotation supports one axis. Blockbench's free format allows
three, and its own exporter will not down-convert, so a rotated source cube is
resampled here into axis-aligned voxels on a fixed grid. Only cubes that really
rotate on more than one axis are resampled; every other cube is copied verbatim
so artist UVs, inflate and shading survive untouched.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/deploy"))
from gui_measure import apply_rotation  # noqa: E402

FACE_UV_AXES = {
    # face -> (horizontal local axis, vertical local axis) for UV sampling
    "north": (0, 1), "south": (0, 1),
    "east": (2, 1), "west": (2, 1),
    "up": (0, 2), "down": (0, 2),
}


def _inverse(point, rotation, origin):
    """Undo apply_rotation's x -> y -> z order."""
    result = point
    for axis, angle in reversed(list(zip(("x", "y", "z"), rotation))):
        if abs(angle) < 1e-9:
            continue
        if axis == "x":
            result = apply_rotation(result, [-angle, 0.0, 0.0], origin)
        elif axis == "y":
            result = apply_rotation(result, [0.0, -angle, 0.0], origin)
        else:
            result = apply_rotation(result, [0.0, 0.0, -angle], origin)
    return result


def _axis_extent(element, axis):
    low, high = float(element["from"][axis]), float(element["to"][axis])
    return min(low, high), max(low, high)


def _sample_uv(element, local):
    """Pick the authored face whose plane the voxel sits on and return its UV."""
    best = None
    for face_name, face in element.get("faces", {}).items():
        uv = face.get("uv")
        if face.get("texture") is None or not isinstance(uv, list) or len(uv) != 4:
            continue
        if abs(float(uv[2]) - float(uv[0])) < 1e-6 or abs(float(uv[3]) - float(uv[1])) < 1e-6:
            continue
        axis_a, axis_b = FACE_UV_AXES.get(face_name, (0, 1))
        span_a = _axis_extent(element, axis_a)
        span_b = _axis_extent(element, axis_b)
        if span_a[1] - span_a[0] < 1e-6 or span_b[1] - span_b[0] < 1e-6:
            continue
        score = (span_a[1] - span_a[0]) * (span_b[1] - span_b[0])
        if best is None or score > best[0]:
            best = (score, face_name, uv, axis_a, axis_b, span_a, span_b)
    if best is None:
        return None
    _, face_name, uv, axis_a, axis_b, span_a, span_b = best
    ta = (local[axis_a] - span_a[0]) / (span_a[1] - span_a[0])
    tb = (local[axis_b] - span_b[0]) / (span_b[1] - span_b[0])
    ta = min(max(ta, 0.0), 1.0)
    tb = min(max(tb, 0.0), 1.0)
    u = float(uv[0]) + (float(uv[2]) - float(uv[0])) * ta
    v = float(uv[1]) + (float(uv[3]) - float(uv[1])) * tb
    return face_name, u, v


def bake_element(element, step):
    rotation = element.get("rotation") or [0.0, 0.0, 0.0]
    if sum(1 for angle in rotation if abs(float(angle)) > 1e-6) <= 1:
        return [element], 0
    origin = element.get("origin") or [8.0, 8.0, 8.0]
    corners = [apply_rotation([x, y, z], rotation, origin)
               for x in _axis_extent(element, 0) for y in _axis_extent(element, 1)
               for z in _axis_extent(element, 2)]
    low = [min(point[axis] for point in corners) - step for axis in range(3)]
    high = [max(point[axis] for point in corners) + step for axis in range(3)]
    # A voxel is kept when its centre lies within half a voxel of the rotated
    # slab, measured along the slab's own normal. Using a flat half-step slack
    # drops cells on any slanted face because a diagonal unit cell reaches
    # further than 0.5 along the normal.
    base = apply_rotation([0.0, 0.0, 0.0], rotation, origin)
    spans = []
    for axis in range(3):
        lo, hi = _axis_extent(element, axis)
        if hi - lo < step:
            tip = apply_rotation([1.0 if axis == 0 else 0.0, 1.0 if axis == 1 else 0.0,
                                  1.0 if axis == 2 else 0.0], rotation, origin)
            normal = [tip[index] - base[index] for index in range(3)]
            slack = 0.5 * (abs(normal[0]) + abs(normal[1]) + abs(normal[2])) + 1e-6
            spans.append((lo, hi, slack))
        else:
            spans.append((lo, hi, 0.0))

    cubes = []
    first = [math.floor(low[axis] / step) for axis in range(3)]
    last = [math.ceil(high[axis] / step) for axis in range(3)]
    for i in range(first[0], last[0]):
        for j in range(first[1], last[1]):
            for k in range(first[2], last[2]):
                centre = [(i + 0.5) * step, (j + 0.5) * step, (k + 0.5) * step]
                local = _inverse(centre, rotation, origin)
                inside = True
                for axis, (lo, hi, slack) in enumerate(spans):
                    if slack > 0.0:
                        mid = (lo + hi) * 0.5
                        if abs(local[axis] - mid) > slack:
                            inside = False
                            break
                    elif not (lo - 1e-6 <= local[axis] <= hi + 1e-6):
                        inside = False
                        break
                if not inside:
                    continue
                sample = _sample_uv(element, local)
                if sample is None:
                    continue
                _, u, v = sample
                corners_uv = [u, v, u + step, v + step]
                faces = {name: {"uv": list(corners_uv), "texture": "0"}
                         for name in FACE_UV_AXES}
                cubes.append({
                    "name": element.get("name", "cube"),
                    "from": [i * step, j * step, k * step],
                    "to": [(i + 1) * step, (j + 1) * step, (k + 1) * step],
                    "faces": faces,
                    "type": "cube",
                    "uuid": element.get("uuid"),
                })
    return cubes, len(cubes)


FACE_DIRECTIONS = {
    "west": (0, -1), "east": (0, 1), "down": (1, -1),
    "up": (1, 1), "north": (2, -1), "south": (2, 1),
}


def prune_voxels(voxels, step):
    """Drop faces (and fully buried voxels) that no camera can ever see."""
    index = {(round(v["from"][0] / step), round(v["from"][1] / step), round(v["from"][2] / step)): v
             for v in voxels}
    kept = []
    for key, voxel in index.items():
        faces = {}
        for name, (axis, sign) in FACE_DIRECTIONS.items():
            neighbour = list(key)
            neighbour[axis] += sign
            if tuple(neighbour) in index:
                continue
            faces[name] = voxel["faces"][name]
        if faces:
            kept.append({**voxel, "faces": faces})
    return kept


def bake_model(model, step):
    elements = []
    report = []
    for index, element in enumerate(model.get("elements", [])):
        if element.get("type", "cube") not in ("cube", None):
            raise SystemExit(f"Unsupported element type at index {index}: {element.get('type')}")
        baked, count = bake_element(element, step)
        if count:
            baked = prune_voxels(baked, step)
            report.append({"element": index, "rotation": element.get("rotation"),
                           "voxels": len(baked), "sampled": count})
        elements.extend(baked)
    result = dict(model)
    result["elements"] = elements
    result["meta"] = dict(model.get("meta", {}), model_format="java_block")
    return result, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--step", type=float, default=1.0)
    args = parser.parse_args()
    model = json.loads(args.source.read_text(encoding="utf-8"))
    baked, report = bake_model(model, args.step)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(baked, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Baked {len(report)} multi-axis cube(s) into {sum(item['voxels'] for item in report)} voxels.")
    for item in report:
        print(" ", item)


if __name__ == "__main__":
    main()
