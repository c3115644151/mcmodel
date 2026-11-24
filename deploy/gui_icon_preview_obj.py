"""Render a neoforge:obj model the way Minecraft draws it in the GUI slot.

The asset review loop used to need a client restart per display tweak, because the
only way to see the toolbar icon was to launch the game and screenshot the hotbar.
This module reproduces the GUI transform offline: it applies the display.gui rotation
around the vanilla 8,8,8 model centre, the gui scale, and the gui translation as a
screen-space offset, then rasterises the OBJ faces through the same isometric
projection the java-model preview uses.

Run it directly to print the icon's bounding box inside the 16px slot and write a
magnified PNG for eyeballing:

    python tools/deploy/gui_icon_preview_obj.py

If the box centre drifts off (8, 8), the reported "suggested_translation" is the
display.gui translation that re-centres it.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
from item_icon_preview import _coefficients, project_iso  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = ROOT / "src/main/resources/assets/pastoral_home/models/block"
TEXTURE_DIR = ROOT / "src/main/resources/assets/pastoral_home/textures/block"
SHOT_DIR = ROOT / "build/shots"

FACE_SHADE = {"up": 1.0, "down": 0.55, "north": 0.78, "south": 0.88, "west": 0.68, "east": 0.92}


def read_obj(path: Path):
    """Return vertices, texture vertices and quads from a Wavefront OBJ file."""
    vertices, texcoords, quads = [], [], []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("v "):
            values = [float(value) for value in line.split()[1:4]]
            vertices.append(tuple(values))
        elif line.startswith("vt "):
            values = [float(value) for value in line.split()[1:3]]
            texcoords.append(tuple(values))
        elif line.startswith("f "):
            pairs = []
            for token in line.split()[1:]:
                pieces = token.split("/")
                vertex_index = int(pieces[0]) - 1
                uv_index = int(pieces[1]) - 1 if len(pieces) > 1 and pieces[1] else None
                pairs.append((vertices[vertex_index], texcoords[uv_index] if uv_index is not None else None))
            if len(pairs) == 3:
                pairs = [pairs[0], pairs[1], pairs[2], pairs[2]]
            if len(pairs) == 4:
                quads.append(pairs)
    return vertices, texcoords, quads


def rotate_gui(point, rotation):
    """Rotate a pixel-space point around the vanilla 8,8,8 GUI model centre."""
    import math

    x, y, z = point[0] - 8.0, point[1] - 8.0, point[2] - 8.0
    for axis, degrees in enumerate(rotation):
        radians = math.radians(degrees)
        cos_value, sin_value = math.cos(radians), math.sin(radians)
        if axis == 0:
            y, z = y * cos_value - z * sin_value, y * sin_value + z * cos_value
        elif axis == 1:
            x, z = x * cos_value + z * sin_value, -x * sin_value + z * cos_value
        else:
            x, y = x * cos_value - y * sin_value, x * sin_value + y * cos_value
    return (x + 8.0, y + 8.0, z + 8.0)


def face_name_for(points):
    """Name a quad by its dominant normal so it gets the vanilla face shade."""
    (ax, ay, az), (bx, by, bz), (cx, cy, cz) = points[0], points[1], points[2]
    ux, uy, uz = bx - ax, by - ay, bz - az
    vx, vy, vz = cx - ax, cy - ay, cz - az
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    dominant = max(range(3), key=lambda i: abs((nx, ny, nz)[i]))
    sign = (nx, ny, nz)[dominant] >= 0
    if dominant == 1:
        return "up" if sign else "down"
    if dominant == 2:
        return "south" if sign else "north"
    return "east" if sign else "west"


def render(obj_path: Path, texture_path: Path, display: dict, size: int = 64):
    """Rasterise one GUI icon; return (image, projected_bounds_in_slot_pixels)."""
    _vertices, _texcoords, quads = read_obj(obj_path)
    rotation = display["rotation"]
    scale = display["scale"][0]
    translation = display["translation"]
    texture = Image.open(texture_path).convert("RGBA")

    faces = []
    for quad in quads:
        points = []
        for vertex, uv in quad:
            pixel = (vertex[0] * 16.0, vertex[1] * 16.0, vertex[2] * 16.0)
            rotated = rotate_gui(pixel, rotation)
            points.append(tuple(8.0 + (rotated[i] - 8.0) * scale for i in range(3)))
        projected = []
        for point in points:
            screen_x, screen_y = project_iso((point[0] - 8.0, point[1] - 8.0, point[2] - 8.0))
            # display.gui translation is authored in model space where +y is up, while the
            # projected screen axis grows downward.
            projected.append((screen_x + translation[0], screen_y - translation[1]))
        depth = sum(point[0] * 0.612372 + point[1] * 0.5 + point[2] * 0.612372 for point in points) / len(points)
        uv_points = [uv for _vertex, uv in quad]
        if any(uv is None for uv in uv_points):
            uv_points = None
        else:
            uv_points = [(uv[0] * texture.width, uv[1] * texture.height) for uv in uv_points]
        faces.append((depth, face_name_for(points), projected, uv_points))

    pixels_per_unit = size / 16.0
    output = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    for _depth, face_name, projected, uv_points in sorted(faces, key=lambda item: item[0]):
        destination = [(size / 2 + x * pixels_per_unit, size / 2 + y * pixels_per_unit) for x, y in projected]
        left = max(0, int(min(p[0] for p in destination)) - 1)
        top = max(0, int(min(p[1] for p in destination)) - 1)
        right = min(size, int(max(p[0] for p in destination)) + 2)
        bottom = min(size, int(max(p[1] for p in destination)) + 2)
        if right <= left or bottom <= top:
            continue
        local_dest = [(x - left, y - top) for x, y in destination]
        mask = Image.new("L", (right - left, bottom - top), 0)
        ImageDraw.Draw(mask).polygon(local_dest, fill=255)
        if uv_points is not None:
            coefficients = _coefficients(local_dest, uv_points)
            if coefficients is None:
                continue
            face_image = texture.transform(mask.size, Image.Transform.PERSPECTIVE, coefficients,
                                           resample=Image.Resampling.NEAREST)
            face_image.putalpha(ImageChops.multiply(face_image.getchannel("A"), mask))
        else:
            face_image = Image.new("RGBA", mask.size, (160, 160, 160, 255))
            face_image.putalpha(mask)
        shade = FACE_SHADE[face_name]
        if shade != 1.0:
            red, green, blue, alpha = face_image.split()
            red = red.point(lambda value: int(value * shade))
            green = green.point(lambda value: int(value * shade))
            blue = blue.point(lambda value: int(value * shade))
            face_image = Image.merge("RGBA", (red, green, blue, alpha))
        layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        layer.alpha_composite(face_image, (left, top))
        output = Image.alpha_composite(output, layer)

    alpha = output.getchannel("A")
    box = alpha.getbbox()
    bounds = None
    if box:
        bounds = (box[0] / pixels_per_unit - size / (2 * pixels_per_unit),
                  box[1] / pixels_per_unit - size / (2 * pixels_per_unit),
                  box[2] / pixels_per_unit - size / (2 * pixels_per_unit),
                  box[3] / pixels_per_unit - size / (2 * pixels_per_unit))
    return output, bounds


PIANO_ICON_OFFSET = (0.145535, 0.121013)
"""Where the confirmed piano icon sits relative to a perfectly centred box.

Its display.gui translation is [0.1455, 1.3710] while its untranslated icon centre is
(0.00, 1.25) in slot pixels, so the authored icon is nudged 0.1455px right and 0.121px up
from dead centre. Reusing that nudge keeps every furniture icon visually consistent.
"""


def rgb_vertices(obj_path: Path):
    """Return the OBJ vertex list in block units, ready for projection."""
    vertices, _texcoords, _quads = read_obj(obj_path)
    return vertices


def projected_vertex_bounds(vertices, rotation=(30.0, 45.0, 0.0),
                            scale: float = 0.7375):
    """Bounding box of the projected model in slot pixels, without rasterising.

    A rendered alpha box is clipped by the canvas edges, so a model wider than the
    16px slot reports a false centre; the vertex envelope has no such limit.
    """
    screen_xs, screen_ys = [], []
    for vertex in vertices:
        pixel = (vertex[0] * 16.0, vertex[1] * 16.0, vertex[2] * 16.0)
        rotated = rotate_gui(pixel, rotation)
        point = tuple(8.0 + (rotated[i] - 8.0) * scale for i in range(3))
        screen_x, screen_y = project_iso((point[0] - 8.0, point[1] - 8.0, point[2] - 8.0))
        screen_xs.append(screen_x)
        screen_ys.append(screen_y)
    return (min(screen_xs), min(screen_ys), max(screen_xs), max(screen_ys))


def fitted_gui_display(vertices,
                       rotation=(30.0, 45.0, 0.0), scale: float = 0.7375) -> dict:
    """Solve the display.gui translation that centres an OBJ model in the item slot."""
    bounds = projected_vertex_bounds(vertices, rotation, scale)
    left, top, right, bottom = bounds
    centre_x = (left + right) / 2.0
    centre_y = (top + bottom) / 2.0
    return {
        "rotation": list(rotation),
        "translation": [round(-centre_x + PIANO_ICON_OFFSET[0], 4),
                        round(centre_y + PIANO_ICON_OFFSET[1], 4), 0.0],
        "scale": [scale, scale, scale],
    }


def main() -> int:
    import json

    descriptor = json.loads((MODEL_DIR / "record_player.json").read_text(encoding="utf-8"))
    display = descriptor["display"]["gui"]
    vertices = rgb_vertices(MODEL_DIR / "record_player.obj")
    # Render at 128px so a model wider than the 16px slot is not clipped away.
    image, _rendered = render(MODEL_DIR / "record_player.obj",
                              TEXTURE_DIR / "record_player.png", display, size=128)
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = SHOT_DIR / "obj_gui_icon.png"
    image.save(output_path)
    print(f"gui transform: rotation={display['rotation']} translation={display['translation']} scale={display['scale']}")
    left, top, right, bottom = projected_vertex_bounds(vertices, tuple(display["rotation"]),
                                                       display["scale"][0])
    translation = display["translation"]
    left, right = left + translation[0], right + translation[0]
    top, bottom = top - translation[1], bottom - translation[1]
    centre = ((left + right) / 2.0, (top + bottom) / 2.0)
    print(f"icon box in slot px: {left:.2f} {top:.2f} {right:.2f} {bottom:.2f}"
          f"  size {right - left:.2f} x {bottom - top:.2f}")
    print(f"icon centre: {centre[0]:.2f}, {centre[1]:.2f}  (slot centre is 0, 0)")
    print(f"suggested_translation: [{-centre[0] + PIANO_ICON_OFFSET[0]:.4f}, "
          f"{centre[1] + PIANO_ICON_OFFSET[1]:.4f}, {display['translation'][2]:.4f}]")
    print(f"wrote {output_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
