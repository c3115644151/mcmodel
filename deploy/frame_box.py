#!/usr/bin/env python
"""Where a placed block's model actually lands on a screenshot.

A block coordinate is not the subject: the lamp is a quarter-block that hangs inside the cell, and
the variant that is placed can rotate it against any of six faces. Both facts are already on disk --
the blockstate names the model, the model carries the element boxes and rotations -- so the pixel
box is derived instead of guessed, and a crop never depends on somebody eyeballing a screenshot.
"""
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "build/resources/main/assets/pastoral_home"
FOV_Y = 70.0


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def variant_for(block_id, properties, res=RES):
    """Model plus blockstate rotation for the state the world reported."""
    name = block_id.split(":", 1)[1]
    states = _load(res / "blockstates" / (name + ".json"))
    props = {key: str(value) for key, value in (properties or {}).items()}
    if "variants" in states:
        variants = states["variants"]
        best = None
        for key, value in variants.items():
            wanted = {}
            for part in key.split(","):
                if "=" in part:
                    prop, val = part.split("=", 1)
                    wanted[prop] = val
            if all(props.get(prop) == val for prop, val in wanted.items()):
                if best is None or len(wanted) > best[0]:
                    best = (len(wanted), value)
        if best is None:
            return None
        return best[1]
    return None


# Element rotations are arbitrary angles about any axis; blockstate x/y are the eight quarter turns
# of OctahedralGroup, and they are NOT the cosine matrix with a positive angle: x:90 sends +Y to -Z
# (north), so the matrix below is the one the client uses, not the naive one.
QUARTER = {
    ("x", 90): lambda v: [v[0], v[2], -v[1]],
    ("x", 180): lambda v: [v[0], -v[1], -v[2]],
    ("x", 270): lambda v: [v[0], -v[2], v[1]],
    ("y", 90): lambda v: [-v[2], v[1], v[0]],
    ("y", 180): lambda v: [-v[0], v[1], -v[2]],
    ("y", 270): lambda v: [v[2], v[1], -v[0]],
}


def turn(direction, keys):
    """Apply blockstate "x" then "y" quarter turns to a direction (-1/0/1 per axis)."""
    turned = tuple(direction)
    for axis in ("x", "y"):
        angle = keys.get(axis)
        if angle:
            turned = QUARTER[(axis, int(angle) % 360)](turned)
    return tuple(int(round(value)) for value in turned)


def rotate_point(point, axis, angle, origin):
    quarter = QUARTER.get((axis, int(angle) % 360))
    if quarter is not None:
        local = [point[i] - origin[i] for i in range(3)]
        turned = quarter(local)
        return [turned[i] + origin[i] for i in range(3)]
    index = "xyz".index(axis)
    local = [point[i] - origin[i] for i in range(3)]
    radians = math.radians(angle)
    cos, sin = math.cos(radians), math.sin(radians)
    a, b = [i for i in range(3) if i != index]
    local[a], local[b] = cos * local[a] - sin * local[b], sin * local[a] + cos * local[b]
    return [local[i] + origin[i] for i in range(3)]


def element_points(element):
    low, high = element["from"], element["to"]
    points = []
    for x in (low[0], high[0]):
        for y in (low[1], high[1]):
            for z in (low[2], high[2]):
                point = [x, y, z]
                rotation = element.get("rotation")
                if rotation:
                    point = rotate_point(point, rotation["axis"], rotation["angle"],
                                         rotation.get("origin", [8.0, 8.0, 8.0]))
                points.append(point)
    return points


def model_box(model_path, variant):
    """Union box of every element, in block units 0..16, with the variant rotation applied."""
    path = RES / "models" / (model_path.split(":", 1)[1] + ".json")
    model = _load(path)
    points = []
    for element in model.get("elements", []):
        points.extend(element_points(element))
    for axis in ("x", "y"):
        angle = variant.get(axis)
        if angle:
            points = [rotate_point(point, axis, angle, [8.0, 8.0, 8.0]) for point in points]
    low = [min(point[i] for point in points) / 16.0 for i in range(3)]
    high = [max(point[i] for point in points) / 16.0 for i in range(3)]
    return low, high


def world_box(block_id, properties, position):
    variant = variant_for(block_id, properties)
    if variant is None:
        return None
    low, high = model_box(variant["model"], variant)
    return ([position[i] + low[i] for i in range(3)],
            [position[i] + high[i] for i in range(3)])


def project(low, high, camera, width=1920, height=1080, fov=FOV_Y, pad=0.25):
    """Pixel box the box covers, assuming the client renders with the vanilla field of view."""
    yaw = math.radians(camera.get("yaw", 180.0))
    pitch = math.radians(camera.get("pitch", 0.0))
    eye = [camera["x"], camera["y"] + 1.62, camera["z"]]
    forward = [-math.sin(yaw) * math.cos(pitch), -math.sin(pitch), math.cos(yaw) * math.cos(pitch)]
    right = [math.cos(yaw), 0.0, math.sin(yaw)]
    up = [forward[1] * right[2] - forward[2] * right[1],
          forward[2] * right[0] - forward[0] * right[2],
          forward[0] * right[1] - forward[1] * right[0]]
    tan_y = math.tan(math.radians(fov / 2.0))
    xs, ys = [], []
    for x in (low[0], high[0]):
        for y in (low[1], high[1]):
            for z in (low[2], high[2]):
                v = [x - eye[0], y - eye[1], z - eye[2]]
                depth = v[0] * forward[0] + v[1] * forward[1] + v[2] * forward[2]
                if depth <= 0.05:
                    return None
                sx = (v[0] * right[0] + v[1] * right[1] + v[2] * right[2]) / depth / (tan_y * (width / height))
                sy = (v[0] * up[0] + v[1] * up[1] + v[2] * up[2]) / depth / tan_y
                xs.append(width * 0.5 + sx * width * 0.5)
                ys.append(height * 0.5 - sy * height * 0.5)
    box_w, box_h = max(xs) - min(xs), max(ys) - min(ys)
    box = (max(0, int(min(xs) - box_w * pad)), max(0, int(min(ys) - box_h * pad)),
           min(width, int(max(xs) + box_w * pad)), min(height, int(max(ys) + box_h * pad)))
    return {"bbox": box, "size": [int(box_w), int(box_h)]}
