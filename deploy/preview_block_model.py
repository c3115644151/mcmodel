"""Render a shipped block model offline so geometry can be tuned before a client restart.

The game is the only ground truth, but a full restart costs minutes and a resource reload still
needs a running client. This script draws the same model json with the same uv mapping the client
bakes, so geometry can be iterated in about a second and the client is only touched once the shape
is right.

Three drawing modes exist because a model answers three different questions:
  clay   -- geometry only, one flat colour per element, for "is the shape right".
  solid  -- every texel with alpha >= 0.999, depth tested, for "what does the opaque part look like".
  blend  -- every texel with 0 < alpha < 1, composited over the solid pass far to near, for "does
            the translucent part sit the way the client draws it".

Camera: orthographic, viewer on the -Z side looking toward +Z, which is how a player standing in
front of a south-facing piece sees it.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "src/main/resources/assets/pastoral_home"
MODELS = ASSETS / "models/block"
TEXTURES = ASSETS / "textures"

FACE_VERTICES = {
    "north": ((1, 1, 0), (1, 0, 0), (0, 0, 0), (0, 1, 0)),
    "south": ((0, 1, 1), (0, 0, 1), (1, 0, 1), (1, 1, 1)),
    "east": ((1, 1, 1), (1, 0, 1), (1, 0, 0), (1, 1, 0)),
    "west": ((0, 1, 0), (0, 0, 0), (0, 0, 1), (0, 1, 1)),
    "up": ((1, 1, 1), (1, 1, 0), (0, 1, 0), (0, 1, 1)),
    "down": ((0, 0, 1), (0, 0, 0), (1, 0, 0), (1, 0, 1)),
}
FACE_ORDER = ("north", "south", "east", "west", "up", "down")

# Which element axes run right and down on each face as seen from outside, matching the uv box
# authoring convention the client uses.
FACE_SCREEN = {
    "north": (lambda o, z: 1 - o[0], lambda o, z: 1 - o[1]),
    "south": (lambda o, z: o[0], lambda o, z: 1 - o[1]),
    "east": (lambda o, z: 1 - o[2], lambda o, z: 1 - o[1]),
    "west": (lambda o, z: o[2], lambda o, z: 1 - o[1]),
    "up": (lambda o, z: o[0], lambda o, z: 1 - o[2]),
    "down": (lambda o, z: o[0], lambda o, z: o[2]),
}
# Vanilla's directional shading, which is most of what makes a flat model read as a box.
FACE_SHADE = {"up": 1.0, "down": 0.5, "north": 0.8, "south": 0.8, "east": 0.6, "west": 0.6}

UV_SCALE = 16.0  # block model uv space is 0..16 whatever the texture resolution
# Blockbench stores project uv in its own canvas units; the export maps them into the 0..16 space by
# this factor. 1.0 means the project already speaks model units.
BB_UV_SCALE = 1.0

CLAY = (0.86, 0.85, 0.82)
# Model space is the facing=north variant, so the playable side of a piece sits at low z and yaw 0
# (camera on -Z) is the front view a player standing at the block's north side gets.
VIEWS = {"front": (0.0, 0.0), "quarter": (35.0, 18.0), "iso": (45.0, 30.0), "top": (0.0, 70.0)}

MODE_CLAY = "clay"
MODE_CUTOUT = "cutout"   # --no-blend: any painted texel wins, nobody composites
MODE_SOLID = "solid"
MODE_BLEND = "blend"


def rotate(point, rotation: dict):
    origin = rotation.get("origin", (8.0, 8.0, 8.0))
    axis = rotation["axis"]
    angle = math.radians(rotation["angle"])
    index = "xyz".index(axis)
    local = [point[i] - origin[i] for i in range(3)]
    c, s = math.cos(angle), math.sin(angle)
    a, b = [i for i in range(3) if i != index]
    ra = c * local[a] - s * local[b]
    rb = s * local[a] + c * local[b]
    local[a], local[b] = ra, rb
    return tuple(local[i] + origin[i] for i in range(3))


def face_points(element: dict, face: str):
    low, high = element["from"], element["to"]
    points = []
    for xbit, ybit, zbit in FACE_VERTICES[face]:
        point = (high[0] if xbit else low[0], high[1] if ybit else low[1], high[2] if zbit else low[2])
        if element.get("rotation"):
            point = rotate(point, element["rotation"])
        points.append(point)
    return points


def face_uvs(element: dict, face: str):
    uv = element["faces"][face].get("uv")
    if uv is None:
        return None
    u1, v1, u2, v2 = (float(value) for value in uv)
    if abs(u2 - u1) < 1e-6 or abs(v2 - v1) < 1e-6:
        return None
    right, down = FACE_SCREEN[face]
    out = []
    for bits in FACE_VERTICES[face]:
        s, t = right(bits, None), down(bits, None)
        out.append(((u1 + s * (u2 - u1)) / UV_SCALE, (v1 + t * (v2 - v1)) / UV_SCALE))
    return out


def texture_ref(model: dict, name: str) -> str:
    textures = model.get("textures", {})
    seen = set()
    while name.startswith("#") and name[1:] in textures and name[1:] not in seen:
        seen.add(name[1:])
        name = textures[name[1:]]
    if name.startswith("#"):
        return "pastoral_home:block/piano"
    return name


# Animated textures are one column of square frames under a .png.mcmeta descriptor; the game reads uv
# against a single frame, so the preview must crop one too or every window stretches across the strip.
ANIM_FRAME = 0


def load_texture(ref: str) -> Image.Image:
    path = TEXTURES / (ref.split(":", 1)[1] + ".png")
    image = Image.open(path).convert("RGBA")
    meta = path.parent / (path.name + ".mcmeta")
    if not meta.exists():
        return image
    animation = (json.loads(meta.read_text(encoding="utf-8")) or {}).get("animation")
    if not animation:
        return image
    frame = int(animation.get("height") or image.width)
    frames = max(1, image.height // frame)
    top = (int(ANIM_FRAME) % frames) * frame
    cropped = image.crop((0, top, image.width, top + frame))
    print("[anim] " + path.name + " is a " + str(frames) + " frame strip, previewing frame "
          + str(int(ANIM_FRAME) % frames) + " of " + str(image.width) + "x" + str(frame))
    return cropped


def load_model(name: str) -> dict:
    path = MODELS / (name + ".json")
    if not path.exists():
        raise SystemExit("missing model " + str(path))
    return json.loads(path.read_text(encoding="utf-8"))


def from_bbmodel(path: Path, frame: int = 0):
    """Load a Blockbench project as a java_block model plus the textures it embeds.

    Blockbench hides textures inside data urls, and packs extra palettes of the same drawing as rows
    under the frame uv_width/uv_height describe, so the frame asked for is cropped out first.
    The uv numbers themselves are already the 0..16 model-unit space a java block model uses -- the
    project's own java_block export copies them verbatim -- so they pass through unscaled. Scaling
    them by 16/uv_width halves every window at 32px resolution and the sampling lands on the wrong
    palette cell.
    """
    import base64
    import io

    data = json.loads(path.read_text(encoding="utf-8"))
    textures = {}
    cache = {}
    sizes = {}
    for index, texture in enumerate(data.get("textures", [])):
        key = "t" + str(index)
        unique = "bb_" + path.stem + "_" + key
        source = texture.get("source") or ""
        if source.startswith("data:"):
            image = Image.open(io.BytesIO(base64.b64decode(source.split(",", 1)[1]))).convert("RGBA")
        else:
            image = Image.open(path.parent / source).convert("RGBA")
        frame_width = float(texture.get("uv_width") or image.width)
        frame_height = float(texture.get("uv_height") or image.height)
        frames = max(1, round(image.height / frame_height))
        top = int((frame % frames) * frame_height)
        image = image.crop((0, top, int(frame_width), top + int(frame_height)))
        cache[unique] = image
        textures[key] = unique
    elements = []
    for element in data.get("elements", []):
        if element.get("visibility") is False:
            continue
        faces = {}
        for face, info in element.get("faces", {}).items():
            uv = info.get("uv")
            index = info.get("texture")
            if uv is None or index is None:
                continue
            key = "t" + str(index)
            if key not in textures:
                continue
            faces[face] = {"texture": "#" + key,
                           "uv": [uv[0] * BB_UV_SCALE, uv[1] * BB_UV_SCALE,
                                  uv[2] * BB_UV_SCALE, uv[3] * BB_UV_SCALE]}
        elements.append({"name": element.get("name", ""), "from": element["from"],
                         "to": element["to"], "faces": faces})
    return {"elements": elements, "textures": textures}, cache


def face_coverage(alpha, uvs) -> float:
    """How much of a face is actually painted: a fully transparent face hides nothing in game."""
    height, width = alpha.shape[:2]
    us = [uv[0] for uv in uvs]
    vs = [uv[1] for uv in uvs]
    x0 = max(0, min(width - 1, int(min(us) * width)))
    x1 = max(x0 + 1, min(width, int(math.ceil(max(us) * width))))
    y0 = max(0, min(height - 1, int(min(vs) * height)))
    y1 = max(y0 + 1, min(height, int(math.ceil(max(vs) * height))))
    region = alpha[y0:y1, x0:x1]
    return float((region >= 0.5).mean()) if region.size else 0.0


def collect_model(model: dict, shift, offset_scale: float, texture_cache=None):
    quads = []
    texture_cache = {} if texture_cache is None else texture_cache
    for index, element in enumerate(model["elements"]):
        for face in FACE_ORDER:
            if face not in element["faces"]:
                continue
            uvs = face_uvs(element, face)
            if uvs is None:
                continue
            ref = texture_ref(model, element["faces"][face].get("texture", "#missing"))
            if ref not in texture_cache:
                texture_cache[ref] = load_texture(ref)
            if (ref, "alpha") not in texture_cache:
                texture_cache[(ref, "alpha")] = (
                        np.asarray(texture_cache[ref], dtype=np.float64)[..., 3] / 255.0)
            points = [((p[0] + shift[0]) * offset_scale, (p[1] + shift[1]) * offset_scale,
                       p[2] * offset_scale)
                      for p in face_points(element, face)]
            quads.append({
                "points": points,
                "uvs": uvs,
                "texture": texture_cache[ref],
                "coverage": face_coverage(texture_cache[(ref, "alpha")], uvs),
                "blended": bool(((texture_cache[(ref, "alpha")] > 0.004) & (
                        texture_cache[(ref, "alpha")] < 0.999)).any()),
                "shade": FACE_SHADE[face],
                "face": face,
                "element": index,
                "name": element.get("name", ""),
            })
    return quads


def collect(cells, offset_scale: float):
    quads = []
    texture_cache = {}
    for name, shift in cells:
        quads.extend(collect_model(load_model(name), shift, offset_scale, texture_cache))
    return quads


def project(point, yaw: float, pitch: float):
    x, y, z = point
    ca, sa = math.cos(yaw), math.sin(yaw)
    x1 = x * ca + z * sa
    z1 = -x * sa + z * ca
    cp, sp = math.cos(pitch), math.sin(pitch)
    y1 = y * cp - z1 * sp
    z2 = y * sp + z1 * cp
    return x1, -y1, z2


def fit_scale(quads, yaw_deg: float, pitch_deg: float, width: int, height: int,
              margin: float = 0.96) -> float:
    """Pixels per model unit that make every quad fit the frame in this view."""
    yaw, pitch = math.radians(yaw_deg), math.radians(pitch_deg)
    xs, ys = [], []
    for quad in quads:
        for point in quad["points"]:
            x, y, _ = project(point, yaw, pitch)
            xs.append(x)
            ys.append(y)
    dx = max(max(xs) - min(xs), 1e-6)
    dy = max(max(ys) - min(ys), 1e-6)
    return min(width * margin / dx, height * margin / dy)


class Canvas:
    """Colour, opaque depth and blend depth buffers plus the counters a check report needs."""

    def __init__(self, width: int, height: int, background=(0, 0, 0, 0)):
        self.width = width
        self.height = height
        self.buffer = np.zeros((height, width, 4), dtype=np.float64)
        for channel, value in enumerate(background):
            self.buffer[..., channel] = value / 255.0
        self.depth = np.full((height, width), np.inf)
        self.depth_blend = np.full((height, width), np.inf)
        self.dropped = 0


def alpha_mask(quad, mode):
    """Texels this pass may paint. One pass decides it, so two passes cannot disagree."""
    texture = np.asarray(quad["texture"], dtype=np.float64)
    alpha = texture[..., 3] / 255.0
    if mode == MODE_CUTOUT:
        return alpha > 0.004
    if mode == MODE_SOLID:
        return alpha >= 0.999
    return (alpha > 0.004) & (alpha < 0.999)


def draw_quad(canvas: Canvas, quad, pixels, mode: str, floor: float):
    """One quad, one pass through one rasteriser.

    Every mode shares this function so a change cannot fix one mode and quietly break the other;
    the pass only chooses which texels paint and whether depth or src-over applies.
    """
    if quad.get("coverage", 1.0) < floor:
        canvas.dropped += 1
        return
    texture = np.asarray(quad["texture"], dtype=np.float64)
    tex_h, tex_w = texture.shape[:2]
    keep = None if mode == MODE_CLAY else alpha_mask(quad, mode)
    shade = quad["shade"]
    for tri in ((0, 1, 2), (0, 2, 3)):
        (ax, ay, az), (bx, by, bz), (cx2, cy2, cz) = [pixels[i] for i in tri]
        (ua, va), (ub, vb), (uc, vc) = [quad["uvs"][i] for i in tri]
        area = (bx - ax) * (cy2 - ay) - (by - ay) * (cx2 - ax)
        if abs(area) < 1e-9:
            continue
        x0 = max(int(math.floor(min(ax, bx, cx2))), 0)
        x1 = min(int(math.ceil(max(ax, bx, cx2))), canvas.width - 1)
        y0 = max(int(math.floor(min(ay, by, cy2))), 0)
        y1 = min(int(math.ceil(max(ay, by, cy2))), canvas.height - 1)
        if x1 < x0 or y1 < y0:
            continue
        px, py = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        w0 = ((bx - px) * (cy2 - py) - (by - py) * (cx2 - px)) / area
        w1 = ((cx2 - px) * (ay - py) - (cy2 - py) * (ax - px)) / area
        w2 = 1.0 - w0 - w1
        inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
        if not inside.any():
            continue
        interpolated_u = w0 * ua + w1 * ub + w2 * uc
        interpolated_v = w0 * va + w1 * vb + w2 * vc
        interpolated_z = w0 * az + w1 * bz + w2 * cz
        sub_depth = canvas.depth[y0:y1 + 1, x0:x1 + 1]
        closer = inside & (interpolated_z < sub_depth - 1e-6)
        if mode == MODE_BLEND:
            closer = closer & (interpolated_z < canvas.depth_blend[y0:y1 + 1, x0:x1 + 1] - 1e-6)
        if not closer.any():
            continue
        sub = canvas.buffer[y0:y1 + 1, x0:x1 + 1]
        if mode == MODE_CLAY:
            body = CLAY if quad.get("clay") is None else quad["clay"]
            tint = 1.0 + ((quad.get("element", 0) * 37) % 7 - 3) * 0.02
            rgb = np.empty(sub.shape[:2] + (3,), dtype=np.float64)
            rgb[...] = np.array(body, dtype=np.float64) * shade * tint
            alpha_out = None
        else:
            tu = np.clip((interpolated_u * tex_w).astype(int) % tex_w, 0, tex_w - 1)
            tv = np.clip((interpolated_v * tex_h).astype(int) % tex_h, 0, tex_h - 1)
            texel = texture[tv, tu]
            if keep is not None:
                closer = closer & keep[tv, tu]
                if not closer.any():
                    continue
            rgb = texel[..., :3] / 255.0 * shade
            alpha_out = texel[..., 3] / 255.0
        if mode == MODE_BLEND:
            src_a = alpha_out[..., None]
            blended_rgb = sub[..., :3] * (1.0 - src_a) + rgb * src_a
            sub[..., :3] = np.where(closer[..., None], blended_rgb, sub[..., :3])
            sub[..., 3] = np.where(closer, sub[..., 3] * (1.0 - alpha_out) + alpha_out, sub[..., 3])
            canvas.depth_blend[y0:y1 + 1, x0:x1 + 1][closer] = interpolated_z[closer]
        else:
            sub[closer, 0] = rgb[closer, 0]
            sub[closer, 1] = rgb[closer, 1]
            sub[closer, 2] = rgb[closer, 2]
            sub[closer, 3] = 1.0
            sub_depth[closer] = interpolated_z[closer]


def render(quads, out: Path, scale: float, yaw_deg: float, pitch_deg: float,
           width: int, height: int, background=(0, 0, 0, 0), pan=(0.0, 0.0), clay=None,
           focus=None, blend=True):
    """Draw every quad and centre the frame on the focus set (default: all quads).

    Textured passes composite the way the client does: fully opaque texels go into a depth-tested
    buffer first, then every texel that carries partial alpha is blended over it from far to near.
    A cutout pass (alpha < 0.5 is gone) reads a translucent lamp shell as a solid slab and buries
    the core inside it, which is exactly the look this preview has to reproduce.
    """
    yaw, pitch = math.radians(yaw_deg), math.radians(pitch_deg)
    projected = [(quad, [project(point, yaw, pitch) for point in quad["points"]]) for quad in quads]

    framed = projected if focus is None else [
        (quad, [project(point, yaw, pitch) for point in quad["points"]]) for quad in focus]
    xs = [p[0] for _, screen in framed for p in screen]
    ys = [p[1] for _, screen in framed for p in screen]
    # pan is in projected model units, positive = right / up in the drawing.
    cx = (min(xs) + max(xs)) * 0.5 + pan[0]
    cy = (min(ys) + max(ys)) * 0.5 + pan[1]

    canvas = Canvas(width, height, background)

    def to_pixels(screen):
        return [(width * 0.5 + (p[0] - cx) * scale, height * 0.5 + (p[1] - cy) * scale, p[2])
                for p in screen]

    floor = 0.2 if clay is not None else 0.0
    if clay is not None:
        for quad in quads:
            quad["clay"] = clay

    solid, blended = [], []
    for quad, screen in projected:
        if clay is None and blend and quad["blended"]:
            blended.append((quad, to_pixels(screen)))
        else:
            solid.append((quad, to_pixels(screen)))
    mode = MODE_CLAY if clay is not None else (MODE_SOLID if blend else MODE_CUTOUT)
    for quad, pixels in solid:
        draw_quad(canvas, quad, pixels, mode, floor)
    # Far to near: a shell in front of its core has the larger z and must be composited last.
    blended.sort(key=lambda item: -sum(p[2] for p in item[1]) / 4.0)
    for quad, pixels in blended:
        draw_quad(canvas, quad, pixels, MODE_BLEND, floor)

    edge = np.zeros(canvas.depth.shape, dtype=bool)
    for dy, dx in ((0, 1), (1, 0)):
        a = canvas.depth[: canvas.depth.shape[0] - dy or None, : canvas.depth.shape[1] - dx or None]
        b = canvas.depth[dy:, dx:]
        jump = np.zeros(canvas.depth.shape, dtype=bool)
        pair = np.isfinite(a) & np.isfinite(b)
        with np.errstate(invalid="ignore"):
            jump[: a.shape[0], : a.shape[1]] = pair & (np.abs(a - b) > 0.35)
        edge |= jump
    canvas.buffer[edge, :3] *= 0.55
    image = Image.fromarray((np.clip(canvas.buffer, 0, 1) * 255).astype(np.uint8), "RGBA")
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)
    print("wrote " + str(out.relative_to(ROOT))
          + (" (dropped " + str(canvas.dropped) + " see-through faces)" if canvas.dropped else ""))
    return image


def contact_sheet(quads, out: Path, view_names, scale, width: int, height: int,
                  background=(0, 0, 0, 0), clay=None, pan=(0.0, 0.0), focus=None,
                  blend=True):
    """Renders each named view and tiles them side by side in one image.

    scale None means auto-fit: one scale shared by every tile, taken from the tightest view, so
    the tiles stay comparable in size while nothing is clipped.
    """
    from PIL import ImageDraw

    framed = quads if focus is None else focus
    if scale is None:
        scale = min(fit_scale(framed, *VIEWS[name], width, height) for name in view_names)
    tiles = []
    for name in view_names:
        if name not in VIEWS:
            raise SystemExit("unknown view " + name + "; pick from " + str(sorted(VIEWS)))
        yaw, pitch = VIEWS[name]
        tile_path = out.parent / (".tile_" + name + ".png")
        tiles.append((name, render(quads, tile_path, scale, yaw, pitch, width, height,
                                   background=background, pan=pan, clay=clay, focus=framed,
                                   blend=blend)))
    sheet = Image.new("RGBA", (width * len(tiles), height), background)
    draw = ImageDraw.Draw(sheet)
    for index, (name, image) in enumerate(tiles):
        sheet.paste(image, (index * width, 0))
        draw.text((index * width + 8, 6), name, fill=(255, 255, 255, 255))
        (out.parent / (".tile_" + name + ".png")).unlink(missing_ok=True)
    sheet.save(out)
    print("wrote " + str(out.relative_to(ROOT)))
    return sheet


def summarize(quads, image, mode: str, dropped: int = 0) -> str:
    """Numbers that say whether a render is plausible; eyes alone keep misreading a bad one."""
    pixels = np.asarray(image, dtype=np.float64)
    painted = pixels[..., 3] > 127.5
    frame_px = pixels.shape[0] * pixels.shape[1]
    total = max(int(painted.sum()), 1)
    rows = np.where(painted.any(axis=1))[0]
    cols = np.where(painted.any(axis=0))[0]
    box = (int(cols[0]), int(rows[0]), int(cols[-1]), int(rows[-1])) if painted.any() else None
    invisible = sum(1 for quad in quads if quad.get("coverage", 1.0) <= 0.0)
    alphas = [np.asarray(quad["texture"], dtype=np.float64)[..., 3].reshape(-1) / 255.0
              for quad in quads]
    flat = np.concatenate(alphas) if alphas else np.zeros(1)
    opaque = float((flat >= 0.999).mean())
    partial = float(((flat > 0.004) & (flat < 0.999)).mean())
    mean = pixels[painted][:, :3].mean(axis=0) if painted.any() else np.zeros(3)
    share = 100.0 * total / frame_px
    return ("[check] faces=" + str(len(quads)) + " fully-transparent=" + str(invisible)
            + " dropped=" + str(dropped) + " mode=" + mode + "\n"
            + "[check] painted=" + format(share, ".1f") + "% bbox=" + str(box)
            + " mean_rgb=(" + format(mean[0], ".0f") + "," + format(mean[1], ".0f")
            + "," + format(mean[2], ".0f") + ")\n"
            + "[check] texture alpha opaque=" + format(opaque, ".2%")
            + " partial=" + format(partial, ".2%"))


USAGE = ("usage: preview_block_model.py [MODEL[:SHIFT][,MODEL[:SHIFT]] | --raw PATH] "
         "--out PATH [--yaw DEG] [--pitch DEG] [--scale N | --fit] [--size WxH] [--pan X,Y] "
         "[--clay [R,G,B]] [--bg R,G,B] [--views front,quarter,top] [--textured] "
         "[--no-blend] [--only PREFIX] [--only-elements IDX,IDX] [--frame N] [--anim-frame N] "
         "[--uv-scale N] [--check]")

VALUE_FLAGS = {"--out", "--yaw", "--pitch", "--scale", "--size", "--pan", "--bg", "--views",
               "--raw", "--only", "--frame", "--only-elements", "--anim-frame", "--uv-scale"}
BARE_FLAGS = {"--fit", "--textured", "--no-blend", "--check"}


def parse_cells(spec: str):
    """name:dx,dy -- the shift is in model pixels, so a second storey is name:0,16."""
    cells = []
    for part in spec.split(";"):
        name, _, shift = part.partition(":")
        values = [float(value) for value in shift.split(",")] if shift else []
        dx = values[0] if values else 0.0
        dy = values[1] if len(values) > 1 else 0.0
        cells.append((name, (dx, dy)))
    return cells


def parse_argv(argv: list[str]) -> dict:
    """Order-independent, so --frame applies to --raw no matter where it sits on the line."""
    options = {"cells": None, "values": {}, "bare": set()}
    args = list(argv)
    if not args:
        raise SystemExit(USAGE)
    if not args[0].startswith("--"):
        options["cells"] = parse_cells(args[0])
        args = args[1:]
    index = 0
    while index < len(args):
        flag = args[index]
        if flag == "--clay":
            # The one flag with an optional value, so it is resolved by shape not by position.
            raw = args[index + 1] if index + 1 < len(args) else None
            if raw and not raw.startswith("--") and "," in raw:
                options["values"]["--clay"] = raw
                index += 2
            else:
                options["bare"].add("--clay")
                index += 1
            continue
        if flag in BARE_FLAGS:
            options["bare"].add(flag)
            index += 1
            continue
        if flag not in VALUE_FLAGS:
            raise SystemExit("unknown flag " + flag)
        if index + 1 >= len(args):
            raise SystemExit(flag + " needs a value")
        options["values"][flag] = args[index + 1]
        index += 2
    return options


def main(argv: list[str]) -> None:
    global ANIM_FRAME, BB_UV_SCALE
    options = parse_argv(argv)
    values, bare = options["values"], options["bare"]
    ANIM_FRAME = int(values.get("--anim-frame", "0"))
    BB_UV_SCALE = float(values.get("--uv-scale", "1.0"))
    out = ROOT / values.get("--out", "build/preview_keybed/preview.png")
    yaw = float(values.get("--yaw", 0.0))
    pitch = float(values.get("--pitch", 0.0))
    scale = float(values.get("--scale", 16.0))
    width, height = (int(v) for v in values.get("--size", "900x520").lower().split("x"))
    pan = [float(v) for v in values.get("--pan", "0,0").split(",")]
    # No --bg keeps the transparent frame; an explicit colour is opaque unless told otherwise.
    background = ((tuple(int(v) for v in values["--bg"].split(",")) + (255,))
                  if "--bg" in values else (0, 0, 0, 0))
    clay = None
    if "--clay" in bare:
        clay = CLAY
    elif "--clay" in values:
        clay = tuple(float(v) / 255.0 for v in values["--clay"].split(","))
    if "--textured" in bare and clay is not None:
        raise SystemExit("--clay and --textured contradict each other; pick one")
    views = [part.strip() for part in values.get("--views", "").split(",") if part.strip()]
    only = values.get("--only")
    frame_index = int(values.get("--frame", 0))
    listed = [int(part) for part in values.get("--only-elements", "").split(",") if part.strip()]
    only_elements = set(listed) or None
    blend = "--no-blend" not in bare

    if "--raw" in values:
        raw_path = ROOT / values["--raw"]
        if raw_path.suffix.lower() == ".bbmodel":
            raw_model, cache = from_bbmodel(raw_path, frame_index)
        else:
            raw_model, cache = json.loads(raw_path.read_text(encoding="utf-8")), None
        quads = collect_model(raw_model, (0.0, 0.0), 1.0, cache)
    elif options["cells"] is not None:
        quads = collect(options["cells"], 1.0)
    else:
        raise SystemExit(USAGE)
    # --only narrows the framing target, not the drawing: fit and centre on the named elements but
    # still draw everything, which is how a keyboard close-up is taken without guessing pan values.
    if only_elements is not None:
        # A reference sheet can hold several copies of a piece; draw one so two renders share a frame.
        quads = [quad for quad in quads if quad["element"] in only_elements]
    focus = [quad for quad in quads if quad["name"].startswith(only)] if only else None
    if only and not focus:
        raise SystemExit("--only " + only + ": no element name starts with that")
    if "--fit" in bare and not views:
        scale = fit_scale(focus or quads, yaw, pitch, width, height)
    if views:
        image = contact_sheet(quads, out, views, None if "--fit" in bare else scale, width, height,
                              background=background, clay=clay, pan=(pan[0], pan[1]), focus=focus,
                              blend=blend)
    else:
        image = render(quads, out, scale, yaw, pitch, width, height, background=background,
                       pan=(pan[0], pan[1]), clay=clay, focus=focus, blend=blend)
    if "--check" in bare:
        mode = MODE_CLAY if clay is not None else (MODE_BLEND if blend else MODE_CUTOUT)
        print(summarize(quads, image, mode))


if __name__ == "__main__":
    main(sys.argv[1:])
