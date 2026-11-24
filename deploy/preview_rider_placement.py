#!/usr/bin/env python3
"""Preview actual player hitboxes, eye points and view rays against block models.

The preview is a model-space placement diagnostic. Profiles record the block
anchor and passenger attachment values used by Java. The blue box is Minecraft's
actual entity AABB; the yellow point and ray use the actual player eye height and
camera yaw. It intentionally does not invent a skinned/avatar pose.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "src/main/resources/assets/pastoral_home"
PROFILE_DIR = ROOT / "tools/deploy/rider_profiles"
PANEL_W, PANEL_H = 420, 410
FACINGS = ("north", "east", "south", "west")
VECTORS = {"north": (0, -1), "east": (1, 0), "south": (0, 1), "west": (-1, 0)}
FACE_VERTS = {
    "north": (0, 2, 6, 4), "south": (1, 5, 7, 3),
    "west": (0, 1, 3, 2), "east": (4, 6, 7, 5),
    "down": (0, 4, 5, 1), "up": (2, 3, 7, 6),
}
FACE_COLORS = {
    "up": (151, 116, 73), "down": (75, 61, 49),
    "north": (111, 83, 56), "south": (123, 90, 57),
    "west": (91, 70, 52), "east": (137, 99, 61),
}
VANILLA_PLAYER = json.loads((PROFILE_DIR / "vanilla_player_26_1_2.json").read_text(encoding="utf-8-sig"))


def rotate_facing(point: tuple[float, float, float], facing: str) -> tuple[float, float, float]:
    """Rotate model-space pixels as Minecraft's horizontal FACING rotates the block."""
    x, y, z = point
    turns = FACINGS.index(facing)
    for _ in range(turns):
        x, z = 16.0 - z, x
    return x, y, z


def aabb_corners(bounds: tuple[float, float, float, float, float, float]):
    x0, y0, z0, x1, y1, z1 = bounds
    return [(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]


def model_mesh_intersects_aabb(mesh: list[tuple[float, float, float]], aabb: tuple[float, ...]) -> bool:
    """Separating-axis test between a transformed model cuboid and player AABB."""
    sub = lambda a, b: tuple(a[i] - b[i] for i in range(3))
    cross = lambda a, b: (a[1] * b[2] - a[2] * b[1],
                          a[2] * b[0] - a[0] * b[2],
                          a[0] * b[1] - a[1] * b[0])
    length = lambda v: math.sqrt(sum(value * value for value in v))
    edges = [sub(mesh[4], mesh[0]), sub(mesh[2], mesh[0]), sub(mesh[1], mesh[0])]
    world_axes = [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)]
    axes = list(world_axes)
    axes.extend(cross(edges[i], edges[j]) for i, j in ((0, 1), (0, 2), (1, 2)))
    axes.extend(cross(edge, world_axis) for edge in edges for world_axis in world_axes)
    player_vertices = aabb_corners(aabb)
    for axis in axes:
        if length(axis) < 1e-8:
            continue
        model_proj = [sum(point[i] * axis[i] for i in range(3)) for point in mesh]
        player_proj = [sum(point[i] * axis[i] for i in range(3)) for point in player_vertices]
        if max(model_proj) < min(player_proj) - 1e-6 or max(player_proj) < min(model_proj) - 1e-6:
            return False
    return True


def model_meshes(model: dict, facing: str) -> list[list[tuple[float, float, float]]]:
    result = []
    for element in model.get("elements", []):
        corners = aabb_corners(tuple(element["from"] + element["to"]))
        rotation = element.get("rotation")
        if rotation and float(rotation.get("angle", 0.0)):
            origin = rotation.get("origin", (8, 8, 8))
            axis = rotation["axis"]
            radians = math.radians(float(rotation["angle"]))
            c, s = math.cos(radians), math.sin(radians)
            rotated = []
            for x, y, z in corners:
                x, y, z = x - origin[0], y - origin[1], z - origin[2]
                if axis == "x": y, z = y * c - z * s, y * s + z * c
                elif axis == "y": x, z = x * c + z * s, -x * s + z * c
                else: x, y = x * c - y * s, x * s + y * c
                rotated.append((x + origin[0], y + origin[1], z + origin[2]))
            corners = rotated
        corners = [rotate_facing(point, facing) for point in corners]
        result.append(corners)
    return result


def model_boxes(model: dict, facing: str) -> list[tuple[float, float, float, float, float, float]]:
    return [tuple([min(p[i] for p in corners) for i in range(3)]
                  + [max(p[i] for p in corners) for i in range(3)])
            for corners in model_meshes(model, facing)]


def rider_anchors(profile: dict, facing: str) -> list[tuple[float, float, float]]:
    if profile["type"] == "seat":
        distance = float(profile["behind_offset_blocks"]) * 16.0
        base = (8.0, float(profile["seat_height_blocks"]) * 16.0, 8.0 + distance)
        attach = tuple(float(v) for v in profile.get("passenger_offset_px", [0, 0.16, 0]))
        return [rotate_facing(tuple(base[i] + attach[i] for i in range(3)), facing)]
    return [rotate_facing(tuple(float(v) for v in spot), facing)
            for spot in profile["sleep_spots_px"]]


def player_boxes(profile: dict, facing: str) -> tuple[list[tuple[tuple[float, ...], str]], list[tuple[float, float, float]]]:
    sleeping = profile["type"] == "sleep"
    pose = VANILLA_PLAYER["entity_dimensions_blocks"]["sleeping" if sleeping else "standing"]
    width, height = (float(value) * 16.0 for value in pose["aabb"])
    eye_height = float(pose["eye_height"]) * 16.0
    output, eyes = [], []
    for x, y, z in rider_anchors(profile, facing):
        corners = [rotate_facing((x + dx, y + dy, z + dz), facing)
                   for dx in (-width / 2, width / 2)
                   for dy in (0.0, height)
                   for dz in (-width / 2, width / 2)]
        output.append((tuple([min(p[i] for p in corners) for i in range(3)]
                              + [max(p[i] for p in corners) for i in range(3)]), "player_aabb"))
        eyes.append((x, y + eye_height, z))
    return output, eyes


def player_look_vector(profile: dict, facing: str):
    return None if profile["type"] == "sleep" else VECTORS[facing]


def telescope_camera_origin(profile: dict, eye: tuple[float, float, float], facing: str):
    look = player_look_vector(profile, facing)
    if look is None:
        return eye
    forward_px = float(profile["camera_forward_offset_blocks"]) * 16.0
    return eye[0] + look[0] * forward_px, eye[1], eye[2] + look[1] * forward_px


def _project(point, view: str):
    x, y, z = point
    if view == "front": return (x, -y), -z
    if view == "side": return (z, -y), x
    if view == "top": return (x, -z), y
    return ((x - z) * 0.7071, (x + z) * 0.35355 - y), x + z + y * 0.1


def _cube_faces(bounds):
    corners = aabb_corners(bounds)
    for face, indices in FACE_VERTS.items():
        yield face, [corners[i] for i in indices]


def _draw_panel(image, draw, model, profile, facing, view, panel_rect, title):
    left, top, width, height = panel_rect
    draw.rectangle((left, top, left + width, top + height), fill=(37, 41, 46), outline=(108, 116, 124), width=2)
    draw.text((left + 12, top + 9), f"{title} · {facing.upper()}", fill=(239, 240, 242))
    draw.text((left + 12, top + 24), "yellow: eye/look ray   cyan: camera at lens", fill=(190, 197, 204))
    meshes = []
    model_geometry = model_meshes(model, facing)
    boxes = [tuple([min(p[i] for p in corners) for i in range(3)]
                   + [max(p[i] for p in corners) for i in range(3)]) for corners in model_geometry]
    for corners in model_geometry:
        for face, indices in FACE_VERTS.items():
            points = [corners[index] for index in indices]
            projected = [_project(point, view) for point in points]
            depth = sum(p[1] for p in projected) / len(projected)
            meshes.append((depth, points, FACE_COLORS[face], "model"))
    riders, eyes = player_boxes(profile, facing)
    rider_colors = {"player_aabb": (69, 156, 212)}
    for bounds, part in riders:
        overlaps_model = any(model_mesh_intersects_aabb(mesh, bounds) for mesh in model_geometry)
        for _face, points in _cube_faces(bounds):
            projected = [_project(point, view) for point in points]
            depth = sum(p[1] for p in projected) / len(projected)
            meshes.append((depth, points, (218, 65, 75) if overlaps_model else rider_colors[part],
                           "rider_overlap" if overlaps_model else "rider"))
    look_vector = player_look_vector(profile, facing)
    projected_all = [_project(point, view)[0] for _, points, _, _ in meshes for point in points]
    for eye in eyes:
        projected_all.append(_project(eye, view)[0])
        if look_vector is not None:
            lens = telescope_camera_origin(profile, eye, facing)
            tip = (lens[0] + look_vector[0] * 5, lens[1], lens[2] + look_vector[1] * 5)
            projected_all.extend((_project(lens, view)[0], _project(tip, view)[0]))
    min_x, max_x = min(p[0] for p in projected_all), max(p[0] for p in projected_all)
    min_y, max_y = min(p[1] for p in projected_all), max(p[1] for p in projected_all)
    span_x, span_y = max(max_x - min_x, 1), max(max_y - min_y, 1)
    scale = min((width - 56) / span_x, (height - 150) / span_y)
    cx, cy = left + width / 2, top + height * 0.47
    def screen(point):
        px, py = _project(point, view)[0]
        return cx + (px - (min_x + max_x) / 2) * scale, cy + (py - (min_y + max_y) / 2) * scale
    meshes.sort(key=lambda entry: entry[0])
    for _depth, points, color, kind in meshes:
        poly = [screen(p) for p in points]
        outline = (255, 105, 110) if kind == "rider_overlap" else (
            (26, 29, 33) if kind == "model" else (178, 218, 239))
        draw.polygon(poly, fill=color, outline=outline, width=2 if kind == "rider_overlap" else 1)
    for eye in eyes:
        eye_screen = screen(eye)
        draw.ellipse((eye_screen[0] - 3, eye_screen[1] - 3, eye_screen[0] + 3, eye_screen[1] + 3),
                     fill=(255, 220, 70), outline=(55, 45, 15))
        if look_vector is not None:
            dx, dz = look_vector
            lens = telescope_camera_origin(profile, eye, facing)
            lens_screen = screen(lens)
            draw.line((eye_screen, lens_screen), fill=(50, 226, 241), width=2)
            draw.ellipse((lens_screen[0] - 4, lens_screen[1] - 4, lens_screen[0] + 4,
                          lens_screen[1] + 4), fill=(50, 226, 241), outline=(12, 54, 62))
            tip = screen((lens[0] + dx * 5, lens[1], lens[2] + dz * 5))
            draw.line((lens_screen, tip), fill=(255, 220, 70), width=3)
            vx, vy = tip[0] - lens_screen[0], tip[1] - lens_screen[1]
            length = max(math.hypot(vx, vy), 1.0)
            ux, uy = vx / length, vy / length
            px, py = -uy, ux
            arrow = [tip,
                     (tip[0] - ux * 9 + px * 4, tip[1] - uy * 9 + py * 4),
                     (tip[0] - ux * 9 - px * 4, tip[1] - uy * 9 - py * 4)]
            draw.polygon(arrow, fill=(255, 220, 70))
    anchor = rider_anchors(profile, facing)[0]
    pose = VANILLA_PLAYER["entity_dimensions_blocks"]["sleeping" if profile["type"] == "sleep" else "standing"]
    dims = tuple(float(value) * 16.0 for value in pose["aabb"])
    eye_px = float(pose["eye_height"]) * 16.0
    anatomy = VANILLA_PLAYER["player_model_parts_px"]
    model_note = (f"Mesh px: head {anatomy['head'][1]} · torso {anatomy['torso'][0]}x{anatomy['torso'][1]} "
                  f"· legs {anatomy['leg'][0]}x{anatomy['leg'][1]} · arms 3/4x12")
    pose_note = (f"Render scale {VANILLA_PLAYER['avatar_render_scale']:.4f} · riding leg X "
                 f"{VANILLA_PLAYER['passenger_pose_radians']['legs_x']:.4f}rad")
    footer = (f"AABB {dims[0]:.1f}x{dims[1]:.1f}px · feet {anchor[0]/16:.2f}/{anchor[1]/16:.2f}/"
              f"{anchor[2]/16:.2f} · eye {eye_px:.2f}px · camera +"
              f"{profile.get('camera_forward_offset_blocks', 0.0):.2f} · view {facing if look_vector else 'sleep'}")
    draw.text((left + 12, top + height - 61), model_note, fill=(187, 198, 206))
    draw.text((left + 12, top + height - 43), pose_note, fill=(187, 198, 206))
    draw.text((left + 12, top + height - 25), footer, fill=(214, 217, 220))


def render(profile_path: Path, output: Path, facing: str | None = None) -> None:
    profile = json.loads(profile_path.read_text(encoding="utf-8-sig"))
    model_path = ROOT / profile["model"]
    model = json.loads(model_path.read_text(encoding="utf-8-sig"))
    image = Image.new("RGB", (PANEL_W * 2, PANEL_H * 2), (28, 31, 35))
    draw = ImageDraw.Draw(image)
    panels = (("isometric", (0, 0), "isometric"), ("front", (PANEL_W, 0), "front"),
              ("side", (0, PANEL_H), "side"), ("top", (PANEL_W, PANEL_H), "top"))
    facing = facing or profile.get("facing", "north")
    for view, (left, top), title in panels:
        _draw_panel(image, draw, model, profile, facing, view,
                    (left, top, PANEL_W, PANEL_H), title)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", help="profile name in tools/deploy/rider_profiles or a JSON path")
    parser.add_argument("--output", type=Path, default=Path("build/rider_position_preview.png"))
    parser.add_argument("--facing", choices=(*FACINGS, "all"), default=None,
                        help="orientation to preview; 'all' writes one contact sheet per facing")
    args = parser.parse_args()
    candidate = Path(args.profile)
    profile_path = candidate if candidate.is_file() else PROFILE_DIR / f"{args.profile}.json"
    if not profile_path.is_file():
        parser.error(f"rider profile not found: {profile_path}")
    if args.facing == "all":
        for facing in FACINGS:
            output = args.output.with_name(f"{args.output.stem}_{facing}{args.output.suffix}").resolve()
            render(profile_path.resolve(), output, facing)
            print(output)
    else:
        output = args.output.resolve()
        render(profile_path.resolve(), output, args.facing)
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
