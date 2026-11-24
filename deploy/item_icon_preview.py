"""Texture-alpha-aware orthographic preview bounds for GUI item icons.

This is a lightweight software preview, not a replacement for Minecraft's renderer.
It projects the authored cuboid faces, samples their UV texture alpha, and returns
the visible pixel envelope so transparent texture padding does not dominate icon fit.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from PIL import Image, ImageChops, ImageDraw

from gui_measure import apply_rotation, project_iso
from item_icon_proxy import rotate_relative_to_vanilla_gui


FACE_VERTICES = {
    # The underside must use the low-y plane. Using ybit=1 projected it onto
    # the top face, where its 0.55 face shade looked like a false shadow.
    "down": ((0, 0, 1), (0, 0, 0), (1, 0, 0), (1, 0, 1)),
    "up": ((0, 1, 0), (0, 1, 1), (1, 1, 1), (1, 1, 0)),
    "north": ((1, 1, 0), (1, 0, 0), (0, 0, 0), (0, 1, 0)),
    "south": ((0, 1, 1), (0, 0, 1), (1, 0, 1), (1, 1, 1)),
    "west": ((0, 1, 0), (0, 0, 0), (0, 0, 1), (0, 1, 1)),
    "east": ((1, 1, 1), (1, 0, 1), (1, 0, 0), (1, 1, 0)),
}


def resolve_texture_reference(model: dict, reference: str) -> str | None:
    textures = model.get("textures", {})
    visited = set()
    key = reference[1:] if reference.startswith("#") else reference
    while key in textures and key not in visited:
        visited.add(key)
        key = str(textures[key])
        if key.startswith("#"):
            key = key[1:]
        else:
            return key
    return None if key == "missing" else key


def _coefficients(dst_points, src_points):
    """Perspective map from output-space destination corners to texture corners."""
    matrix, values = [], []
    for (x, y), (u, v) in zip(dst_points, src_points):
        matrix.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        values.append(u)
        matrix.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        values.append(v)
    n = 8
    for col in range(n):
        pivot = max(range(col, n), key=lambda row: abs(matrix[row][col]))
        matrix[col], matrix[pivot] = matrix[pivot], matrix[col]
        values[col], values[pivot] = values[pivot], values[col]
        div = matrix[col][col]
        if abs(div) < 1e-12:
            return None
        for j in range(col, n):
            matrix[col][j] /= div
        values[col] /= div
        for row in range(n):
            if row == col:
                continue
            factor = matrix[row][col]
            for j in range(col, n):
                matrix[row][j] -= factor * matrix[col][j]
            values[row] -= factor * values[col]
    return values


def _element_points(element: dict, face_name: str):
    low, high = element["from"], element["to"]
    points = []
    for xbit, ybit, zbit in FACE_VERTICES[face_name]:
        point = (high[0] if xbit else low[0], high[1] if ybit else low[1], high[2] if zbit else low[2])
        if element.get("rotation"):
            point = apply_rotation(point, element["rotation"], element.get("origin"))
        points.append(point)
    return points


def _project_view(point, view: str, camera_distance: float = 48.0):
    x, y, z = point[0] - 8.0, point[1] - 8.0, point[2] - 8.0
    if view == "perspective_front":
        # A Blockbench-like elevated front camera. Keep the camera slightly above
        # the model and far enough away that the 2:1 perspective reads naturally
        # without cropping multi-cell furniture.
        camera = (0.0, camera_distance * 0.25, -camera_distance)
        norm = (camera[1] ** 2 + camera[2] ** 2) ** 0.5
        forward = (0.0, -camera[1] / norm, -camera[2] / norm)
        right = (1.0, 0.0, 0.0)
        up = (0.0, forward[2], -forward[1])
        relative = (x - camera[0], y - camera[1], z - camera[2])
        depth = sum(relative[i] * forward[i] for i in range(3))
        if depth <= 1e-6:
            return (1e6, 1e6), depth
        focal = 42.0
        screen_x = sum(relative[i] * right[i] for i in range(3)) * focal / depth
        screen_y = -sum(relative[i] * up[i] for i in range(3)) * focal / depth
        return (screen_x, screen_y), depth
    if view == "front":
        return (x, -y), z
    if view == "side":
        return (z, -y), x
    if view == "top":
        return (x, -z), y
    return project_iso((x, y, z)), x * 0.612372 + y * 0.5 + z * 0.612372


def render_projected_icon(model: dict, texture_resolver: Callable[[str], Path | None],
                         gui_scale: tuple[float, float, float] = (0.625, 0.625, 0.625),
                         gui_rotation: tuple[float, float, float] = (30.0, 225.0, 0.0),
                         size: int = 64, view: str = "isometric",
                         depth_buffer: bool = False,
                         pixels_per_unit: float | None = None,
                         projection_offset: tuple[float, float] = (0.0, 0.0),
                         camera_distance: float = 48.0) -> Image.Image:
    """Render a textured isometric icon approximation for visual batch QA.

    Uses source face UVs, texture alpha, an orthographic GUI projection, sorted
    cuboid faces, and simple block-face shading. It is deliberately a lightweight
    preview, not a replacement for Minecraft's GPU renderer.
    """
    face_shade = {"up": 1.0, "down": 0.55, "north": 0.78, "south": 0.88, "west": 0.68, "east": 0.92}
    quads = []
    for element in model.get("elements", []):
        for face_name, face in element.get("faces", {}).items():
            if face_name not in FACE_VERTICES or not isinstance(face, dict):
                continue
            points = [rotate_relative_to_vanilla_gui(point, gui_rotation)
                      for point in _element_points(element, face_name)]
            scaled_points = [tuple(8.0 + (point[i] - 8.0) * gui_scale[i] for i in range(3)) for point in points]
            projections_and_depths = [_project_view(point, view, camera_distance) for point in scaled_points]
            projected = [item[0] for item in projections_and_depths]
            depths = [item[1] for item in projections_and_depths]
            depth = sum(depths) / len(depths)
            uv = face.get("uv")
            texture_ref = resolve_texture_reference(model, str(face.get("texture", "")))
            texture_path = texture_resolver(texture_ref) if texture_ref else None
            texture = None
            if texture_path and texture_path.is_file():
                try:
                    texture = Image.open(texture_path).convert("RGBA")
                except Exception:
                    texture = None
            uv_points = None
            if uv and texture:
                rotation = (int(face.get("rotation", 0)) // 90) % 4
                order = [(i + rotation) % 4 for i in range(4)]
                uv_points = []
                for index in order:
                    u = uv[0] if index in (0, 1) else uv[2]
                    v = uv[1] if index in (0, 3) else uv[3]
                    uv_points.append((u * texture.width / 16.0, v * texture.height / 16.0))
            quads.append((depth, face_name, projected, texture, uv_points, depths))

    if depth_buffer:
        try:
            return _render_projected_depth_buffer(quads, size, face_shade, view,
                                                  pixels_per_unit, projection_offset)
        except ModuleNotFoundError as error:
            if error.name != "numpy":
                raise
            # Keep asset review usable in the project's minimal Pillow-only
            # environment. The painter fallback is approximate for intersecting
            # translucent faces, but is adequate for ordinary opaque BB cubes.

    output = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pixels_per_unit = pixels_per_unit or (size / 16.0)
    # Back-to-front painter's order approximates the depth buffer for furniture
    # cuboids while remaining deterministic and cheap for 16px item assets.
    # Depth is positive into the scene for the front/side orthographic cameras,
    # so their far planes must be painted first. Isometric and top views use the
    # opposite ordering. Reusing one ascending painter order made front-facing
    # paper decals disappear behind the bulletin-board backing.
    reverse_depth = view in ("front", "side", "perspective_front")
    for _depth, face_name, projected, texture, uv_points, _vertex_depths in sorted(
            quads, key=lambda item: item[0], reverse=reverse_depth):
        destination = [(size / 2 + (x + projection_offset[0]) * pixels_per_unit,
                        size / 2 + (y + projection_offset[1]) * pixels_per_unit) for x, y in projected]
        left = max(0, int(min(p[0] for p in destination)) - 1)
        top = max(0, int(min(p[1] for p in destination)) - 1)
        right = min(size, int(max(p[0] for p in destination)) + 2)
        bottom = min(size, int(max(p[1] for p in destination)) + 2)
        if right <= left or bottom <= top:
            continue
        local_dest = [(x - left, y - top) for x, y in destination]
        mask = Image.new("L", (right - left, bottom - top), 0)
        ImageDraw.Draw(mask).polygon(local_dest, fill=255)
        if texture is not None and uv_points is not None:
            coeff = _coefficients(local_dest, uv_points)
            if coeff is None:
                continue
            face_image = texture.transform(mask.size, Image.Transform.PERSPECTIVE, coeff,
                                           resample=Image.Resampling.NEAREST)
            face_image.putalpha(ImageChops.multiply(face_image.getchannel("A"), mask))
        else:
            color = (160, 160, 160, 255)
            face_image = Image.new("RGBA", mask.size, color)
            face_image.putalpha(mask)

        shade = face_shade[face_name]
        if shade != 1.0:
            red, green, blue, alpha = face_image.split()
            red = red.point(lambda value: int(value * shade))
            green = green.point(lambda value: int(value * shade))
            blue = blue.point(lambda value: int(value * shade))
            face_image = Image.merge("RGBA", (red, green, blue, alpha))
        layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        layer.alpha_composite(face_image, (left, top))
        output = Image.alpha_composite(output, layer)
    return output


def _render_projected_depth_buffer(quads, size: int, face_shade: dict[str, float], view: str,
                                   pixels_per_unit: float, projection_offset: tuple[float, float]) -> Image.Image:
    """Rasterize projected faces with per-pixel depth instead of average-depth painter sorting."""
    import numpy as np

    output = np.zeros((size, size, 4), dtype=np.uint8)
    z_buffer = np.full((size, size), np.inf, dtype=np.float64)

    for _average_depth, face_name, projected, texture, uv_points, vertex_depths in quads:
        destination = [(size / 2 + (x + projection_offset[0]) * pixels_per_unit,
                        size / 2 + (y + projection_offset[1]) * pixels_per_unit) for x, y in projected]
        left = max(0, int(min(p[0] for p in destination)) - 1)
        top = max(0, int(min(p[1] for p in destination)) - 1)
        right = min(size, int(max(p[0] for p in destination)) + 2)
        bottom = min(size, int(max(p[1] for p in destination)) + 2)
        if right <= left or bottom <= top:
            continue
        local_dest = [(x - left, y - top) for x, y in destination]
        mask = Image.new("L", (right - left, bottom - top), 0)
        ImageDraw.Draw(mask).polygon(local_dest, fill=255)
        if texture is not None and uv_points is not None:
            coeff = _coefficients(local_dest, uv_points)
            if coeff is None:
                continue
            face_image = texture.transform(mask.size, Image.Transform.PERSPECTIVE, coeff,
                                           resample=Image.Resampling.NEAREST)
            face_image.putalpha(ImageChops.multiply(face_image.getchannel("A"), mask))
        else:
            face_image = Image.new("RGBA", mask.size, (160, 160, 160, 255))
            face_image.putalpha(mask)

        shade = face_shade[face_name]
        if shade != 1.0:
            red, green, blue, alpha = face_image.split()
            red = red.point(lambda value: int(value * shade))
            green = green.point(lambda value: int(value * shade))
            blue = blue.point(lambda value: int(value * shade))
            face_image = Image.merge("RGBA", (red, green, blue, alpha))
        source = np.asarray(face_image, dtype=np.uint8)

        grid_x, grid_y = np.meshgrid(np.arange(left, right) + 0.5,
                                     np.arange(top, bottom) + 0.5)
        depth_map = np.full((bottom - top, right - left), np.inf, dtype=np.float64)
        # Triangulating the quad gives perspective-correct inverse-depth
        # interpolation for every covered pixel. The image-space UV transform
        # above is a homography, matching the same planar projection.
        for triangle in ((0, 1, 2), (0, 2, 3)):
            points = [destination[index] for index in triangle]
            depths = [float(vertex_depths[index]) for index in triangle]
            (x0, y0), (x1, y1), (x2, y2) = points
            denominator = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
            if abs(denominator) < 1e-10 or any(abs(value) < 1e-10 for value in depths):
                continue
            w0 = ((y1 - y2) * (grid_x - x2) + (x2 - x1) * (grid_y - y2)) / denominator
            w1 = ((y2 - y0) * (grid_x - x2) + (x0 - x2) * (grid_y - y2)) / denominator
            w2 = 1.0 - w0 - w1
            inside = (w0 >= -1e-7) & (w1 >= -1e-7) & (w2 >= -1e-7)
            inverse_depth = w0 / depths[0] + w1 / depths[1] + w2 / depths[2]
            triangle_depth = np.divide(1.0, inverse_depth, out=np.full_like(inverse_depth, np.inf),
                                       where=np.abs(inverse_depth) > 1e-12)
            triangle_depth[~inside] = np.inf
            depth_map = np.minimum(depth_map, triangle_depth)

        # Orthographic top/iso projectors use larger depth values toward the
        # camera; turn those into a consistent smaller-is-nearer depth metric.
        compare_depth = -depth_map if view in ("top", "isometric") else depth_map
        region_depth = z_buffer[top:bottom, left:right]
        alpha = source[:, :, 3].astype(np.float64) / 255.0
        closer = (compare_depth < region_depth) & (alpha > 0.0)
        if not np.any(closer):
            continue
        region = output[top:bottom, left:right]
        src_rgb = source[:, :, :3].astype(np.float64)
        dst_rgb = region[:, :, :3].astype(np.float64)
        dst_alpha = region[:, :, 3].astype(np.float64) / 255.0
        blend_alpha = alpha[:, :, None]
        composed_rgb = src_rgb * blend_alpha + dst_rgb * (1.0 - blend_alpha)
        composed_alpha = alpha + dst_alpha * (1.0 - alpha)
        region[closer, :3] = np.clip(composed_rgb[closer], 0, 255).astype(np.uint8)
        region[closer, 3] = np.clip(composed_alpha[closer] * 255.0, 0, 255).astype(np.uint8)
        region_depth[closer] = compare_depth[closer]

    return Image.fromarray(output, mode="RGBA")


def visible_projected_measurements(model: dict, texture_resolver: Callable[[str], Path | None],
                                   pixels_per_unit: int = 8, preview_path: Path | None = None):
    """Return visible-alpha bounds and centroid in projected model units."""
    quads = []
    projected_all = []
    for element in model.get("elements", []):
        for face_name, face in element.get("faces", {}).items():
            if face_name not in FACE_VERTICES or not isinstance(face, dict):
                continue
            gui_rotation = model.get("display", {}).get("gui", {}).get("rotation", (30.0, 225.0, 0.0))
            points = [rotate_relative_to_vanilla_gui(point, gui_rotation)
                      for point in _element_points(element, face_name)]
            projected = [project_iso((point[0] - 8.0, point[1] - 8.0, point[2] - 8.0))
                          for point in points]
            projected_all.extend(projected)
            uv = face.get("uv")
            texture_ref = resolve_texture_reference(model, str(face.get("texture", "")))
            texture_path = texture_resolver(texture_ref) if texture_ref else None
            texture = None
            if texture_path and texture_path.is_file():
                try:
                    texture = Image.open(texture_path).convert("RGBA")
                except Exception:
                    texture = None
            uv_points = None
            if uv and texture:
                rotation = (int(face.get("rotation", 0)) // 90) % 4
                order = [(i + rotation) % 4 for i in range(4)]
                uv_points = []
                for index in order:
                    u = uv[0] if index in (0, 1) else uv[2]
                    v = uv[1] if index in (0, 3) else uv[3]
                    uv_points.append((u * texture.width / 16.0, v * texture.height / 16.0))
            quads.append((projected, texture, uv_points))

    if not projected_all:
        return None
    min_x = min(point[0] for point in projected_all)
    max_x = max(point[0] for point in projected_all)
    min_y = min(point[1] for point in projected_all)
    max_y = max(point[1] for point in projected_all)
    padding = pixels_per_unit * 2
    width = max(1, int((max_x - min_x) * pixels_per_unit) + padding * 2)
    height = max(1, int((max_y - min_y) * pixels_per_unit) + padding * 2)
    alpha_union = Image.new("L", (width, height), 0)

    for projected, texture, uv_points in quads:
        destination = [(padding + (x - min_x) * pixels_per_unit,
                        padding + (y - min_y) * pixels_per_unit) for x, y in projected]
        left = max(0, int(min(p[0] for p in destination)) - 1)
        top = max(0, int(min(p[1] for p in destination)) - 1)
        right = min(width, int(max(p[0] for p in destination)) + 2)
        bottom = min(height, int(max(p[1] for p in destination)) + 2)
        if right <= left or bottom <= top:
            continue
        face_mask = Image.new("L", (right - left, bottom - top), 0)
        local_dest = [(x - left, y - top) for x, y in destination]
        ImageDraw.Draw(face_mask).polygon(local_dest, fill=255)

        if texture is None or uv_points is None:
            face_alpha = face_mask
        else:
            coeff = _coefficients(local_dest, uv_points)
            if coeff is None:
                continue
            warped = texture.transform((right - left, bottom - top), Image.Transform.PERSPECTIVE,
                                       coeff, resample=Image.Resampling.NEAREST)
            face_alpha = ImageChops.multiply(warped.getchannel("A"), face_mask)
        alpha_union.paste(ImageChops.lighter(alpha_union.crop((left, top, right, bottom)), face_alpha), (left, top))

    bbox = alpha_union.getbbox()
    if bbox is None:
        return None
    alpha_crop = alpha_union.crop(bbox)
    total_alpha = 0
    weighted_x = 0.0
    weighted_y = 0.0
    for index, alpha in enumerate(alpha_crop.getdata()):
        if alpha:
            px = index % alpha_crop.width
            py = index // alpha_crop.width
            total_alpha += alpha
            weighted_x += (px + 0.5) * alpha
            weighted_y += (py + 0.5) * alpha
    center_x = min_x + (bbox[0] - padding + weighted_x / total_alpha) / pixels_per_unit
    center_y = min_y + (bbox[1] - padding + weighted_y / total_alpha) / pixels_per_unit
    if preview_path:
        preview_path.parent.mkdir(parents=True, exist_ok=True)
        alpha_union.save(preview_path)
    return {
        "bounds": (min_x + (bbox[0] - padding) / pixels_per_unit,
                   min_y + (bbox[1] - padding) / pixels_per_unit,
                   min_x + (bbox[2] - padding) / pixels_per_unit,
                   min_y + (bbox[3] - padding) / pixels_per_unit),
        "center": (center_x, center_y),
        "alpha_mass": total_alpha,
    }


def visible_projected_bounds(model: dict, texture_resolver: Callable[[str], Path | None],
                             pixels_per_unit: int = 8, preview_path: Path | None = None):
    """Return (x0,y0,x1,y1) of visible alpha in projected model units, or None."""
    result = visible_projected_measurements(model, texture_resolver, pixels_per_unit, preview_path)
    return result["bounds"] if result else None


def project_gui_translation(translation, gui_rotation):
    """Rough screen offset of a display translation, for drawing previews only.

    Minecraft applies the translation to model space before the GUI rotation, and
    the rotation also tilts by 30 degrees, so this yaw-only projection is an
    approximation. It is adequate for shifting a preview bitmap; it must not be
    inverted to solve for a centering translation, which is what produced the
    per-item offsets this pipeline no longer emits.
    """
    yaw_delta = float(gui_rotation[1]) - 225.0
    vector = apply_rotation(tuple(float(v) for v in translation), [0.0, yaw_delta, 0.0], [0.0, 0.0, 0.0])
    return project_iso(vector)



