"""Texture-alpha-aware orthographic preview bounds for GUI item icons.

This is a lightweight software preview, not a replacement for Minecraft's renderer.
It projects the authored cuboid faces, samples their UV texture alpha, and returns
the visible pixel envelope so transparent texture padding does not dominate icon fit.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Callable

from PIL import Image, ImageChops, ImageDraw

from gui_measure import apply_rotation, project_iso
from item_icon_proxy import rotate_for_display, rotate_relative_to_vanilla_gui


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


# project_iso 的视点不变方向（display 空间）。相机从 (+x,+y,+z) 看向模型，
# 法线与它点乘为正的面朝相机、是正面；为负的是背面。Minecraft 方块模型做
# 背面剔除，离线预览必须一致，否则：负尺寸灯罩（from>to，绕序翻转、法线朝内）
# 会被画成实心块，背面也会盖住正面细节。
GUI_VIEW_DIR = (1.0, math.sqrt(2.0) * math.tan(math.radians(30.0)), -1.0)

# 镂空（cutout）渲染类型的丢弃阈值是 alpha < 0.1，不是 0.5：原版
# rendertype_cutout 的片元着色器写的是 "if (color.a < 0.1) discard;"，保留下来的
# 像素以原色直接写入（cutout 不开混合，所以半透明像素显示为全色）。阈值取 128
# 会把 0.1–0.5 之间的像素整片丢掉，地毯、灯罩和花架的边缘因此比游戏里窄一圈。
ALPHA_CUTOUT = 26

# GUI 物品图标没有任何方向明暗：ItemFeatureRenderer.renderItem 把烘焙 quad 直接
# putBakedQuad 到 render type 缓冲，只传 light coords（GUI 为 FULL_BRIGHT）与图层
# tint，从不读 quad 的 materialInfo().shade()。那个 shade 标志的唯一消费者是
# BlockModelLighter（方块/区块渲染，见 BlockModelLighter.java:207 与 :220），
# 走不到物品路径。所以图标上每个面都是全亮：面颜色 = 纹理色 × tint。
# 之前按 FaceBakery 的方向常量（up 1.0 / down 0.5 / 南北 0.8 / 东西 0.6）乘一遍，
# 恰好让侧面多的图标整体偏暗约 20%，这就是「剪影 IoU=1.000 但 rgb 差 40+」的来源。
SHADE_GAME = {"up": 1.0, "down": 1.0, "north": 0.40, "south": 0.40,
             "west": 0.60, "east": 0.65}
SHADE_FLAT = {"up": 1.0, "down": 1.0, "north": 1.0, "south": 1.0,
              "west": 1.0, "east": 1.0}

# 真机实测的有效明暗表（见 diag_gui_shading.py 与 design/item-icon-gui.md）：
# 把真机截图的像素按面归类后除以平面渲染，n/s=0.40、e/w=0.60/0.65、up/down=1.0，
# 且该倍率在各亮度带恒定（纯乘法，不是 gamma）。这是默认档，离线预览据此与游戏对齐。
# 某些模型（薄片、贴花、金属反光面）加上阴影反而更难看，可以按物品切到 flat。
SHADE_PROFILES = {"game": SHADE_GAME, "flat": SHADE_FLAT}
FACE_SHADE = SHADE_GAME

# 强度是 game 表的线性插值系数：0 = 不乘明暗（等同 flat），1 = 真机实测值，
# 允许 >1（压得更狠）。单物品常常两者都不满意——火盆这类自带亮面的模型开 1.0 发暗、
# 关掉又发亮，需要中间值，所以档位从"二选一"改成连续量。
SHADE_STRENGTH_MIN = 0.0
SHADE_STRENGTH_MAX = 1.5


def clamp_shade_strength(strength: float) -> float:
    try:
        value = float(strength)
    except (TypeError, ValueError):
        return 1.0
    return max(SHADE_STRENGTH_MIN, min(SHADE_STRENGTH_MAX, value))


def shade_strength_profile(strength: float) -> dict[str, float]:
    """Per-face multipliers at a shading strength (linear between flat and game)."""
    factor = clamp_shade_strength(strength)
    return {face: round(1.0 - factor * (1.0 - value), 4)
            for face, value in SHADE_GAME.items()}


def shade_profile(name: str | None = None, strength: float | None = None) -> dict[str, float]:
    """Resolve a shading profile; an explicit strength wins over the named profile."""
    if strength is not None:
        return shade_strength_profile(strength)
    if not name:
        return SHADE_GAME
    if str(name) == "flat":
        return SHADE_FLAT
    return SHADE_PROFILES.get(str(name), SHADE_GAME)

# 面朝向的编号，用于把真机与离线的色差按面归因（诊断脚本 diag_gui_shading.py）。
# 面 ID 缓冲区里存的是 element_index * 8 + 方向编号，这样同一方向但来自不同
# element 的面不会混在一起；方向用 id % 8 还原，element 用 id // 8。
# 0 保留为空像素。
FACE_IDS = {"down": 1, "up": 2, "north": 3, "south": 4, "west": 5, "east": 6}


def np_zero_ids(size: int):
    """Face-id buffer (uint8) for shading diagnostics; None when numpy is absent."""
    try:
        import numpy as np
    except ModuleNotFoundError as error:
        if error.name != "numpy":
            raise
        return None
    return np.zeros((size, size), dtype=np.uint16)


def apply_alpha_cutout(image: Image.Image) -> Image.Image:
    """把纹理面的 alpha 硬裁成 0 或 255，模拟 ALPHA_CUTOUT 0.5。"""
    alpha = image.getchannel("A").point(lambda value: 255 if value >= ALPHA_CUTOUT else 0)
    image.putalpha(alpha)
    return image


def _face_outward_normal(element: dict, face_name: str):
    """面的绕序法线（模型空间）。负尺寸 cube 绕序翻转，法线自然朝内，
    这正是 Minecraft 实现「内面可见」镂空灯罩的机制。"""
    pts = _element_points(element, face_name)
    a, b, c = pts[0], pts[1], pts[2]
    ux, uy, uz = (b[i] - a[i] for i in range(3))
    vx, vy, vz = (c[i] - a[i] for i in range(3))
    nx, ny, nz = (uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)
    mag = math.sqrt(nx * nx + ny * ny + nz * nz)
    if mag < 1e-9:
        return None
    return (nx / mag, ny / mag, nz / mag)


ROOT_ORIGIN_DEFAULTS = {
    "corner": (0.0, 0.0, 0.0),
    "center": (8.0, 8.0, 8.0),
    "opposing-corner": (16.0, 16.0, 16.0),
}


def root_origin(transform):
    """Root transform origin in model units; defaults to the opposing corner."""
    origin = transform.get("origin", "opposing-corner")
    if isinstance(origin, str):
        return ROOT_ORIGIN_DEFAULTS.get(origin, ROOT_ORIGIN_DEFAULTS["opposing-corner"])
    return tuple(float(value) * 16.0 for value in origin)


def _root_axis_rotations(value):
    if not value:
        return []
    if isinstance(value, dict):
        return [value]
    return list(value)


def _rotate_about_axis(point, axis, degrees):
    angle = math.radians(float(degrees))
    cosine, sine = math.cos(angle), math.sin(angle)
    x, y, z = point
    if axis == "x":
        return (x, y * cosine - z * sine, y * sine + z * cosine)
    if axis == "y":
        return (x * cosine + z * sine, y, -x * sine + z * cosine)
    return (x * cosine - y * sine, x * sine + y * cosine, z)


def apply_root_transform(point, transform):
    """Apply a NeoForge model root transform ("transform" at the model root).

    The entries are applied in the documented order - translation, left rotation,
    scale, right rotation - composed about the transform origin, and the result is
    baked into the geometry *before* the item display transform. The translation is
    given in blocks rather than 1/16 blocks, so [0, 1, 0] raises the whole model by
    a full block; ignoring it drew such icons 16 units off and left the game's icon
    clipped to one corner of the slot.
    """
    if not transform:
        return point
    origin = root_origin(transform)
    translation = transform.get("translation", (0.0, 0.0, 0.0))
    local = (point[0] - origin[0] + float(translation[0]) * 16.0,
             point[1] - origin[1] + float(translation[1]) * 16.0,
             point[2] - origin[2] + float(translation[2]) * 16.0)
    for entry in _root_axis_rotations(transform.get("rotation") or transform.get("left_rotation")):
        for axis, degrees in entry.items():
            local = _rotate_about_axis(local, str(axis).lower(), degrees)
    scale = transform.get("scale", (1.0, 1.0, 1.0))
    local = (local[0] * float(scale[0]), local[1] * float(scale[1]), local[2] * float(scale[2]))
    for entry in _root_axis_rotations(transform.get("right_rotation") or transform.get("post_rotation")):
        for axis, degrees in entry.items():
            local = _rotate_about_axis(local, str(axis).lower(), degrees)
    return (local[0] + origin[0], local[1] + origin[1], local[2] + origin[2])


def _mat_mul(a, b):
    return tuple(tuple(sum(a[row][k] * b[k][col] for k in range(3)) for col in range(3))
                 for row in range(3))


def _mat_apply(matrix, vector):
    return tuple(sum(matrix[row][k] * vector[k] for k in range(3)) for row in range(3))


def gui_rotation_matrix(rotation):
    """ItemTransform rotation as Rx * Ry * Rz, matching Quaternionf.rotationXYZ."""
    rx, ry, rz = (math.radians(float(value)) for value in rotation)
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    rotate_x = ((1.0, 0.0, 0.0), (0.0, cx, -sx), (0.0, sx, cx))
    rotate_y = ((cy, 0.0, sy), (0.0, 1.0, 0.0), (-sy, 0.0, cy))
    rotate_z = ((cz, -sz, 0.0), (sz, cz, 0.0), (0.0, 0.0, 1.0))
    return _mat_mul(rotate_x, _mat_mul(rotate_y, rotate_z))


def gui_screen_point(point, rotation):
    """Project one model point the way the game draws a GUI item.

    ItemTransform.apply translates, rotates around X, Y then Z, scales, and centers
    the unit cube; the GUI item camera then looks down -Z with +Y up. So screen X is
    the rotated X and screen Y is minus the rotated Y - not a hand-built isometric
    basis. Building that basis by hand picked the mirrored handedness (screen X came
    out as +(x+z) instead of -(x+z) after the 225 degree yaw), which reflected every
    asymmetric model left-to-right against the real icon.
    """
    matrix = gui_rotation_matrix(rotation)
    normalized = ((point[0] - 8.0) / 16.0, (point[1] - 8.0) / 16.0, (point[2] - 8.0) / 16.0)
    rotated = _mat_apply(matrix, normalized)
    return (rotated[0] * 16.0, -rotated[1] * 16.0), rotated[2]


def face_is_front_facing(element: dict, face_name: str, gui_rotation) -> bool:
    """按 Minecraft 的背面剔除规则判断这个面在 GUI 相机下是否可见。"""
    normal = _face_outward_normal(element, face_name)
    if normal is None:
        return True
    # 相机沿 -Z 看，旋转后法线 z 为正的面才朝向相机。
    rotated = _mat_apply(gui_rotation_matrix(gui_rotation), normal)
    return rotated[2] > 1e-6


def load_sprite(path: Path, frame: int = 0) -> Image.Image | None:
    """Load a texture as one sprite frame.

    An animated sprite ships as a vertical strip (the 彩灯 shell is 32x128 with four
    32x32 frames) whose height is the frame count times the frame height. Face UVs are
    measured against the frame, so sampling the whole strip stretched every face
    window four times too tall and the icon read as horizontal amber bands instead
    of a lamp. The frame height comes from the sprite's .mcmeta, falling back to the
    sprite width, which is the frame shape for every strip this project ships.
    """
    path = Path(path)
    if not path.is_file():
        return None
    try:
        sprite = Image.open(path).convert("RGBA")
    except Exception:
        return None
    meta_path = path.with_name(path.name + ".mcmeta")
    height = sprite.height
    if meta_path.is_file():
        try:
            animation = json.loads(meta_path.read_text(encoding="utf-8")).get("animation", {})
        except (OSError, json.JSONDecodeError):
            animation = {}
        declared = animation.get("height") or sprite.width
        if isinstance(declared, int) and 0 < declared < sprite.height:
            height = declared
    if height >= sprite.height:
        return sprite
    frames = sprite.height // height
    chosen = max(0, min(frame, frames - 1))
    return sprite.crop((0, chosen * height, sprite.width, (chosen + 1) * height))


def tinted_water_sprite(texture: Image.Image | None, texture_ref: str | None) -> Image.Image | None:
    """Apply the vanilla biome water tint to a grey water sprite.

    Minecraft's water_still / flowing sprites are grey in the texture atlas and
    get their blue colour from a per-biome colour multiplier at render time.
    The offline preview has no biome, so without this the water in a barrel or
    well renders as a flat grey/white block instead of the blue players see in
    game. Use the overworld river/ocean water colour.
    """
    if texture is None or not texture_ref:
        return texture
    ref = texture_ref.lower()
    if "water_still" not in ref and "water_flow" not in ref and "wishing_well_water" not in ref:
        return texture
    # 0x3F76E4 is vanilla overworld water; keep the sprite's own luminance so
    # surface highlights/still-water shading survive the tint.
    tint = (0x3F, 0x76, 0xE4)
    src = list(texture.get_flattened_data())
    out = []
    for r, g, b, a in src:
        lum = (r + g + b) / 3.0 / 255.0
        out.append((int(tint[0] * lum), int(tint[1] * lum), int(tint[2] * lum), a))
    result = Image.new("RGBA", texture.size)
    result.putdata(out)
    return result


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
    return project_iso((x, y, z)), x * 0.612372 + y * 0.5 - z * 0.612372


def render_projected_icon(model: dict, texture_resolver: Callable[[str], Path | None],
                         gui_scale: tuple[float, float, float] = (0.625, 0.625, 0.625),
                         gui_rotation: tuple[float, float, float] = (30.0, 225.0, 0.0),
                         size: int = 64, view: str = "isometric",
                         depth_buffer: bool | None = None,
                         pixels_per_unit: float | None = None,
                         projection_offset: tuple[float, float] = (0.0, 0.0),
                         camera_distance: float = 48.0,
                         face_shade: dict[str, float] | None = None,
                         return_face_ids: bool = False):
    """Render a textured isometric icon approximation for visual batch QA.

    Uses source face UVs, texture alpha, an orthographic GUI projection, sorted
    cuboid faces, and simple block-face shading. It is deliberately a lightweight
    preview, not a replacement for Minecraft's GPU renderer.
    """
    if face_shade is None:
        face_shade = FACE_SHADE
    quads = []
    offset_for_buffer = projection_offset
    for element_index, element in enumerate(model.get("elements", [])):
        for face_name, face in element.get("faces", {}).items():
            if face_name not in FACE_VERTICES or not isinstance(face, dict):
                continue
            # Minecraft 做背面剔除；负尺寸 cube 的绕序翻转让内面成为正面。
            # 不剔除会把镂空灯罩画成实心块、让背面盖住正面细节。
            # 只在 GUI 等轴测视图剔除：GUI_VIEW_DIR 是该相机特有的视向，
            # front/side/top 等正交视图用于公告板/碰撞预览，相机方向不同，
            # 不能套用，否则会把那些视图的正面误剔除。
            if view == "isometric" and not face_is_front_facing(element, face_name, gui_rotation):
                continue
            if view == "isometric":
                # 直接复刻游戏的变换链：模型点经 display 旋转/缩放后正交投影。
                root_transform = model.get("transform")
                projections_and_depths = []
                for point in (apply_root_transform(raw, root_transform)
                              for raw in _element_points(element, face_name)):
                    screen, depth = gui_screen_point(point, gui_rotation)
                    projections_and_depths.append((
                        (screen[0] * gui_scale[0] + projection_offset[0],
                         screen[1] * gui_scale[1] + projection_offset[1]),
                        depth * gui_scale[2]))
                projected = [item[0] for item in projections_and_depths]
                depths = [item[1] for item in projections_and_depths]
                offset_for_buffer = (0.0, 0.0)
            else:
                points = [rotate_for_display(point, gui_rotation)
                          for point in _element_points(element, face_name)]
                scaled_points = [tuple(8.0 + (point[i] - 8.0) * gui_scale[i] for i in range(3)) for point in points]
                projections_and_depths = [_project_view(point, view, camera_distance) for point in scaled_points]
                projected = [item[0] for item in projections_and_depths]
                depths = [item[1] for item in projections_and_depths]
                offset_for_buffer = projection_offset
            depth = sum(depths) / len(depths)
            uv = face.get("uv")
            texture_ref = resolve_texture_reference(model, str(face.get("texture", "")))
            texture_path = texture_resolver(texture_ref) if texture_ref else None
            texture = load_sprite(texture_path) if texture_path else None
            texture = tinted_water_sprite(texture, texture_ref)
            uv_points = None
            if uv and texture:
                rotation = (int(face.get("rotation", 0)) // 90) % 4
                order = [(i + rotation) % 4 for i in range(4)]
                uv_points = []
                for index in order:
                    u = uv[0] if index in (0, 1) else uv[2]
                    v = uv[1] if index in (0, 3) else uv[3]
                    uv_points.append((u * texture.width / 16.0, v * texture.height / 16.0))
            quads.append((depth, face_name, projected, texture, uv_points, depths,
                          element_index))

    # GUI 等轴测默认走逐像素 z-buffer：Minecraft 用深度缓冲决定遮挡，与 quad
    # 顺序无关；painter/元素顺序都无法同时正确处理所有模型（床要元素顺序、
    # 彩灯要深度顺序）。其它正交视图（公告板/碰撞预览）有 art-directed 叠放
    # 语义，保留 painter 深度排序。numpy 缺失时自动回退 painter。
    if depth_buffer is None:
        depth_buffer = view == "isometric"
    if depth_buffer:
        # pixels_per_unit 默认 None 在这里解析；painter 路径也会再次解析，
        # 但 z-buffer 路径在调用前就要用到它，不能把 None 传进去。
        ppm = pixels_per_unit or (size / 16.0)
        ids = np_zero_ids(size) if return_face_ids else None
        try:
            image = _render_projected_depth_buffer(quads, size, face_shade, view,
                                                   ppm, offset_for_buffer, ids)
            return (image, ids) if return_face_ids else image
        except ModuleNotFoundError as error:
            if error.name != "numpy":
                raise
            # Keep asset review usable in the project's minimal Pillow-only
            # environment. The painter fallback is approximate for intersecting
            # translucent faces, but is adequate for ordinary opaque BB cubes.

    ids = np_zero_ids(size) if return_face_ids else None
    output = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pixels_per_unit = pixels_per_unit or (size / 16.0)
    # Minecraft 的方块模型没有逐 quad 深度排序：同一 render type 内就是按
    # 元素（再按面）的声明顺序绘制，后画的盖住先画的。GUI 等轴测必须照此，
    # 否则按深度排序会让白色床垫盖住床的绿色被子（实测），与游戏内不符。
    # quads 已经按元素顺序 append，所以等轴测视图直接按插入顺序绘制即可。
    # front/side/top 是公告板/碰撞预览用的正交视图，仍按深度排序让贴纸类
    # 前层可见。
    if view != "isometric":
        reverse_depth = view in ("front", "side", "perspective_front")
        quads = sorted(quads, key=lambda item: item[0], reverse=reverse_depth)
    for (_depth, face_name, projected, texture, uv_points, _vertex_depths,
         _element_index) in quads:
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
            apply_alpha_cutout(face_image)
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
    return (output, ids) if return_face_ids else output


def _render_projected_depth_buffer(quads, size: int, face_shade: dict[str, float], view: str,
                                   pixels_per_unit: float, projection_offset: tuple[float, float],
                                   face_ids_out=None) -> Image.Image:
    """Rasterize projected faces per pixel: barycentric depth, UV, texel fetch.

    A single perspective transform per quad (Pillow) cannot sample a face whose UV
    rectangle is degenerate or nearly so - flat foliage panels are exported with
    u1 == u2, and the matrix inversion then fails, which silently dropped the whole
    face. Barycentric interpolation over the same two triangles that carry the depth
    has no such singularity, and it is what the GPU actually does, so per-pixel UV
    interpolation replaces the per-quad transform.
    """
    import numpy as np

    output = np.zeros((size, size, 3), dtype=np.float64)
    alpha_buffer = np.zeros((size, size), dtype=np.float64)
    z_buffer = np.full((size, size), np.inf, dtype=np.float64)
    # 正交投影（本项目所有视图都是正交）下深度沿屏幕线性变化，直接按重心
    # 坐标插值 depth；逆深度插值是透视投影才用的，套在正交上会让平面 quad
    # 的深度非线性，相交处互相撕出破洞。
    keep_max = view in ("top", "isometric")  # 这些视图 depth 越大越靠近相机
    depth_init = -np.inf if keep_max else np.inf
    cutout = ALPHA_CUTOUT / 255.0

    for (_average_depth, face_name, projected, texture, uv_points, vertex_depths,
         element_index) in quads:
        destination = [(size / 2 + (x + projection_offset[0]) * pixels_per_unit,
                        size / 2 + (y + projection_offset[1]) * pixels_per_unit) for x, y in projected]
        left = max(0, int(math.floor(min(p[0] for p in destination))))
        top = max(0, int(math.floor(min(p[1] for p in destination))))
        right = min(size, int(math.ceil(max(p[0] for p in destination))) + 1)
        bottom = min(size, int(math.ceil(max(p[1] for p in destination))) + 1)
        if right <= left or bottom <= top:
            continue
        shade = face_shade[face_name]
        sprite = None
        if texture is not None and uv_points is not None:
            sprite = np.asarray(texture.convert("RGBA"), dtype=np.float64) / 255.0
            sprite_height, sprite_width = sprite.shape[0], sprite.shape[1]

        # 像素中心采样，与 GPU 的多边形覆盖规则一致（边界像素归入三角形）。
        grid_x, grid_y = np.meshgrid(np.arange(left, right) + 0.5,
                                     np.arange(top, bottom) + 0.5)
        region_depth = z_buffer[top:bottom, left:right]
        region_rgb = output[top:bottom, left:right]
        region_alpha = alpha_buffer[top:bottom, left:right]
        region_ids = (face_ids_out[top:bottom, left:right]
                      if face_ids_out is not None else None)
        face_id = element_index * 8 + FACE_IDS.get(face_name, 0)

        for triangle in ((0, 1, 2), (0, 2, 3)):
            points = [destination[index] for index in triangle]
            depths = [float(vertex_depths[index]) for index in triangle]
            (x0, y0), (x1, y1), (x2, y2) = points
            denominator = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
            if abs(denominator) < 1e-10:
                continue
            w0 = ((y1 - y2) * (grid_x - x2) + (x2 - x1) * (grid_y - y2)) / denominator
            w1 = ((y2 - y0) * (grid_x - x2) + (x0 - x2) * (grid_y - y2)) / denominator
            w2 = 1.0 - w0 - w1
            inside = (w0 >= -1e-7) & (w1 >= -1e-7) & (w2 >= -1e-7)
            if not inside.any():
                continue
            depth_map = np.full(inside.shape, depth_init, dtype=np.float64)
            depth_map[inside] = (w0[inside] * depths[0] + w1[inside] * depths[1]
                                 + w2[inside] * depths[2])
            compare_depth = -depth_map if keep_max else depth_map
            # 深度比较用 <=：原版 cutout/translucent 的深度测试是 GL_LEQUAL，
            # 深度相同的后画者胜。薄壁模型（玻璃杯壁、帐篷布面）大量出现等深重合，
            # 用 < 会让先画的面永远占优，与游戏挑中的面不同，整片面偏色。
            closer = inside & (compare_depth <= region_depth)

            if sprite is None:
                flat = tuple(int(160 * shade) for _ in range(3))
                region_rgb[closer] = flat
                region_alpha[closer] = 1.0
                region_depth[closer] = compare_depth[closer]
                if region_ids is not None:
                    region_ids[closer] = face_id
                continue

            u = (w0 * uv_points[triangle[0]][0] + w1 * uv_points[triangle[1]][0]
                 + w2 * uv_points[triangle[2]][0])
            v = (w0 * uv_points[triangle[0]][1] + w1 * uv_points[triangle[1]][1]
                 + w2 * uv_points[triangle[2]][1])
            # 纹素中心取样：UV 是纹素单位，向下取整就是该纹素。
            texel_u = np.clip(u.astype(np.int64), 0, sprite_width - 1)
            texel_v = np.clip(v.astype(np.int64), 0, sprite_height - 1)
            texel = sprite[texel_v, texel_u]
            opaque = closer & (texel[:, :, 3] >= cutout)
            if not opaque.any():
                continue
            region_rgb[opaque] = texel[:, :, :3][opaque] * shade
            region_alpha[opaque] = 1.0
            region_depth[opaque] = compare_depth[opaque]
            if region_ids is not None:
                region_ids[opaque] = face_id

    rgba = np.zeros((size, size, 4), dtype=np.uint8)
    rgba[:, :, :3] = np.clip(output * 255.0, 0, 255).astype(np.uint8)
    rgba[:, :, 3] = np.clip(alpha_buffer * 255.0, 0, 255).astype(np.uint8)
    return Image.fromarray(rgba, mode="RGBA")


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
            # visible_projected_measurements 固定测 GUI 相机下的可见像素，
            # 必须与 Minecraft 一样剔除背面，否则背面（以及负尺寸灯罩被误
            # 当成实心块）会污染 fit 的尺寸与居中测量。
            if not face_is_front_facing(element, face_name, gui_rotation):
                continue
            # 与渲染同一套变换，否则 fit 算出的尺寸和游戏里差一个镜像。
            root_transform = model.get("transform")
            projected = [gui_screen_point(apply_root_transform(point, root_transform), gui_rotation)[0]
                          for point in _element_points(element, face_name)]
            projected_all.extend(projected)
            uv = face.get("uv")
            texture_ref = resolve_texture_reference(model, str(face.get("texture", "")))
            texture_path = texture_resolver(texture_ref) if texture_ref else None
            texture = load_sprite(texture_path) if texture_path else None
            texture = tinted_water_sprite(texture, texture_ref)
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
            # 与渲染路径一致：半透明 texel 在 alpha<128 时完全不可见，
            # 不能把它们算进图标的可视边界（否则 fit 会按透明边算尺寸）。
            face_alpha = face_alpha.point(lambda value: 255 if value >= ALPHA_CUTOUT else 0)
        alpha_union.paste(ImageChops.lighter(alpha_union.crop((left, top, right, bottom)), face_alpha), (left, top))

    bbox = alpha_union.getbbox()
    if bbox is None:
        return None
    alpha_crop = alpha_union.crop(bbox)
    total_alpha = 0
    weighted_x = 0.0
    weighted_y = 0.0
    for index, alpha in enumerate(alpha_crop.get_flattened_data()):
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



